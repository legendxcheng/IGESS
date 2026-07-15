"""Lossless parsing and merge-patch handling for incremental model changes."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import json
import re
from types import MappingProxyType
from typing import Any, Mapping, NoReturn

import yaml
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode

from .entity_schema import (
    ENTITY_SCHEMAS,
    EntitySchema,
    get_entity_schema,
    validate_entity_fields,
)
from .response import AuthoringError


_REQUIRED_ENVELOPE_KEYS = ("version", "operation", "entity", "id", "fields")
_OPTIONAL_ENVELOPE_KEYS = ("if_model_digest",)
_ENVELOPE_KEYS = _REQUIRED_ENVELOPE_KEYS + _OPTIONAL_ENVELOPE_KEYS
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_PATH_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
_MAX_DIAGNOSTIC_PATH = 512
_MAX_SOURCE_BYTES = 1_048_576
_MAX_NESTING_DEPTH = 64
_MAX_UNIQUE_CONTAINERS = 4_096
_MAX_TRAVERSAL_VISITS = 16_384

# PyYAML 6 does not recognize unquoted ``1e3`` as a float.  The protocol does,
# because accepting it as a string would make quoting change numeric semantics.
_YAML_DECIMAL_OR_EXPONENT_RE = re.compile(
    r"^(?:"
    r"[-+]?(?:[0-9][0-9_]*)?\.[0-9_]+(?:[eE][-+]?[0-9]+)?"
    r"|[-+]?[0-9][0-9_]*(?:[eE][-+]?[0-9]+)"
    r"|[-+]?\.(?:inf|Inf|INF|nan|NaN|NAN)"
    r")$"
)


class _RejectedNumber(ValueError):
    pass


class _DuplicateKey(ValueError):
    pass


class _UnsupportedYamlFeature(ValueError):
    pass


class _ExactChangeLoader(yaml.SafeLoader):
    """SafeLoader variant that rejects floats and duplicate mapping keys."""

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
            raise _UnsupportedYamlFeature("merge_key")
        self.flatten_mapping(node)
        mapping: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                duplicate = key in mapping
            except TypeError as exc:
                raise ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "found unhashable key",
                    key_node.start_mark,
                ) from exc
            if duplicate:
                raise _DuplicateKey(str(key))
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


# Do not mutate SafeLoader's process-global resolver table.
_ExactChangeLoader.yaml_implicit_resolvers = {
    key: list(resolvers)
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_ExactChangeLoader.add_implicit_resolver(
    "tag:yaml.org,2002:float",
    _YAML_DECIMAL_OR_EXPONENT_RE,
    list("-+0123456789."),
)


def _reject_yaml_float(loader: _ExactChangeLoader, node: yaml.Node) -> NoReturn:
    del loader, node
    raise _RejectedNumber("floating YAML token")


_ExactChangeLoader.add_constructor("tag:yaml.org,2002:float", _reject_yaml_float)


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _deep_freeze(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(item) for item in value)
    return value


def _deep_thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _deep_thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_deep_thaw(item) for item in value]
    return value


def _validate_direct_header(
    version: Any,
    operation: Any,
    entity: Any,
    entity_id: Any,
    digest: Any,
) -> EntitySchema:
    if type(version) is not int or version != 1:
        _invalid_field(
            entity=entity,
            entity_id=entity_id,
            field="version",
            value=version,
            allowed=(1,),
            message="Change version must be the native integer 1",
        )
    if operation != "upsert":
        _invalid_field(
            entity=entity,
            entity_id=entity_id,
            field="operation",
            value=operation,
            allowed=("upsert",),
            message="Only the upsert change operation is supported",
        )
    if not isinstance(entity, str):
        _invalid_field(
            entity=entity,
            entity_id=entity_id,
            field="entity",
            value=entity,
            allowed=tuple(ENTITY_SCHEMAS),
            message="Change entity must be a supported entity name",
        )
    schema = get_entity_schema(entity)
    validate_entity_fields(entity, entity_id, {}, require_complete=False)
    if digest is not None and (
        not isinstance(digest, str) or _DIGEST_RE.fullmatch(digest) is None
    ):
        _invalid_field(
            entity=entity,
            entity_id=entity_id,
            field="if_model_digest",
            value=digest,
            allowed=("null", "sha256:<64 lowercase hex>"),
            message="if_model_digest must be null or a lowercase SHA-256 digest",
        )
    return schema


def _canonical_json_tree(value: Any, root_path: str) -> Any:
    memo: dict[int, Any] = {}

    def convert(node: Any, path: str) -> Any:
        if isinstance(node, Mapping):
            marker = id(node)
            if marker in memo:
                return memo[marker]
            result: dict[str, Any] = {}
            memo[marker] = result
            for key, item in node.items():
                if not isinstance(key, str):
                    _unsupported_value(
                        path,
                        key,
                        "Change mappings require string keys",
                    )
                result[key] = convert(item, _mapping_path(path, key))
            return result
        if isinstance(node, (list, tuple)):
            marker = id(node)
            if marker in memo:
                return memo[marker]
            result_list: list[Any] = []
            memo[marker] = result_list
            for index, item in enumerate(node):
                result_list.append(
                    convert(item, _bounded_path(f"{path}[{index}]"))
                )
            return result_list
        if node is None or type(node) in {bool, str}:
            return node
        if type(node) is int:
            try:
                json.dumps(node, allow_nan=False)
            except (TypeError, ValueError, OverflowError):
                _unsupported_value(path, node, "Integer is too large for JSON")
            return node
        _unsupported_value(
            path,
            node,
            "Change values must use strict JSON scalar types",
        )

    return convert(value, root_path)


def _unsupported_value(path: str, value: Any, message: str) -> NoReturn:
    raise AuthoringError(
        "invalid_change",
        message,
        {
            "reason": "unsupported_value",
            "path": _bounded_path(path),
            "value": _json_safe_diagnostic(value),
            "value_type": type(value).__name__,
        },
    )


def _verify_strict_json_payload(
    version: int,
    operation: str,
    entity: str,
    entity_id: str,
    fields: Mapping[str, Any],
    digest: str | None,
) -> None:
    payload = {
        "version": version,
        "operation": operation,
        "entity": entity,
        "id": entity_id,
        "fields": _deep_thaw(fields),
    }
    if digest is not None:
        payload["if_model_digest"] = digest
    try:
        json.dumps(payload, allow_nan=False)
    except (TypeError, ValueError, OverflowError, RecursionError):
        _unsupported_value(
            "$.fields",
            fields,
            "ModelChange payload is not strict JSON",
        )


@dataclass(frozen=True, slots=True)
class ModelChange:
    """A validated complete entity candidate produced from one upsert patch."""

    version: int
    operation: str
    entity: str
    id: str
    fields: Mapping[str, Any] = field(default_factory=dict)
    if_model_digest: str | None = None

    def __post_init__(self) -> None:
        _ensure_acyclic_tree(self.fields, "$.fields")
        if not isinstance(self.fields, Mapping):
            _invalid_field(
                entity=self.entity,
                entity_id=self.id,
                field="fields",
                value=self.fields,
                allowed=("mapping",),
                message="ModelChange fields must be a mapping",
            )

        schema = _validate_direct_header(
            self.version,
            self.operation,
            self.entity,
            self.id,
            self.if_model_digest,
        )
        canonical = _canonical_json_tree(self.fields, "$.fields")
        normalized = validate_entity_fields(
            schema.entity,
            self.id,
            canonical,
        )
        frozen = _deep_freeze(normalized)
        object.__setattr__(self, "fields", frozen)
        _verify_strict_json_payload(
            self.version,
            self.operation,
            self.entity,
            self.id,
            frozen,
            self.if_model_digest,
        )

    def to_payload(self) -> dict[str, Any]:
        """Return a strict-JSON-serializable defensive audit payload."""

        payload = {
            "version": self.version,
            "operation": self.operation,
            "entity": self.entity,
            "id": self.id,
            "fields": _deep_thaw(self.fields),
        }
        if self.if_model_digest is not None:
            payload["if_model_digest"] = self.if_model_digest
        return payload


def parse_change_text(
    text: str,
    format_name: str,
    current: Mapping[str, Any] | None = None,
) -> ModelChange:
    """Parse, merge, validate, and normalize one YAML or JSON upsert document."""

    document = _parse_document(text, format_name)
    _ensure_acyclic_tree(document, "$")
    if type(document) is not dict:
        _parse_error(
            "Change document must be a mapping",
            reason="root_not_mapping",
            format_name=format_name,
        )

    for key in document:
        if key not in _ENVELOPE_KEYS:
            _invalid_field(
                entity=document.get("entity"),
                entity_id=document.get("id"),
                field=str(key),
                value=document[key],
                allowed=_ENVELOPE_KEYS,
                message=f"Unknown top-level change key: {key!r}",
            )
    for key in _REQUIRED_ENVELOPE_KEYS:
        if key not in document:
            _invalid_field(
                entity=document.get("entity"),
                entity_id=document.get("id"),
                field=key,
                value=None,
                allowed=("required top-level key",),
                message=f"Missing top-level change key: {key!r}",
            )

    version = document["version"]
    if type(version) is not int or version != 1:
        _invalid_field(
            entity=document.get("entity"),
            entity_id=document.get("id"),
            field="version",
            value=version,
            allowed=(1,),
            message="Change version must be the native integer 1",
        )

    operation = document["operation"]
    if operation != "upsert":
        _invalid_field(
            entity=document.get("entity"),
            entity_id=document.get("id"),
            field="operation",
            value=operation,
            allowed=("upsert",),
            message="Only the upsert change operation is supported",
        )

    entity = document["entity"]
    if not isinstance(entity, str):
        _invalid_field(
            entity=entity,
            entity_id=document.get("id"),
            field="entity",
            value=entity,
            allowed=tuple(ENTITY_SCHEMAS),
            message="Change entity must be a supported entity name",
        )
    schema = get_entity_schema(entity)
    entity_id = document["id"]
    # This validates the envelope id without imposing create-field requirements.
    validate_entity_fields(entity, entity_id, {}, require_complete=False)

    patch = document["fields"]
    if type(patch) is not dict:
        _invalid_field(
            entity=entity,
            entity_id=entity_id,
            field="fields",
            value=patch,
            allowed=("native mapping",),
            message="Change fields must be a native mapping",
        )

    _validate_patch_fields(entity, entity_id, patch, schema)

    digest = document.get("if_model_digest")
    if digest is not None and (
        not isinstance(digest, str) or _DIGEST_RE.fullmatch(digest) is None
    ):
        _invalid_field(
            entity=entity,
            entity_id=entity_id,
            field="if_model_digest",
            value=digest,
            allowed=("null", "sha256:<64 lowercase hex>"),
            message="if_model_digest must be null or a lowercase SHA-256 digest",
        )

    base = {} if current is None else current
    candidate = merge_fields(base, patch, schema)
    normalized = validate_entity_fields(entity, entity_id, candidate)
    return ModelChange(
        version=version,
        operation=operation,
        entity=entity,
        id=entity_id,
        fields=normalized,
        if_model_digest=digest,
    )


def merge_fields(
    current: Mapping[str, Any],
    patch: Mapping[str, Any],
    schema: EntitySchema,
) -> dict[str, Any]:
    """Apply JSON Merge Patch semantics to entity fields without mutation."""

    _ensure_acyclic_tree(current, "$.current")
    _ensure_acyclic_tree(patch, "$.fields")
    if not isinstance(current, Mapping):
        _invalid_field(
            entity=schema.entity,
            entity_id=None,
            field="current",
            value=current,
            allowed=("mapping",),
            message="Current entity fields must be a mapping",
        )
    if type(patch) is not dict:
        _invalid_field(
            entity=schema.entity,
            entity_id=None,
            field="fields",
            value=patch,
            allowed=("native mapping",),
            message="Change fields must be a native mapping",
        )

    known = set(schema.field_names)
    required = set(schema.required_fields)
    for name, value in patch.items():
        if name not in known:
            _invalid_field(
                entity=schema.entity,
                entity_id=None,
                field=str(name),
                value=value,
                allowed=schema.field_names,
                message=f"Unknown field {name!r} for {schema.entity}",
            )
        if value is None and name in required:
            _invalid_field(
                entity=schema.entity,
                entity_id=None,
                field=name,
                value=None,
                allowed=("required field",),
                message=f"Required field {name!r} cannot be removed",
            )

    return _merge_mapping(current, patch)


def _merge_mapping(current: Mapping[str, Any], patch: Mapping[str, Any]) -> dict[str, Any]:
    result = _deep_mutable(current)
    for key, value in patch.items():
        if value is None:
            result.pop(key, None)
        elif type(value) is dict:
            existing = result.get(key)
            nested_current = existing if isinstance(existing, Mapping) else {}
            result[key] = _merge_mapping(nested_current, value)
        else:
            result[key] = _deep_mutable(value)
    return result


def _deep_mutable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _deep_mutable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_deep_mutable(item) for item in value]
    return deepcopy(value)


def _validate_patch_fields(
    entity: str,
    entity_id: str,
    patch: dict[str, Any],
    schema: EntitySchema,
) -> None:
    """Validate independent patch values before applying deletion markers."""

    known = set(schema.field_names)
    required = set(schema.required_fields)
    for name, value in patch.items():
        if name not in known or (value is None and name in required):
            validate_entity_fields(
                entity,
                entity_id,
                {name: value},
                require_complete=False,
            )
        if value is None or _contains_null(value):
            continue
        validate_entity_fields(
            entity,
            entity_id,
            {name: value},
            require_complete=False,
        )


def _contains_null(value: Any) -> bool:
    if type(value) is dict:
        return any(item is None or _contains_null(item) for item in value.values())
    if type(value) is list:
        return any(_contains_null(item) for item in value)
    return False


def _ensure_acyclic_tree(value: Any, root_path: str) -> None:
    """Reject cycles and boundedly traverse aliases shared across branches."""

    active: dict[int, str] = {}
    seen_containers: set[int] = set()
    visits = 0
    stack: list[tuple[bool, Any, str, int]] = [
        (False, value, root_path, 0)
    ]
    while stack:
        exiting, node, path, depth = stack.pop()
        is_mapping = isinstance(node, Mapping)
        is_sequence = isinstance(node, (list, tuple))
        marker = id(node)
        if exiting:
            active.pop(marker, None)
            continue

        visits += 1
        if visits > _MAX_TRAVERSAL_VISITS:
            _budget_error(
                "traversal_visits",
                _MAX_TRAVERSAL_VISITS,
                visits,
                path,
            )
        if not is_mapping and not is_sequence:
            continue
        if depth > _MAX_NESTING_DEPTH:
            _budget_error(
                "nesting_depth",
                _MAX_NESTING_DEPTH,
                depth,
                path,
            )

        cycle_to = active.get(marker)
        if cycle_to is not None:
            raise AuthoringError(
                "invalid_change",
                "Cyclic mappings and lists are not allowed in changes",
                {
                    "reason": "cyclic_structure",
                    "path": path,
                    "cycle_to": cycle_to,
                },
            )

        if marker not in seen_containers:
            seen_containers.add(marker)
            if len(seen_containers) > _MAX_UNIQUE_CONTAINERS:
                _budget_error(
                    "unique_containers",
                    _MAX_UNIQUE_CONTAINERS,
                    len(seen_containers),
                    path,
                )

        active[marker] = path
        stack.append((True, node, path, depth))
        child_count = len(node)
        if visits + child_count > _MAX_TRAVERSAL_VISITS:
            _budget_error(
                "traversal_visits",
                _MAX_TRAVERSAL_VISITS,
                visits + child_count,
                path,
            )
        if is_mapping:
            children = [
                (item, _mapping_path(path, key))
                for key, item in node.items()
            ]
        else:
            children = [
                (item, _bounded_path(f"{path}[{index}]"))
                for index, item in enumerate(node)
            ]
        for child, child_path in reversed(children):
            stack.append((False, child, child_path, depth + 1))


def _mapping_path(parent: str, key: Any) -> str:
    if isinstance(key, str) and _PATH_IDENTIFIER_RE.fullmatch(key):
        segment = f".{key}"
    else:
        safe_key = _json_safe_diagnostic(key)
        encoded = json.dumps(safe_key, ensure_ascii=False, separators=(",", ":"))
        if len(encoded) > 64:
            encoded = encoded[:61] + "..."
        segment = f"[{encoded}]"
    return _bounded_path(parent + segment)


def _bounded_path(path: str) -> str:
    if len(path) <= _MAX_DIAGNOSTIC_PATH:
        return path
    return path[: _MAX_DIAGNOSTIC_PATH - 3] + "..."


def _budget_error(
    budget: str,
    limit: int,
    actual: int,
    path: str,
) -> NoReturn:
    raise AuthoringError(
        "invalid_change",
        "Change document exceeds a structural safety budget",
        {
            "reason": "budget_exceeded",
            "budget": budget,
            "limit": limit,
            "actual": actual,
            "path": _bounded_path(path),
        },
    )


def _parse_document(text: str, format_name: str) -> Any:
    if format_name not in {"json", "yaml"}:
        _parse_error(
            "Unsupported change document format",
            reason="unsupported_format",
            format_name=format_name,
        )
    if not isinstance(text, str):
        _parse_error(
            "Change document text must be a string",
            reason="invalid_syntax",
            format_name=format_name,
        )
    try:
        source_bytes = len(text.encode("utf-8"))
    except UnicodeError:
        _parse_error(
            "Change document has invalid Unicode text",
            reason="invalid_syntax",
            format_name=format_name,
        )
    if source_bytes > _MAX_SOURCE_BYTES:
        _budget_error(
            "source_bytes",
            _MAX_SOURCE_BYTES,
            source_bytes,
            "$",
        )
    try:
        if format_name == "json":
            return json.loads(
                text,
                parse_int=int,
                parse_float=_reject_json_number,
                parse_constant=_reject_json_number,
                object_pairs_hook=_unique_json_object,
            )
        return yaml.load(text, Loader=_ExactChangeLoader)
    except _RejectedNumber:
        _parse_error(
            "Floating-point numeric tokens are not allowed in changes",
            reason="floating_number",
            format_name=format_name,
        )
    except _DuplicateKey:
        _parse_error(
            "Duplicate mapping keys are not allowed in changes",
            reason="duplicate_key",
            format_name=format_name,
        )
    except _UnsupportedYamlFeature:
        raise AuthoringError(
            "invalid_change",
            "YAML merge keys are not supported in changes",
            {
                "format": format_name,
                "reason": "unsupported_yaml_feature",
                "feature": "merge_key",
            },
        )
    except RecursionError:
        _budget_error(
            "parser_depth",
            _MAX_NESTING_DEPTH,
            _MAX_NESTING_DEPTH + 1,
            "$",
        )
    except (json.JSONDecodeError, yaml.YAMLError, UnicodeError, TypeError, ValueError):
        _parse_error(
            "Change document has invalid syntax",
            reason="invalid_syntax",
            format_name=format_name,
        )


def _reject_json_number(token: str) -> NoReturn:
    del token
    raise _RejectedNumber("floating JSON token")


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey(key)
        result[key] = value
    return result


def _parse_error(message: str, *, reason: str, format_name: str) -> NoReturn:
    raise AuthoringError(
        "invalid_change",
        message,
        {"format": format_name, "reason": reason},
    )


def _invalid_field(
    *,
    entity: Any,
    entity_id: Any,
    field: str,
    value: Any,
    allowed: tuple[Any, ...],
    message: str,
) -> NoReturn:
    raise AuthoringError(
        "invalid_change",
        message,
        {
            "entity": _json_safe_diagnostic(entity),
            "id": _json_safe_diagnostic(entity_id),
            "field": _json_safe_diagnostic(field),
            "value": _json_safe_diagnostic(value),
            "allowed": [_json_safe_diagnostic(item) for item in allowed],
        },
    )


def _json_safe_diagnostic(value: Any, *, _depth: int = 0) -> Any:
    if value is None or type(value) in {bool, int, str}:
        return value
    if _depth >= 16:
        return f"<{type(value).__name__}:max-depth>"
    if isinstance(value, Mapping):
        return {
            key if isinstance(key, str) else str(_json_safe_diagnostic(key)): (
                _json_safe_diagnostic(item, _depth=_depth + 1)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [
            _json_safe_diagnostic(item, _depth=_depth + 1)
            for item in value
        ]
    return f"<{type(value).__name__}>"


__all__ = ["ModelChange", "merge_fields", "parse_change_text"]
