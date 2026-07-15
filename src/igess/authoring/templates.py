"""Exact blank source templates for incremental model authoring."""

from __future__ import annotations

from datetime import datetime
from io import BytesIO
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, NoReturn
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from openpyxl import Workbook
import yaml

from .entity_schema import ENTITY_SCHEMAS
from .response import AuthoringError


_MODEL_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_INVALID_DEFAULT_ID_CHARACTER_RE = re.compile(r"[^A-Za-z0-9_-]")
_MODIFIED_PROPERTY_RE = re.compile(
    rb"(<dcterms:modified xsi:type=\"dcterms:W3CDTF\">)[^<]*(</dcterms:modified>)"
)
_FIXED_WORKBOOK_TIME = datetime(2026, 6, 26, 0, 0, 0)
_FIXED_ZIP_TIME = (2026, 6, 26, 0, 0, 0)

_WORKBOOK_ENTITIES = (
    ("resource", "resources"),
    ("generator", "generators"),
    ("activity", "activities"),
    ("activity_output", "activity_outputs"),
    ("upgrade", "upgrades"),
    ("constant", "constants"),
    ("milestone", "milestones"),
    ("prestige_layer", "prestige_layers"),
)

_FIELD_COMMENTS = {
    "resource": {
        "id": "stable resource id",
        "name": "display name",
        "dimension": "quantity dimension",
    },
    "generator": {
        "id": "stable generator id",
        "name": "display name",
        "generator_type": "YAML generator type",
        "output_resource": "produced resource id",
        "source_type": "source type id",
        "base_output": "base output per second",
        "base_cost": "first purchase cost",
        "cost_resource": "resource spent",
        "cost_growth": "exponential cost growth",
        "unlock_condition": "deterministic unlock condition",
    },
    "activity": {
        "id": "stable activity id",
        "name": "display name",
        "source_type": "source type id",
        "unlock_condition": "deterministic unlock condition",
    },
    "activity_output": {
        "id": "stable output id",
        "activity_id": "activity id",
        "output_resource": "produced resource id",
        "amount_per_second": "full-time amount per second",
    },
    "upgrade": {
        "id": "stable upgrade id",
        "name": "display name",
        "target": "modifier target",
        "modifier_type": "modifier type id",
        "value": "modifier value",
        "cost_resource": "resource spent",
        "base_cost": "purchase cost",
        "unlock_condition": "deterministic unlock condition",
    },
    "constant": {
        "id": "stable constant id",
        "value": "string-encoded number",
    },
    "milestone": {
        "id": "stable milestone id",
        "name": "display name",
        "condition": "condition",
        "reward_resource": "resource rewarded",
        "reward_amount": "reward amount",
    },
    "prestige_layer": {
        "id": "stable prestige id",
        "name": "display name",
        "trigger_resource": "resource measured",
        "reward_resource": "resource rewarded",
        "formula": "YAML formula id",
        "divisor": "formula divisor",
        "exponent": "formula exponent",
        "min_gain": "minimum gain",
        "reset_resources": "resources reset",
        "unlock_condition": "condition",
    },
}

_README = """# IGESS Incremental Authoring Project

`economy.yaml` and `Datas/` are the formal sources of truth. `luban_exports/` is generated from those sources; do not edit generated exports by hand.

## Agent workflow

Work with an Agent to add one rule at a time. After every rule, inspect model status and any automatic smoke result before adding the next rule. Once the model is complete, run formal simulations and tune the same attributable source state.

## Commands

```powershell
igess model init --out projects/my-game
igess model status --project .
igess model apply --project . --change changes/next-rule.yaml
igess model simulate --project . --scenario smoke
```

## Artifacts

- `economy.yaml`: formal YAML rules and engine defaults.
- `Datas/`: formal Luban workbook rules.
- `luban_exports/`: generated runtime tables.
- `changes/`: attributable incremental change records and proposed changes.
- `runs/`: simulation run records and outputs.
- `reports/`: generated analysis reports.
"""

_RUN_SCRIPT = """$ErrorActionPreference = "Stop"

& igess model status --project $PSScriptRoot
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

& igess model simulate --project $PSScriptRoot --scenario smoke
exit $LASTEXITCODE
"""


def initialize_authoring_project(
    out: str | os.PathLike[str], model_id: str | None = None
) -> Path:
    """Create an exact blank authoring project in an absent or empty directory."""

    target = Path(out).expanduser()
    effective_model_id = (
        _model_id_from_output_name(target.name) if model_id is None else model_id
    )
    if not isinstance(effective_model_id, str) or not _MODEL_ID_RE.fullmatch(
        effective_model_id
    ):
        _invalid_model_id(target, effective_model_id)

    target_was_empty = _validate_empty_target(target)
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{target.name or 'igess'}-staging-",
            dir=parent,
        )
    )
    removed_empty_target = False
    try:
        _write_project(staging, effective_model_id)
        current_target_is_empty = _validate_empty_target(target)
        if current_target_is_empty:
            target.rmdir()
            removed_empty_target = True
        os.replace(staging, target)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        if target_was_empty and removed_empty_target and not target.exists():
            target.mkdir()
        raise
    return target


def _model_id_from_output_name(output_name: str) -> str:
    """Derive a valid stable id while preserving every output-name character slot."""

    sanitized = _INVALID_DEFAULT_ID_CHARACTER_RE.sub("_", output_name)
    return sanitized or "model"


def _validate_empty_target(target: Path) -> bool:
    if target.is_symlink():
        _occupied_target(target, "unsafe_symlink")
    try:
        if not target.exists():
            return False
        if not target.is_dir():
            _occupied_target(target, "not_directory")
        if any(target.iterdir()):
            _occupied_target(target, "not_empty")
    except AuthoringError:
        raise
    except OSError as error:
        raise AuthoringError(
            "project_target_inaccessible",
            f"Authoring project target could not be inspected: {target}",
            {
                "error_type": type(error).__name__,
                "path": str(target),
                "reason": "access_error",
            },
        ) from None
    return True


def _occupied_target(target: Path, reason: str) -> NoReturn:
    raise AuthoringError(
        "project_not_empty",
        f"Authoring project target must be absent or empty: {target}",
        {"path": str(target), "reason": reason},
    )


def _invalid_model_id(target: Path, model_id: Any) -> NoReturn:
    raise AuthoringError(
        "invalid_model_id",
        "Model id must match [A-Za-z0-9_-]+",
        {
            "allowed": "[A-Za-z0-9_-]+",
            "model_id": model_id,
            "path": str(target),
            "reason": "invalid_explicit_id",
        },
    )


def _write_project(root: Path, model_id: str) -> None:
    datas = root / "Datas"
    datas.mkdir()
    for directory in ("luban_exports", "runs", "reports", "changes"):
        (root / directory).mkdir()
    _write_text(root / "economy.yaml", _yaml_text(model_id))
    _write_text(root / "README.md", _README)
    _write_text(root / "run.ps1", _RUN_SCRIPT)
    _write_registry(datas / "__tables__.xlsx")
    for entity, _table_id in _WORKBOOK_ENTITIES:
        schema = ENTITY_SCHEMAS[entity]
        _write_entity_workbook(datas / schema.storage_name, entity)


def _yaml_text(model_id: str) -> str:
    source_types = {
        "active": {"description": "Active player actions"},
        "generator": {"description": "Automatic generator output"},
        "offline": {"description": "Offline reward"},
        "milestone": {"description": "Milestone reward"},
        "prestige": {"description": "Prestige reward"},
    }
    data: dict[str, Any] = {
        "model": {
            "id": model_id,
            "tick_seconds": 1,
            "number_backend": "bignum_log",
            "random_seed": 20260626,
        },
        "formulas": {
            "exponential_cost": {
                "args": ["base_cost", "growth", "owned"],
                "expr": "base_cost * pow(growth, owned)",
            },
            "generator_output": {
                "args": ["base_output", "owned", "multiplier"],
                "expr": "base_output * owned * multiplier",
            },
            "prestige_gain": {
                "args": ["progress", "divisor", "exponent"],
                "expr": "floor(pow(progress / divisor, exponent))",
            },
        },
        "generator_types": {
            "building": {
                "cost_formula": "exponential_cost",
                "production_formula": "generator_output",
            }
        },
        "source_types": source_types,
        "modifier_pipeline": {
            "order": ["base", "flat", "add_pct", "mult", "exp"]
        },
        "modifier_types": {
            "flat": {"stage": "flat"},
            "add_pct": {"stage": "add_pct"},
            "multiply": {"stage": "mult"},
            "exponent": {"stage": "exp"},
        },
        "behavior_policies": {
            "cheap_unlock_first": {"type": "cheap_unlock_first"}
        },
        "session_patterns": {
            "authoring_default": {
                "offline_every_seconds": 60,
                "offline_duration_seconds": 0,
            }
        },
        "player_profiles": {
            "default": {
                "source_efficiency": {source_id: "1" for source_id in source_types},
                "behavior_policy": "cheap_unlock_first",
                "session_pattern": "authoring_default",
                "prestige_policy": "conservative",
                "activity_weights": {},
                "luck": "1",
            }
        },
        "scenarios": {
            "smoke": {
                "duration_hours": "0.002777777777777778",
                "time_mode": "tick",
                "profiles": ["default"],
                "start_state": "new_player",
                "record_interval_seconds": 1,
                "outputs": [
                    "resource_curve",
                    "purchase_timeline",
                    "unlock_timeline",
                    "prestige_timeline",
                    "bottleneck_report",
                ],
            }
        },
    }
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)


def _write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", newline="\n")


def _write_registry(path: Path) -> None:
    workbook = _new_workbook("__tables__")
    sheet = workbook.active
    sheet.append(["##var", "table", "path", "mode", "key"])
    sheet.append(
        ["##", "stable table id", "source workbook", "export mode", "map key field"]
    )
    sheet.append(["##type", "string", "string", "string", "string"])
    for entity, table_id in _WORKBOOK_ENTITIES:
        schema = ENTITY_SCHEMAS[entity]
        sheet.append([None, table_id, schema.storage_name, "map", "id"])
    _save_workbook(workbook, path)


def _write_entity_workbook(path: Path, entity: str) -> None:
    schema = ENTITY_SCHEMAS[entity]
    headers = ("id", *schema.field_names)
    comments = _FIELD_COMMENTS[entity]
    workbook = _new_workbook(path.stem)
    sheet = workbook.active
    sheet.append(["##var", *headers])
    sheet.append(["##", *(comments[field] for field in headers)])
    sheet.append(
        [
            "##type",
            *(
                "(list#sep=;),string" if field == "reset_resources" else "string"
                for field in headers
            ),
        ]
    )
    _save_workbook(workbook, path)


def _new_workbook(title: str) -> Workbook:
    workbook = Workbook()
    workbook.active.title = title
    workbook.properties.created = _FIXED_WORKBOOK_TIME
    workbook.properties.modified = _FIXED_WORKBOOK_TIME
    workbook.properties.creator = "IGESS"
    workbook.properties.lastModifiedBy = "IGESS"
    return workbook


def _save_workbook(workbook: Workbook, path: Path) -> None:
    raw = BytesIO()
    try:
        workbook.save(raw)
    finally:
        workbook.close()
    raw.seek(0)
    deterministic = BytesIO()
    with ZipFile(raw, "r") as source, ZipFile(
        deterministic, "w", compression=ZIP_DEFLATED, compresslevel=9
    ) as target:
        for original in source.infolist():
            info = ZipInfo(original.filename, _FIXED_ZIP_TIME)
            info.compress_type = ZIP_DEFLATED
            info.external_attr = original.external_attr
            info.create_system = original.create_system
            content = source.read(original.filename)
            if original.filename == "docProps/core.xml":
                content = _MODIFIED_PROPERTY_RE.sub(
                    rb"\g<1>2026-06-26T00:00:00Z\g<2>", content
                )
            target.writestr(info, content)
    path.write_bytes(deterministic.getvalue())


__all__ = ["initialize_authoring_project"]
