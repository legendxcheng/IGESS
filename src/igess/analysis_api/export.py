"""Explicit analysis exports; original runs and numeric inputs stay read-only."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from .contracts import AnalysisError
from .snapshot import read_bytes, safe_path
from .export_directory import new_export_directory, write_export_file


def export_evaluation(payload: dict[str, Any], out: str | Path, *, project: Path,
                      history_roots, target_path: Path) -> dict[str, str]:
    destination = Path(out).absolute()
    safe_path(destination.parent, destination)
    protected = [*history_roots, target_path, project / "economy.yaml",
                 *[project / name for name in ("Datas", "luban_exports", ".igess", "reports")]]
    config = read_bytes(project, project / "economy.yaml")
    if config:
        value = yaml.safe_load(config)
        engine = value.get("engine", {}) if isinstance(value, dict) else {}
        if not isinstance(engine, dict):
            raise AnalysisError("invalid_export_config", "Engine must be an object to determine protected inputs")
        source = engine.get("source_runtime", {})
        if not isinstance(source, dict):
            raise AnalysisError("invalid_export_config", "Source runtime must be an object")
        for path in (engine.get("data_root"), engine.get("python_schema"), source.get("project_root"), source.get("data_root")):
            if isinstance(path, str) and path:
                protected.append((project / path).resolve())
    resolved = destination.resolve()
    for path in protected:
        boundary = Path(path).resolve()
        if resolved.is_relative_to(boundary) or boundary.is_relative_to(resolved):
            raise AnalysisError("unsafe_output", "Export overlaps history or authoritative input")
    if destination.exists():
        raise AnalysisError("output_exists", "Export requires a new directory")
    # Build both documents before creating anything. Exclusive creation prevents overwrites.
    text = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    markdown = render_markdown(payload)
    with new_export_directory(destination) as directory_fd:
        for name, body in (("evaluation.json", text), ("evaluation.md", markdown)):
            write_export_file(destination, directory_fd, name, body)
    return {"json": str(destination / "evaluation.json"), "markdown": str(destination / "evaluation.md")}


def render_markdown(payload: dict[str, Any]) -> str:
    def cell(value):
        text = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
        return text.replace("|", "\\|").replace("\n", " ").replace("\r", " ")
    target_set = payload["target_set"]
    lines = ["# 目标对照", "", f"运行：{cell(payload['run_id'])}",
             f"目标：{cell(target_set['target_set_id'])} / {cell(target_set['version'])}",
             f"结论：{cell(payload['evaluation_status'])}", f"生成时间：{payload['generated_at']}", "",
             "| 目标 | 指标版本 | 目标值 | 实际值 | 偏差 | 判定 | 覆盖/原因 |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for row in payload["targets"]:
        actual = row["actual"]
        values = (row["target_id"], actual["definition_version"], row["target"]["value"],
                  actual.get("value", actual["value_status"]), row.get("delta", ""), row["status"],
                  {"coverage": actual["coverage"], "reason": row["reason"]})
        lines.append("| " + " | ".join(cell(v) for v in values) + " |")
    lines.extend(["", "## 归因与证据", "", "```json",
                  json.dumps({"manifest": payload["manifest"], "input_digests": payload["input_digests"],
                              "target_set": target_set, "evidence": {r["target_id"]: r["actual"]["evidence"] for r in payload["targets"]}},
                             ensure_ascii=False, indent=2).replace("```", "\\u0060\\u0060\\u0060"), "```", ""])
    return "\n".join(lines)
