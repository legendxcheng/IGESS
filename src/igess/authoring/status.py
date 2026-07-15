"""Derived, read-only status for incrementally authored economy models."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
import os
from pathlib import Path
import re
import stat
from types import MappingProxyType
from typing import Any, BinaryIO, Literal, NoReturn

import yaml
from yaml.nodes import MappingNode, ScalarNode

from ..builder import ModelBuilder
from ..linter import ConfigLinter
from ..loader import ConfigLoader
from .entity_schema import ENTITY_SCHEMAS
from .exports import compute_export_digest, ephemeral_export
from .probe import (
    EligibilityFinding,
    run_ten_tick_probe,
    static_smoke_eligibility,
)
from .project import AuthoringProject
from .response import AuthoringError
from . import project as _project_module
from . import workbook_source as _workbook_source
from . import yaml_source as _yaml_source


StatusState = Literal["incomplete", "runnable", "ready", "failed"]
_ENTITY_NAMES = tuple(ENTITY_SCHEMAS)
_WORKBOOK_SCHEMAS = tuple(
    schema for schema in ENTITY_SCHEMAS.values() if schema.storage_kind == "workbook"
)
_YAML_SCHEMAS = tuple(
    schema for schema in ENTITY_SCHEMAS.values() if schema.storage_kind == "yaml"
)


@dataclass(frozen=True, slots=True)
class ModelStatus:
    """One immutable, JSON-safe snapshot of current authoring readiness.

    Available scenarios are defensively normalized to sorted, unique ids before
    their cross-field state invariants are validated.
    """

    model_digest: str
    structural_valid: bool
    smoke_eligible: bool
    state: StatusState
    entity_counts: Mapping[str, int] = field(default_factory=dict)
    missing_requirements: tuple[EligibilityFinding, ...] = ()
    warnings: tuple[EligibilityFinding, ...] = ()
    available_scenarios: tuple[str, ...] = ()
    latest_smoke_run_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.model_digest, str) or not self.model_digest:
            raise ValueError("model_digest must be a non-empty string")
        if type(self.structural_valid) is not bool:
            raise TypeError("structural_valid must be a bool")
        if type(self.smoke_eligible) is not bool:
            raise TypeError("smoke_eligible must be a bool")
        if self.state not in {"incomplete", "runnable", "ready", "failed"}:
            raise ValueError("state must be incomplete, runnable, ready, or failed")
        if self.state == "failed":
            if self.structural_valid or self.smoke_eligible:
                raise ValueError(
                    "failed status must be structurally invalid and smoke-ineligible"
                )
        elif not self.structural_valid:
            raise ValueError("non-failed status must be structurally valid")
        if self.smoke_eligible and not self.structural_valid:
            raise ValueError("smoke eligibility requires structural validity")
        if self.state in {"runnable", "ready"} and not self.smoke_eligible:
            raise ValueError("runnable and ready status must be smoke-eligible")
        if not isinstance(self.entity_counts, Mapping):
            raise TypeError("entity_counts must be a mapping")
        counts: dict[str, int] = {}
        for name, count in self.entity_counts.items():
            if not isinstance(name, str) or not name:
                raise TypeError("entity count names must be non-empty strings")
            if type(count) is not int or count < 0:
                raise TypeError("entity counts must be non-negative integers")
            counts[name] = count
        object.__setattr__(self, "entity_counts", MappingProxyType(counts))

        missing = tuple(self.missing_requirements)
        warnings = tuple(self.warnings)
        if any(not isinstance(issue, EligibilityFinding) for issue in (*missing, *warnings)):
            raise TypeError("requirements and warnings must contain EligibilityFinding values")
        object.__setattr__(self, "missing_requirements", missing)
        object.__setattr__(self, "warnings", warnings)

        scenario_values = tuple(self.available_scenarios)
        if any(not isinstance(value, str) or not value for value in scenario_values):
            raise TypeError("available_scenarios must contain non-empty strings")
        scenarios = tuple(sorted(set(scenario_values)))
        object.__setattr__(self, "available_scenarios", scenarios)
        if self.smoke_eligible and "smoke" not in scenarios:
            raise ValueError("smoke-eligible status requires the smoke scenario")
        has_non_smoke_scenario = any(value != "smoke" for value in scenarios)
        if self.state == "ready" and not has_non_smoke_scenario:
            raise ValueError("ready status requires a non-smoke scenario")
        if self.state == "runnable" and has_non_smoke_scenario:
            raise ValueError("runnable status cannot include a non-smoke scenario")
        if self.latest_smoke_run_id is not None and (
            not isinstance(self.latest_smoke_run_id, str)
            or not self.latest_smoke_run_id
        ):
            raise TypeError("latest_smoke_run_id must be a non-empty string or None")

    def to_payload(self) -> dict[str, Any]:
        """Return a defensive protocol payload in the specified key order."""

        return {
            "model_digest": self.model_digest,
            "structural_valid": self.structural_valid,
            "smoke_eligible": self.smoke_eligible,
            "state": self.state,
            "entity_counts": dict(self.entity_counts),
            "missing_requirements": [item.to_payload() for item in self.missing_requirements],
            "warnings": [item.to_payload() for item in self.warnings],
            "available_scenarios": list(self.available_scenarios),
            "latest_smoke_run_id": self.latest_smoke_run_id,
        }


def derive_status(
    project: AuthoringProject,
    latest_smoke: Callable[[], object | None],
) -> ModelStatus:
    """Derive readiness only from current authoritative sources.

    Ordinary failures are data in the returned status.  Process-control
    ``BaseException`` values deliberately remain programmer-visible.
    """

    counts = {name: 0 for name in _ENTITY_NAMES}
    requirements: list[EligibilityFinding] = []
    warnings: list[EligibilityFinding] = []
    scenarios: set[str] = set()
    model_digest = "unavailable"
    state: StatusState = "failed"
    smoke_eligible = False

    latest_run_id, latest_issue = _read_latest_smoke(latest_smoke)
    if latest_issue is not None:
        requirements.append(latest_issue)

    if not isinstance(project, AuthoringProject):
        requirements.append(
            EligibilityFinding(
                "status_project_invalid",
                "Model status requires a discovered AuthoringProject.",
            )
        )
        return _make_status(
            model_digest,
            counts,
            requirements,
            warnings,
            scenarios,
            latest_run_id,
            state="failed",
            smoke_eligible=False,
        )

    try:
        model_digest = project.model_digest()
    except Exception as error:
        requirements.append(_error_finding(error, "source_digest"))

    _inspect_yaml(project.config, counts, scenarios, requirements)
    _inspect_workbooks(project, counts, requirements)

    export_completed = False
    try:
        with ephemeral_export(project) as exported:
            model_digest = exported.source_digest
            try:
                committed_digest = compute_export_digest(project.exports)
            except Exception:
                committed_digest = None
            if committed_digest != exported.export_digest:
                warnings.append(
                    EligibilityFinding(
                        "exports_stale",
                        "Committed runtime exports are missing or stale; apply a change to synchronize them.",
                    )
                )

            if not requirements:
                try:
                    raw = ConfigLoader.load(
                        exported.candidate_config,
                        exported.export_root,
                    )
                except Exception as error:
                    requirements.append(_error_finding(error, "load"))
                else:
                    try:
                        ConfigLinter.validate(raw)
                    except Exception as error:
                        requirements.append(_error_finding(error, "lint"))
                    else:
                        try:
                            model = ModelBuilder.build(raw)
                        except Exception as error:
                            requirements.append(_error_finding(error, "build"))
                        else:
                            try:
                                eligibility = static_smoke_eligibility(raw, model)
                            except Exception as error:
                                requirements.append(_error_finding(error, "eligibility"))
                            else:
                                if not eligibility.eligible:
                                    requirements.extend(eligibility.findings)
                                    state = "incomplete"
                                else:
                                    smoke_eligible = True
                                    try:
                                        probe = run_ten_tick_probe(model)
                                        if probe.artifacts or probe.report_index is not None:
                                            raise AuthoringError(
                                                "smoke_artifact_unexpected",
                                                "Artifact-free status probe produced persistent artifacts.",
                                                {},
                                            )
                                    except Exception as error:
                                        requirements.append(_error_finding(error, "probe"))
                                    else:
                                        if probe.observable_change:
                                            state = (
                                                "ready"
                                                if any(item != "smoke" for item in scenarios)
                                                else "runnable"
                                            )
                                        else:
                                            state = "incomplete"
                                            requirements.extend(probe.findings)
        export_completed = True
    except Exception as error:
        state = "failed"
        smoke_eligible = False
        requirements.append(_error_finding(error, "export"))

    if state == "failed":
        smoke_eligible = False
    if not export_completed:
        warnings = [warning for warning in warnings if warning.code != "exports_stale"]

    return _make_status(
        model_digest,
        counts,
        requirements,
        warnings,
        scenarios,
        latest_run_id,
        state=state,
        smoke_eligible=smoke_eligible,
    )


def _read_latest_smoke(
    callback: Callable[[], object | None],
) -> tuple[str | None, EligibilityFinding | None]:
    if not callable(callback):
        return None, EligibilityFinding(
            "latest_smoke_invalid",
            "Latest smoke lookup must be callable.",
        )
    try:
        record = callback()
    except Exception:
        return None, EligibilityFinding(
            "latest_smoke_failed",
            "Latest smoke run could not be read.",
        )
    if record is None:
        return None, None
    try:
        if isinstance(record, Mapping):
            run_id = record.get("run_id")
        else:
            run_id = getattr(record, "run_id")
    except Exception:
        run_id = None
    if not isinstance(run_id, str) or not run_id:
        return None, EligibilityFinding(
            "latest_smoke_invalid",
            "Latest smoke lookup returned a record without a valid run_id.",
        )
    return run_id, None


def _inspect_yaml(
    path: Path,
    counts: dict[str, int],
    scenarios: set[str],
    requirements: list[EligibilityFinding],
) -> None:
    try:
        node_counts, node_scenarios, duplicates = _yaml_node_inventory(path)
    except Exception as error:
        fallback_counts, fallback_scenarios = _fallback_yaml_inventory(path)
        counts.update(fallback_counts)
        scenarios.update(fallback_scenarios)
        requirements.append(_error_finding(error, "yaml_inventory"))
    else:
        counts.update(node_counts)
        scenarios.update(node_scenarios)
        requirements.extend(duplicates)

    try:
        config = _yaml_source._load_config(path)
    except Exception as error:
        requirements.append(_error_finding(error, "yaml"))
        return

    for schema in _YAML_SCHEMAS:
        try:
            entities = _yaml_source._entity_mapping(config, schema)
        except Exception as error:
            requirements.append(_error_finding(error, "yaml"))
            continue
        counts[schema.entity] = len(entities)
        if schema.entity == "scenario":
            scenarios.update(key for key in entities if isinstance(key, str) and key)
        for entity_id, fields in entities.items():
            if type(fields) is not dict:
                requirements.append(
                    EligibilityFinding(
                        "invalid_yaml_source",
                        f"YAML {schema.storage_name}:{entity_id} must be a mapping.",
                        schema.entity,
                        entity_id if isinstance(entity_id, str) else None,
                    )
                )
                continue
            try:
                _yaml_source._validate_entity(
                    config,
                    schema.entity,
                    entity_id,
                    fields,
                )
            except Exception as error:
                requirements.append(_error_finding(error, "yaml"))


def _yaml_node_inventory(
    path: Path,
) -> tuple[dict[str, int], set[str], list[EligibilityFinding]]:
    text, _ = _yaml_source._read_text(path)
    _yaml_source._scan_yaml_budget(text)
    try:
        root = yaml.compose(text, Loader=yaml.SafeLoader)
    except yaml.YAMLError as error:
        _yaml_source._yaml_parse_error(error, phase="compose")
    if root is None:
        return {}, set(), []
    _yaml_source._validate_composed_tree(root)
    if not isinstance(root, MappingNode):
        return {}, set(), []

    schemas_by_storage = {schema.storage_name: schema for schema in _YAML_SCHEMAS}
    counts: dict[str, int] = {}
    scenarios: set[str] = set()
    duplicates: list[EligibilityFinding] = []
    for storage_node, value_node in root.value:
        if not isinstance(storage_node, ScalarNode):
            continue
        schema = schemas_by_storage.get(storage_node.value)
        if schema is None or not isinstance(value_node, MappingNode):
            continue
        seen: set[str] = set()
        count = 0
        for id_node, _ in value_node.value:
            if not isinstance(id_node, ScalarNode):
                continue
            entity_id = id_node.value
            count += 1
            if schema.entity == "scenario" and entity_id:
                scenarios.add(entity_id)
            if entity_id in seen:
                duplicates.append(
                    EligibilityFinding(
                        "duplicate_entity_id",
                        f"Duplicate {schema.entity} id '{entity_id}' in YAML source.",
                        schema.entity,
                        entity_id,
                    )
                )
            seen.add(entity_id)
        counts[schema.entity] = counts.get(schema.entity, 0) + count
    return counts, scenarios, duplicates


def _inspect_workbooks(
    project: AuthoringProject,
    counts: dict[str, int],
    requirements: list[EligibilityFinding],
) -> None:
    registered = _registered_workbook_paths(project, requirements)
    for schema in _WORKBOOK_SCHEMAS:
        registered_path = registered.get(schema.storage_name)
        path = registered_path or project.datas / schema.storage_name
        try:
            snapshot = _read_bounded_workbook_snapshot(
                path,
                project.datas,
                entity=schema.entity,
                direct=registered_path is None,
            )
        except Exception as error:
            counts[schema.entity] = 0
            requirements.append(_error_finding(error, "workbook"))
            continue
        try:
            with _workbook_source._open_snapshot(
                snapshot,
                path,
                read_only=True,
            ) as workbook:
                inspected = _workbook_source._inspect_open(workbook, path, schema)
        except Exception as error:
            counts[schema.entity] = _partial_workbook_count(snapshot, path)
            requirements.append(_error_finding(error, "workbook"))
            continue
        counts[schema.entity] = len(inspected.records)
        requirements.extend(
            EligibilityFinding(
                "duplicate_entity_id",
                f"Duplicate {schema.entity} id '{entity_id}' in workbook source.",
                schema.entity,
                entity_id,
            )
            for entity_id in inspected.duplicate_ids
        )


def _registered_workbook_paths(
    project: AuthoringProject,
    requirements: list[EligibilityFinding],
) -> dict[str, Path]:
    registry = project.datas / "__tables__.xlsx"
    result: dict[str, Path] = {}
    try:
        resolved_registry = _project_module._resolve_registry(registry, project.datas)
        with resolved_registry.open("rb") as handle:
            registrations = _project_module._read_registration_paths(
                handle,
                resolved_registry,
            )
        snapshots = _project_module._validate_registration_paths(
            project.datas,
            resolved_registry,
            registrations,
        )
        for snapshot in snapshots:
            candidate = snapshot.path
            name = candidate.name
            if name in {schema.storage_name for schema in _WORKBOOK_SCHEMAS}:
                result[name] = candidate
        expected = {schema.storage_name for schema in _WORKBOOK_SCHEMAS}
        if set(result) != expected:
            requirements.append(
                EligibilityFinding(
                    "source_registry_incomplete",
                    "Source registry must contain each canonical authoring workbook exactly once.",
                )
            )
    except Exception as error:
        requirements.append(_error_finding(error, "registry"))
    return result


def _open_workbook_binary(path: Path) -> BinaryIO:
    """Open one workbook without following a final symlink where supported."""

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        return os.fdopen(descriptor, "rb")
    except BaseException:
        os.close(descriptor)
        raise


def _read_bounded_workbook_snapshot(
    path: Path,
    datas: Path,
    *,
    entity: str,
    direct: bool,
) -> Any:
    """Read one boundary-checked workbook once into an immutable snapshot."""

    initial = _validate_workbook_path(
        path,
        datas,
        entity=entity,
        direct=direct,
    )
    limit = _workbook_source._MAX_SOURCE_BYTES
    if initial.st_size > limit:
        _workbook_path_error(
            "Workbook exceeds the compressed source size limit",
            "source_too_large",
            path,
            entity,
            actual_bytes=initial.st_size,
            limit_bytes=limit,
        )

    try:
        with _open_workbook_binary(path) as handle:
            opened = os.fstat(handle.fileno())
            _require_workbook_identity(
                path,
                datas,
                initial,
                opened,
                entity=entity,
                direct=direct,
                phase="open",
            )
            content = handle.read(limit + 1)
            after = os.fstat(handle.fileno())
            current = _require_workbook_identity(
                path,
                datas,
                initial,
                after,
                entity=entity,
                direct=direct,
                phase="read",
            )
    except AuthoringError:
        raise
    except Exception as error:
        _workbook_path_error(
            "Workbook could not be opened and read safely",
            "source_open_error",
            path,
            entity,
            error_type=type(error).__name__,
        )

    if len(content) > limit:
        _workbook_path_error(
            "Workbook exceeds the compressed source size limit",
            "source_too_large",
            path,
            entity,
            actual_bytes=len(content),
            limit_bytes=limit,
        )
    opened_identity = _workbook_source._identity_from_stat(opened)
    after_identity = _workbook_source._identity_from_stat(after)
    current_identity = _workbook_source._identity_from_stat(current)
    if (
        opened_identity != after_identity
        or after_identity != current_identity
        or len(content) != after.st_size
    ):
        _workbook_path_error(
            "Workbook changed while its immutable snapshot was read",
            "source_changed_during_read",
            path,
            entity,
            actual_bytes=len(content),
            expected_bytes=after.st_size,
        )

    snapshot = _workbook_source._WorkbookSnapshot(
        content,
        after_identity,
        stat.S_IMODE(after.st_mode),
    )
    _workbook_source._preflight_archive(snapshot, path)
    return snapshot


def _validate_workbook_path(
    path: Path,
    datas: Path,
    *,
    entity: str,
    direct: bool,
) -> os.stat_result:
    try:
        datas_identity = datas.lstat()
        path_identity = path.lstat()
    except (OSError, ValueError) as error:
        _workbook_path_error(
            "Workbook path could not be inspected safely",
            "path_inspection_error",
            path,
            entity,
            error_type=type(error).__name__,
        )
    if _path_is_indirection(datas, datas_identity):
        _workbook_path_error(
            "Workbook Datas boundary is an unsafe path indirection",
            "boundary_indirection",
            path,
            entity,
        )
    if _path_is_indirection(path, path_identity):
        _workbook_path_error(
            "Workbook path is an unsafe indirection",
            "path_indirection",
            path,
            entity,
        )
    if not stat.S_ISDIR(datas_identity.st_mode):
        _workbook_path_error(
            "Workbook Datas boundary is not a directory",
            "boundary_wrong_type",
            path,
            entity,
        )
    if not stat.S_ISREG(path_identity.st_mode):
        _workbook_path_error(
            "Workbook path is not a regular file",
            "path_wrong_type",
            path,
            entity,
        )
    try:
        if not path.is_relative_to(datas):
            raise ValueError("outside Datas")
        if direct and path.parent != datas:
            raise ValueError("not a direct child")
        resolved_datas = datas.resolve(strict=True)
        resolved_path = path.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as error:
        _workbook_path_error(
            "Workbook path is outside its authoritative Datas boundary",
            "outside_datas",
            path,
            entity,
            error_type=type(error).__name__,
        )
    if resolved_datas != datas or not resolved_path.is_relative_to(resolved_datas):
        _workbook_path_error(
            "Workbook path resolves outside its authoritative Datas boundary",
            "outside_datas",
            path,
            entity,
            resolved_path=str(resolved_path),
        )
    if direct and resolved_path.parent != resolved_datas:
        _workbook_path_error(
            "Canonical workbook must be a direct child of Datas",
            "not_direct_child",
            path,
            entity,
            resolved_path=str(resolved_path),
        )
    return path_identity


def _require_workbook_identity(
    path: Path,
    datas: Path,
    initial: os.stat_result,
    opened: os.stat_result,
    *,
    entity: str,
    direct: bool,
    phase: str,
) -> os.stat_result:
    if not stat.S_ISREG(opened.st_mode) or not os.path.samestat(initial, opened):
        _workbook_path_error(
            "Workbook path changed before its content could be consumed",
            "path_identity_changed",
            path,
            entity,
            phase=phase,
        )
    current = _validate_workbook_path(
        path,
        datas,
        entity=entity,
        direct=direct,
    )
    if not os.path.samestat(current, opened):
        _workbook_path_error(
            "Workbook pathname no longer identifies the opened file",
            "path_identity_changed",
            path,
            entity,
            phase=phase,
        )
    return current


def _path_is_indirection(path: Path, identity: os.stat_result) -> bool:
    if stat.S_ISLNK(identity.st_mode) or path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if callable(is_junction):
        try:
            if is_junction():
                return True
        except OSError:
            return True
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(getattr(identity, "st_file_attributes", 0) & reparse_flag)


def _workbook_path_error(
    message: str,
    reason: str,
    path: Path,
    entity: str,
    **details: Any,
) -> NoReturn:
    raise AuthoringError(
        "invalid_workbook_source",
        message,
        {
            "entity": entity,
            "path": str(path),
            "reason": reason,
            **details,
        },
    )


def _partial_workbook_count(snapshot: Any, path: Path) -> int:
    """Best-effort id count from an already safety-preflighted workbook."""

    try:
        with _workbook_source._open_snapshot(snapshot, path, read_only=True) as workbook:
            sheet = workbook.active
            if sheet is None:
                return 0
            _workbook_source._validate_dimensions(sheet, path)
            marker_cells = [cell for row in sheet.iter_rows() for cell in row if cell.value == "##var"]
            if len(marker_cells) != 1:
                return 0
            marker = marker_cells[0]
            type_markers = [
                cell
                for row in sheet.iter_rows()
                for cell in row
                if getattr(cell, "column", None) == marker.column
                and cell.value == "##type"
            ]
            if len(type_markers) != 1 or type_markers[0].row <= marker.row:
                return 0
            id_columns = [
                column
                for column in range(1, sheet.max_column + 1)
                if sheet.cell(marker.row, column).value == "id"
            ]
            if len(id_columns) != 1:
                return 0
            return sum(
                1
                for row in range(type_markers[0].row + 1, sheet.max_row + 1)
                if type(sheet.cell(row, id_columns[0]).value) is str
                and sheet.cell(row, id_columns[0]).value != ""
            )
    except Exception:
        return 0


_TOP_LEVEL_MAPPING_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):(?:\s*#.*)?$")
_CANONICAL_ENTITY_RE = re.compile(r"^  ([A-Za-z0-9_.-]+):(?:\s*#.*)?$")


def _fallback_yaml_inventory(path: Path) -> tuple[dict[str, int], set[str]]:
    """Recover canonical ids from malformed text without accepting it as valid."""

    try:
        text, _ = _yaml_source._read_text(path)
    except Exception:
        return {}, set()
    by_storage = {schema.storage_name: schema.entity for schema in _YAML_SCHEMAS}
    current: str | None = None
    counts: dict[str, int] = {}
    scenarios: set[str] = set()
    for line in text.splitlines():
        top_level = _TOP_LEVEL_MAPPING_RE.fullmatch(line)
        if top_level is not None:
            current = by_storage.get(top_level.group(1))
            continue
        if line and not line[0].isspace() and not line.lstrip().startswith("#"):
            current = None
            continue
        entity = _CANONICAL_ENTITY_RE.fullmatch(line)
        if current is None or entity is None:
            continue
        entity_id = entity.group(1)
        counts[current] = counts.get(current, 0) + 1
        if current == "scenario":
            scenarios.add(entity_id)
    return counts, scenarios


def _error_finding(error: Exception, phase: str) -> EligibilityFinding:
    if isinstance(error, AuthoringError):
        entity = error.details.get("entity")
        entity_id = error.details.get("id")
        return EligibilityFinding(
            error.code,
            error.message,
            entity if isinstance(entity, str) and entity else None,
            entity_id if isinstance(entity_id, str) and entity_id else None,
        )
    return EligibilityFinding(
        f"status_{phase}_failed",
        f"Model status could not complete the {phase} phase.",
    )


def _make_status(
    model_digest: str,
    counts: dict[str, int],
    requirements: list[EligibilityFinding],
    warnings: list[EligibilityFinding],
    scenarios: set[str],
    latest_run_id: str | None,
    *,
    state: StatusState,
    smoke_eligible: bool,
) -> ModelStatus:
    ordered_requirements = _ordered_issues(requirements)
    ordered_warnings = _ordered_issues(warnings)
    return ModelStatus(
        model_digest=model_digest,
        structural_valid=state != "failed",
        smoke_eligible=smoke_eligible,
        state=state,
        entity_counts=counts,
        missing_requirements=ordered_requirements,
        warnings=ordered_warnings,
        available_scenarios=tuple(sorted(scenarios)),
        latest_smoke_run_id=latest_run_id,
    )


def _ordered_issues(
    issues: list[EligibilityFinding],
) -> tuple[EligibilityFinding, ...]:
    unique: dict[tuple[str, str | None, str | None, str], EligibilityFinding] = {}
    for issue in issues:
        key = (issue.code, issue.entity, issue.id, issue.message)
        unique.setdefault(key, issue)
    return tuple(
        sorted(
            unique.values(),
            key=lambda issue: (
                issue.code,
                issue.entity or "",
                issue.id or "",
                issue.message,
            ),
        )
    )


__all__ = ["ModelStatus", "derive_status"]
