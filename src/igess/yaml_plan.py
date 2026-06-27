from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import yaml


ALLOWED_TOP_LEVEL_SECTIONS = {
    "advice",
    "behavior_policies",
    "formulas",
    "generator_types",
    "modifier_pipeline",
    "modifier_types",
    "player_profiles",
    "regression_gates",
    "report",
    "scan_presets",
    "scenarios",
    "session_patterns",
    "source_types",
}
TABLE_SUFFIXES = {".xlsx", ".xls", ".csv", ".tsv"}
TABLE_PATH_MARKERS = {"data-tables", "datas", "luban_exports"}


class PlanValidationError(ValueError):
    pass


def create_yaml_plan(
    config_path: str | Path,
    intent: str,
    output_dir: str | Path,
) -> dict[str, Any]:
    config_path = Path(config_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    scenario_id = _first_scenario(data)
    gate_patch = {
        scenario_id: {
            "max_payback_seconds": {
                "generator:fisherman": 999999,
            },
            "max_unlock_delay_pct": {
                "generator:fisherman": 25,
            },
        }
    }
    plan = {
        "schema_version": 1,
        "intent": intent,
        "requires_human_approval": True,
        "changes": [
            {
                "file": str(config_path),
                "section": f"regression_gates.{scenario_id}",
                "operation": "merge",
                "value": gate_patch,
            }
        ],
        "expected_effects": [
            "Adds reviewable regression gates for the selected scenario.",
            "Does not edit Luban or Excel source tables.",
        ],
    }
    (output_dir / "yaml_plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (output_dir / "yaml_plan.md").write_text(_markdown(plan), encoding="utf-8", newline="\n")
    (output_dir / "economy.patch.yaml").write_text(
        yaml.safe_dump({"regression_gates": gate_patch}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
        newline="\n",
    )
    return plan


def apply_yaml_plan(
    config_path: str | Path,
    plan_path: str | Path,
    *,
    approve: bool,
    tables: str | Path | None = None,
) -> dict[str, Any]:
    if not approve:
        raise PlanValidationError("YAML plan application requires explicit approval.")
    config_path = Path(config_path)
    plan_path = Path(plan_path)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    _validate_plan(plan, config_path)
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    for change in plan["changes"]:
        top_level = str(change["section"]).split(".", 1)[0]
        if change["operation"] != "merge":
            raise PlanValidationError(f"Unsupported YAML operation: {change['operation']}")
        data[top_level] = _merge_dicts(dict(data.get(top_level, {})), dict(change["value"]))
    backup_path = config_path.with_suffix(config_path.suffix + ".bak")
    shutil.copyfile(config_path, backup_path)
    config_path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
        newline="\n",
    )
    lint_status = "skipped"
    if tables is not None:
        try:
            from .linter import ConfigLinter
            from .loader import ConfigLoader

            ConfigLinter.validate(ConfigLoader.load(config_path, tables))
            lint_status = "passed"
        except Exception as exc:  # noqa: BLE001 - restore the approved config on invalid YAML plans.
            shutil.copyfile(backup_path, config_path)
            raise PlanValidationError(f"Applied YAML plan failed lint and was restored: {exc}") from exc
    return {
        "schema_version": 1,
        "status": "applied",
        "config": config_path.as_posix(),
        "backup": backup_path.as_posix(),
        "changes_applied": len(plan["changes"]),
        "lint": lint_status,
    }


def _validate_plan(plan: dict[str, Any], config_path: Path) -> None:
    if plan.get("schema_version") != 1:
        raise PlanValidationError("Unsupported YAML plan schema version.")
    changes = plan.get("changes")
    if not isinstance(changes, list) or not changes:
        raise PlanValidationError("YAML plan must include at least one change.")
    for change in changes:
        target = Path(str(change.get("file") or ""))
        _validate_target_path(target, config_path)
        section = str(change.get("section") or "")
        top_level = section.split(".", 1)[0]
        if top_level not in ALLOWED_TOP_LEVEL_SECTIONS:
            raise PlanValidationError(f"YAML section is not allowlisted: {section}")
        if change.get("operation") != "merge":
            raise PlanValidationError(f"Unsupported YAML operation: {change.get('operation')}")
        if not isinstance(change.get("value"), dict):
            raise PlanValidationError("YAML merge value must be a mapping.")


def _validate_target_path(target: Path, config_path: Path) -> None:
    parts = {part.lower() for part in target.parts}
    if target.suffix.lower() in TABLE_SUFFIXES:
        raise PlanValidationError(f"YAML plan cannot touch table file: {target}")
    if parts & TABLE_PATH_MARKERS:
        raise PlanValidationError(f"YAML plan cannot touch table path: {target}")
    if target.name and target.name != config_path.name and target.resolve() != config_path.resolve():
        raise PlanValidationError(f"YAML plan target does not match config: {target}")


def _merge_dicts(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    merged = dict(left)
    for key, value in right.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dicts(dict(merged[key]), value)
        else:
            merged[key] = value
    return merged


def _first_scenario(data: dict[str, Any]) -> str:
    scenarios = data.get("scenarios") or {}
    if isinstance(scenarios, dict) and scenarios:
        return str(next(iter(scenarios)))
    return "day_1_progression"


def _markdown(plan: dict[str, Any]) -> str:
    lines = [
        "# IGESS YAML Plan",
        "",
        f"Intent: {plan['intent']}",
        "",
        "## Changes",
        "",
    ]
    for change in plan["changes"]:
        lines.append(
            f"- `{change['operation']}` `{change['section']}` in `{change['file']}`"
        )
    lines.extend(["", "## Expected Effects", ""])
    for effect in plan["expected_effects"]:
        lines.append(f"- {effect}")
    lines.extend(["", "Requires human approval before application.", ""])
    return "\n".join(lines)
