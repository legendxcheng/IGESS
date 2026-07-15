"""Strict, canonical persistence for YAML-backed authoring entities."""

from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Any, Mapping, NoReturn

import yaml
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode, ScalarNode, SequenceNode
from yaml.tokens import (
    AliasToken,
    BlockEndToken,
    BlockMappingStartToken,
    BlockSequenceStartToken,
    FlowMappingEndToken,
    FlowMappingStartToken,
    FlowSequenceEndToken,
    FlowSequenceStartToken,
)

from .change import ModelChange
from .entity_schema import (
    EntitySchema,
    ValidationContext,
    get_entity_schema,
    validate_entity_fields,
)
from .response import AuthoringError


_MAX_SOURCE_BYTES = 4 * 1024 * 1024
_MAX_NESTING_DEPTH = 64
_MAX_CONTAINERS = 8_192
_MAX_VISITS = 32_768
_MAX_YAML_TOKENS = 32_768
_MAX_YAML_ALIASES = 4_096

# PyYAML does not resolve exponent-only values such as ``1e3`` as floats.
# Authoring YAML rejects them as numeric tokens rather than silently turning
# them into exact-decimal strings whose meaning changes when quoted.
_YAML_DECIMAL_OR_EXPONENT_RE = re.compile(
    r"^(?:"
    r"[-+]?(?:[0-9][0-9_]*)?\.[0-9_]+(?:[eE][-+]?[0-9]+)?"
    r"|[-+]?[0-9][0-9_]*(?:[eE][-+]?[0-9]+)"
    r"|[-+]?\.(?:inf|Inf|INF|nan|NaN|NAN)"
    r")$"
)


class _DuplicateKey(ValueError):
    def __init__(self, key: Any, line: int, column: int) -> None:
        super().__init__(str(key))
        self.key = key
        self.line = line
        self.column = column


class _UnsupportedFloat(ValueError):
    def __init__(self, value: str, line: int, column: int) -> None:
        super().__init__(value)
        self.value = value
        self.line = line
        self.column = column


class _UnsupportedYamlFeature(ValueError):
    def __init__(self, feature: str, line: int, column: int) -> None:
        super().__init__(feature)
        self.feature = feature
        self.line = line
        self.column = column


class _StrictConfigLoader(yaml.SafeLoader):
    """SafeLoader variant that rejects ambiguous source constructs."""

    def construct_mapping(self, node: MappingNode, deep: bool = False) -> dict[Any, Any]:
        if not isinstance(node, MappingNode):
            raise ConstructorError(
                None,
                None,
                f"expected a mapping node, but found {node.id}",
                node.start_mark,
            )
        if any(
            key_node.tag == "tag:yaml.org,2002:merge"
            for key_node, _ in node.value
        ):
            raise _UnsupportedYamlFeature(
                "merge_key",
                node.start_mark.line + 1,
                node.start_mark.column + 1,
            )

        mapping: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                duplicate = key in mapping
            except TypeError as error:
                raise ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "found unhashable key",
                    key_node.start_mark,
                ) from error
            if duplicate:
                raise _DuplicateKey(
                    key,
                    key_node.start_mark.line + 1,
                    key_node.start_mark.column + 1,
                )
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


# Resolver tables are mutable class state, so make a private copy before
# teaching this loader that exponent-only tokens are floats.
_StrictConfigLoader.yaml_implicit_resolvers = {
    key: list(resolvers)
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_StrictConfigLoader.add_implicit_resolver(
    "tag:yaml.org,2002:float",
    _YAML_DECIMAL_OR_EXPONENT_RE,
    list("-+0123456789."),
)


def _reject_float(loader: _StrictConfigLoader, node: yaml.Node) -> NoReturn:
    del loader
    raise _UnsupportedFloat(
        node.value,
        node.start_mark.line + 1,
        node.start_mark.column + 1,
    )


_StrictConfigLoader.add_constructor("tag:yaml.org,2002:float", _reject_float)


class _CanonicalConfigDumper(yaml.SafeDumper):
    """Safe dumper that keeps strict-loader numeric strings unambiguous."""


def _represent_canonical_string(
    dumper: _CanonicalConfigDumper,
    value: str,
) -> yaml.Node:
    style = "'" if _YAML_DECIMAL_OR_EXPONENT_RE.fullmatch(value) else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


_CanonicalConfigDumper.add_representer(str, _represent_canonical_string)


def read_yaml_entity(
    config_or_path: Mapping[str, Any] | str | os.PathLike[str],
    entity: str,
    entity_id: str,
) -> dict[str, Any] | None:
    """Return one validated YAML entity, or ``None`` when its id is absent.

    A mapping is useful for callers that already hold a candidate config.  A
    path is decoded as strict UTF-8 and parsed with duplicate-key detection.
    The returned native mapping is a defensive copy suitable for merge-patch
    parsing.
    """

    schema = _yaml_schema(entity)
    config = _load_config(config_or_path)
    entities = _entity_mapping(config, schema)
    if entity_id not in entities:
        return None
    fields = entities[entity_id]
    if type(fields) is not dict:
        _source_error(
            "YAML entity fields must be a mapping",
            "entity_not_mapping",
            entity=entity,
            id=entity_id,
            mapping=schema.storage_name,
            value_type=type(fields).__name__,
        )
    return _validate_entity(config, entity, entity_id, fields)


def find_yaml_duplicates(
    config_or_path: Mapping[str, Any] | str | os.PathLike[str],
    entity: str,
) -> list[str]:
    """Return duplicate ids in an entity's YAML mapping, in source order.

    In-memory mappings cannot contain duplicate keys, so they return an empty
    list.  Path input is inspected at the YAML node level before construction,
    which preserves duplicate-key evidence that ``safe_load`` would lose.
    """

    schema = _yaml_schema(entity)
    if isinstance(config_or_path, Mapping):
        _validate_config_tree(config_or_path)
        return []

    path = _coerce_path(config_or_path)
    text, _ = _read_text(path)
    _scan_yaml_budget(text)
    try:
        root = yaml.compose(text, Loader=yaml.SafeLoader)
    except yaml.YAMLError as error:
        _yaml_parse_error(error, phase="compose")
    except (MemoryError, RecursionError, ValueError) as error:
        _source_error(
            "YAML duplicate scan could not compose the source safely",
            "compose_error",
            error_type=type(error).__name__,
            phase="compose",
        )
    if root is None:
        return []
    _validate_composed_tree(root)
    if not isinstance(root, MappingNode):
        _source_error(
            "YAML project config must be a mapping",
            "root_not_mapping",
            value_type=_node_kind(root),
        )

    duplicates: list[str] = []
    reported: set[str] = set()
    for key_node, value_node in root.value:
        if not (
            isinstance(key_node, ScalarNode)
            and key_node.value == schema.storage_name
            and isinstance(value_node, MappingNode)
        ):
            continue
        seen: set[str] = set()
        for entity_key, _ in value_node.value:
            if not isinstance(entity_key, ScalarNode):
                continue
            entity_key_value = entity_key.value
            if entity_key_value in seen and entity_key_value not in reported:
                duplicates.append(entity_key_value)
                reported.add(entity_key_value)
            seen.add(entity_key_value)
    return duplicates


def _scan_yaml_budget(text: str) -> None:
    starts = (
        BlockMappingStartToken,
        BlockSequenceStartToken,
        FlowMappingStartToken,
        FlowSequenceStartToken,
    )
    ends = (BlockEndToken, FlowMappingEndToken, FlowSequenceEndToken)
    depth = 0
    token_count = 0
    alias_count = 0
    try:
        for token in yaml.scan(text, Loader=yaml.SafeLoader):
            token_count += 1
            if token_count > _MAX_YAML_TOKENS:
                _source_error(
                    "YAML duplicate scan exceeds the token budget",
                    "token_budget_exceeded",
                    actual=token_count,
                    limit=_MAX_YAML_TOKENS,
                    phase="scan",
                )
            if isinstance(token, starts):
                depth += 1
                if depth > _MAX_NESTING_DEPTH:
                    _source_error(
                        "YAML duplicate scan exceeds the nesting limit",
                        "nesting_depth_exceeded",
                        actual=depth,
                        limit=_MAX_NESTING_DEPTH,
                        phase="scan",
                    )
            elif isinstance(token, ends):
                depth = max(0, depth - 1)
            if isinstance(token, AliasToken):
                alias_count += 1
                if alias_count > _MAX_YAML_ALIASES:
                    _source_error(
                        "YAML duplicate scan exceeds the alias budget",
                        "alias_budget_exceeded",
                        actual=alias_count,
                        limit=_MAX_YAML_ALIASES,
                        phase="scan",
                    )
    except AuthoringError:
        raise
    except yaml.YAMLError as error:
        _yaml_parse_error(error, phase="scan")
    except (MemoryError, RecursionError, ValueError) as error:
        _source_error(
            "YAML duplicate scan could not tokenize the source safely",
            "scan_error",
            error_type=type(error).__name__,
            phase="scan",
        )


def _validate_composed_tree(root: yaml.Node) -> None:
    active: dict[int, str] = {}
    unique_containers: set[int] = set()
    visits = 0
    stack: list[tuple[bool, yaml.Node, str, int]] = [(False, root, "$", 0)]
    while stack:
        exiting, node, path, depth = stack.pop()
        marker = id(node)
        if exiting:
            active.pop(marker, None)
            continue

        visits += 1
        if visits > _MAX_VISITS:
            _source_error(
                "YAML duplicate scan exceeds the node visit budget",
                "traversal_budget_exceeded",
                actual=visits,
                limit=_MAX_VISITS,
                path=path,
                phase="compose",
            )
        if isinstance(node, ScalarNode):
            continue
        if depth > _MAX_NESTING_DEPTH:
            _source_error(
                "YAML duplicate scan exceeds the composed nesting limit",
                "nesting_depth_exceeded",
                actual=depth,
                limit=_MAX_NESTING_DEPTH,
                path=path,
                phase="compose",
            )
        cycle_to = active.get(marker)
        if cycle_to is not None:
            _source_error(
                "YAML aliases may not form cyclic structures",
                "cyclic_structure",
                cycle_to=cycle_to,
                path=path,
                phase="compose",
            )
        if marker not in unique_containers:
            unique_containers.add(marker)
            if len(unique_containers) > _MAX_CONTAINERS:
                _source_error(
                    "YAML duplicate scan contains too many containers",
                    "container_budget_exceeded",
                    actual=len(unique_containers),
                    limit=_MAX_CONTAINERS,
                    path=path,
                    phase="compose",
                )

        active[marker] = path
        stack.append((True, node, path, depth))
        if isinstance(node, MappingNode):
            children = [child for pair in node.value for child in pair]
        elif isinstance(node, SequenceNode):
            children = list(node.value)
        else:
            _source_error(
                "YAML duplicate scan found an unsupported node",
                "unsupported_node",
                node_type=type(node).__name__,
                path=path,
                phase="compose",
            )
        for index in range(len(children) - 1, -1, -1):
            stack.append((False, children[index], f"{path}[{index}]", depth + 1))


def upsert_yaml_entity(candidate_config: Path, change: ModelChange) -> bool:
    """Persist one complete YAML-backed entity candidate atomically.

    ``candidate_config`` is the staged project config, never the live source
    selected implicitly.  ``change.fields`` must be the complete result of the
    existing merge-patch contract.  The function returns ``True`` only when
    the canonical UTF-8 bytes differ and are replaced; a canonical no-op
    returns ``False``.
    """

    path = _coerce_path(candidate_config)
    schema = _yaml_schema(change.entity)
    text, original_bytes = _read_text(path)
    config = _parse_config(text)
    entities = _entity_mapping(config, schema, create=True)

    fields = _plain_tree(change.fields)
    normalized = _validate_entity(
        config,
        change.entity,
        change.id,
        fields,
        replacement=(schema.storage_name, change.id, fields),
    )
    entities[change.id] = normalized

    serialized = yaml.dump(
        config,
        Dumper=_CanonicalConfigDumper,
        allow_unicode=True,
        sort_keys=False,
    ).rstrip("\r\n") + "\n"
    candidate_bytes = serialized.encode("utf-8")
    if candidate_bytes == original_bytes:
        return False

    _replace_atomically(path, candidate_bytes, change)
    return True


def _yaml_schema(entity: str) -> EntitySchema:
    schema = get_entity_schema(entity)
    if schema.storage_kind != "yaml":
        raise AuthoringError(
            "invalid_change",
            f"Entity {entity!r} is not stored in YAML",
            {
                "entity": entity,
                "reason": "wrong_storage_kind",
                "storage_kind": schema.storage_kind,
            },
        )
    return schema


def _load_config(
    config_or_path: Mapping[str, Any] | str | os.PathLike[str],
) -> dict[str, Any]:
    if isinstance(config_or_path, Mapping):
        _validate_config_tree(config_or_path)
        if type(config_or_path) is not dict:
            config_or_path = dict(config_or_path)
        return _plain_tree(config_or_path)
    path = _coerce_path(config_or_path)
    text, _ = _read_text(path)
    return _parse_config(text)


def _coerce_path(value: str | os.PathLike[str]) -> Path:
    if not isinstance(value, (str, os.PathLike)):
        raise TypeError("YAML config must be a mapping or path-like value")
    return Path(value)


def _read_text(path: Path) -> tuple[str, bytes]:
    try:
        raw = path.read_bytes()
    except (OSError, MemoryError, ValueError) as error:
        raise AuthoringError(
            "yaml_read_failed",
            "YAML project config could not be read",
            {
                "error_type": type(error).__name__,
                "path": str(path),
                "reason": "read_error",
            },
        ) from None
    if len(raw) > _MAX_SOURCE_BYTES:
        _source_error(
            "YAML project config exceeds the authoring size limit",
            "source_too_large",
            actual_bytes=len(raw),
            limit_bytes=_MAX_SOURCE_BYTES,
            path=str(path),
        )
    try:
        return raw.decode("utf-8"), raw
    except UnicodeDecodeError as error:
        _source_error(
            "YAML project config must be UTF-8",
            "invalid_encoding",
            byte_offset=error.start,
            path=str(path),
        )


def _parse_config(text: str) -> dict[str, Any]:
    try:
        loaded = yaml.load(text, Loader=_StrictConfigLoader)
    except _DuplicateKey as error:
        _source_error(
            "YAML project config contains a duplicate mapping key",
            "duplicate_key",
            column=error.column,
            key=_diagnostic_scalar(error.key),
            line=error.line,
        )
    except _UnsupportedFloat as error:
        _source_error(
            "YAML authoring sources require exact decimals as quoted strings",
            "unsupported_float",
            column=error.column,
            line=error.line,
            value=error.value,
        )
    except _UnsupportedYamlFeature as error:
        _source_error(
            "YAML project config uses an unsupported YAML feature",
            "unsupported_yaml_feature",
            column=error.column,
            feature=error.feature,
            line=error.line,
        )
    except ConstructorError as error:
        reason = (
            "unsupported_tag"
            if "could not determine a constructor for the tag" in str(error)
            else "constructor_error"
        )
        details: dict[str, Any] = {"error_type": type(error).__name__, "reason": reason}
        if error.problem_mark is not None:
            details.update(
                {
                    "column": error.problem_mark.column + 1,
                    "line": error.problem_mark.line + 1,
                }
            )
        if error.problem:
            details["problem"] = error.problem
        raise AuthoringError(
            "invalid_yaml_source",
            "YAML project config could not be constructed safely",
            details,
        ) from None
    except yaml.YAMLError as error:
        _yaml_parse_error(error)
    except (MemoryError, RecursionError, ValueError) as error:
        _source_error(
            "YAML project config could not be parsed within safety limits",
            "parse_error",
            error_type=type(error).__name__,
        )

    if loaded is None:
        loaded = {}
    if type(loaded) is not dict:
        _source_error(
            "YAML project config must be a mapping",
            "root_not_mapping",
            value_type=type(loaded).__name__,
        )
    _validate_config_tree(loaded)
    return loaded


def _yaml_parse_error(
    error: yaml.YAMLError,
    *,
    phase: str | None = None,
) -> NoReturn:
    details: dict[str, Any] = {
        "error_type": type(error).__name__,
        "reason": "parse_error",
    }
    mark = getattr(error, "problem_mark", None)
    if mark is not None:
        details.update({"column": mark.column + 1, "line": mark.line + 1})
    problem = getattr(error, "problem", None)
    if isinstance(problem, str):
        details["problem"] = problem
    if phase is not None:
        details["phase"] = phase
    raise AuthoringError(
        "invalid_yaml_source",
        "YAML project config is not valid YAML",
        details,
    ) from None


def _validate_config_tree(value: Any) -> None:
    active: dict[int, str] = {}
    seen: set[int] = set()
    visits = 0
    stack: list[tuple[bool, Any, str, int]] = [(False, value, "$", 0)]
    while stack:
        exiting, node, path, depth = stack.pop()
        is_mapping = isinstance(node, Mapping)
        is_list = type(node) is list
        marker = id(node)
        if exiting:
            active.pop(marker, None)
            continue

        visits += 1
        if visits > _MAX_VISITS:
            _source_error(
                "YAML project config exceeds the traversal budget",
                "traversal_budget_exceeded",
                limit=_MAX_VISITS,
                path=path,
            )
        if not is_mapping and not is_list:
            if node is None or type(node) in {bool, int, str}:
                continue
            _source_error(
                "YAML project config contains an unsupported value",
                "unsupported_value",
                path=path,
                value_type=type(node).__name__,
            )
        if depth > _MAX_NESTING_DEPTH:
            _source_error(
                "YAML project config exceeds the nesting limit",
                "nesting_depth_exceeded",
                limit=_MAX_NESTING_DEPTH,
                path=path,
            )
        cycle_to = active.get(marker)
        if cycle_to is not None:
            _source_error(
                "YAML aliases may not form cyclic structures",
                "cyclic_structure",
                cycle_to=cycle_to,
                path=path,
            )
        if marker not in seen:
            seen.add(marker)
            if len(seen) > _MAX_CONTAINERS:
                _source_error(
                    "YAML project config contains too many containers",
                    "container_budget_exceeded",
                    limit=_MAX_CONTAINERS,
                    path=path,
                )

        active[marker] = path
        stack.append((True, node, path, depth))
        if is_mapping:
            items = list(node.items())
            for key, child in reversed(items):
                if not isinstance(key, str):
                    _source_error(
                        "YAML project config requires string mapping keys",
                        "non_string_key",
                        key=_diagnostic_scalar(key),
                        path=path,
                    )
                stack.append((False, child, f"{path}.{key}", depth + 1))
        else:
            for index in range(len(node) - 1, -1, -1):
                stack.append((False, node[index], f"{path}[{index}]", depth + 1))


def _entity_mapping(
    config: dict[str, Any],
    schema: EntitySchema,
    *,
    create: bool = False,
) -> dict[str, Any]:
    if schema.storage_name not in config:
        if create:
            config[schema.storage_name] = {}
        else:
            return {}
    value = config[schema.storage_name]
    if type(value) is not dict:
        _source_error(
            f"YAML entity mapping {schema.storage_name!r} must be a mapping",
            "entity_mapping_not_mapping",
            entity=schema.entity,
            mapping=schema.storage_name,
            value_type=type(value).__name__,
        )
    return value


def _validate_entity(
    config: dict[str, Any],
    entity: str,
    entity_id: str,
    fields: dict[str, Any],
    *,
    replacement: tuple[str, str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    selected = config
    if replacement is not None:
        storage, replacement_id, replacement_fields = replacement
        selected = _plain_tree(config)
        replacement_mapping = selected.get(storage)
        if replacement_mapping is None:
            replacement_mapping = {}
            selected[storage] = replacement_mapping
        if type(replacement_mapping) is dict:
            replacement_mapping[replacement_id] = _plain_tree(replacement_fields)

    rng_tables = selected.get("rng_tables", {})
    context = ValidationContext(
        rng_tables=rng_tables if type(rng_tables) is dict else {}
    )
    normalized = validate_entity_fields(
        entity,
        entity_id,
        fields,
        context=context,
    )
    _validate_references(selected, entity, entity_id, normalized)
    return normalized


def _validate_references(
    config: dict[str, Any],
    entity: str,
    entity_id: str,
    fields: dict[str, Any],
) -> None:
    if entity == "generator_type":
        for field in ("cost_formula", "production_formula"):
            _require_reference(config, entity, entity_id, field, fields[field], "formulas")
    elif entity == "player_profile":
        _require_reference(
            config,
            entity,
            entity_id,
            "behavior_policy",
            fields["behavior_policy"],
            "behavior_policies",
        )
        _require_reference(
            config,
            entity,
            entity_id,
            "session_pattern",
            fields["session_pattern"],
            "session_patterns",
        )
        for source_type in fields["source_efficiency"]:
            _require_reference(
                config,
                entity,
                entity_id,
                "source_efficiency",
                source_type,
                "source_types",
            )
    elif entity == "scenario":
        for profile in fields["profiles"]:
            _require_reference(
                config,
                entity,
                entity_id,
                "profiles",
                profile,
                "player_profiles",
            )
    elif entity == "rng_scenario":
        _require_reference(
            config,
            entity,
            entity_id,
            "table",
            fields["table"],
            "rng_tables",
        )
        for profile in fields["profiles"]:
            _require_reference(
                config,
                entity,
                entity_id,
                "profiles",
                profile,
                "player_profiles",
            )
    elif entity == "regression_gate":
        _require_reference(
            config,
            entity,
            entity_id,
            "id",
            entity_id,
            "scenarios",
        )


def _require_reference(
    config: dict[str, Any],
    entity: str,
    entity_id: str,
    field: str,
    value: str,
    target_mapping: str,
) -> None:
    targets = config.get(target_mapping, {})
    if type(targets) is dict and value in targets:
        return
    allowed = tuple(targets) if type(targets) is dict else ()
    raise AuthoringError(
        "invalid_change",
        f"{entity}:{entity_id} references unknown {target_mapping} id {value!r}",
        {
            "allowed": allowed,
            "entity": entity,
            "field": field,
            "id": entity_id,
            "reason": "unknown_reference",
            "reference_mapping": target_mapping,
            "value": value,
        },
    )


def _replace_atomically(path: Path, content: bytes, change: ModelChange) -> None:
    temporary: Path | None = None
    phase = "temp_write"
    try:
        source_mode = stat.S_IMODE(path.stat().st_mode)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
        )
        temporary = Path(temporary_name)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, source_mode)

        phase = "reload"
        reloaded = _load_config(temporary)
        reloaded_fields = _entity_mapping(reloaded, _yaml_schema(change.entity)).get(change.id)
        if type(reloaded_fields) is not dict:
            _source_error(
                "Reloaded YAML candidate is missing the upserted entity",
                "reload_missing_entity",
                entity=change.entity,
                id=change.id,
            )
        _validate_entity(reloaded, change.entity, change.id, reloaded_fields)

        phase = "replace"
        os.replace(temporary, path)
        temporary = None
    except AuthoringError:
        raise
    except (OSError, MemoryError, ValueError) as error:
        if phase == "replace" and _path_has_exact_bytes(path, content):
            return
        reason = {
            "temp_write": "temp_write_error",
            "reload": "reload_error",
            "replace": "replace_error",
        }[phase]
        raise AuthoringError(
            "yaml_write_failed",
            "YAML candidate could not be replaced atomically",
            {
                "error_type": type(error).__name__,
                "path": str(path),
                "reason": reason,
            },
        ) from None
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def _path_has_exact_bytes(path: Path, expected: bytes) -> bool:
    """Fingerprint the target after an ambiguous replace-side exception."""

    try:
        if path.stat().st_size != len(expected):
            return False
        return path.read_bytes() == expected
    except (OSError, MemoryError, ValueError):
        return False


def _plain_tree(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain_tree(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_tree(item) for item in value]
    return deepcopy(value)


def _source_error(message: str, reason: str, **details: Any) -> NoReturn:
    raise AuthoringError(
        "invalid_yaml_source",
        message,
        {"reason": reason, **details},
    )


def _diagnostic_scalar(value: Any) -> str | int | bool | None:
    if value is None or type(value) in {str, int, bool}:
        return value
    return f"<{type(value).__name__}>"


def _node_kind(node: yaml.Node) -> str:
    return type(node).__name__.removesuffix("Node").lower()


__all__ = [
    "find_yaml_duplicates",
    "read_yaml_entity",
    "upsert_yaml_entity",
]
