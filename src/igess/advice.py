from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .builder import ModelBuilder
from .compare import compare_runs
from .gates import evaluate_gates
from .linter import ConfigLinter
from .loader import ConfigLoader
from .outputs import OutputWriter
from .reporting.loader import ReportData, load_report_data
from .reporting.static import generate_static_report
from .simulator import Simulator


def run_advise(
    config: str | Path,
    tables: str | Path,
    scenario_id: str,
    output_dir: str | Path,
    baseline: str | Path | None = None,
) -> dict[str, Any]:
    output_dir = Path(output_dir)
    run_dir = output_dir / "run"
    report_dir = output_dir / "report"
    output_dir.mkdir(parents=True, exist_ok=True)

    raw = ConfigLoader.load(config, tables)
    ConfigLinter.validate(raw)
    model = ModelBuilder.build(raw)
    result = Simulator(model).run_scenario(scenario_id)
    OutputWriter.write_all(result, run_dir, model)
    report_index = generate_static_report(run_dir, report_dir)

    artifacts: dict[str, str] = {"report": _path(report_index)}
    if baseline is not None:
        compare_index = compare_runs(baseline, run_dir, output_dir / "compare")
        artifacts["comparison"] = _path(compare_index)
        gate_result = evaluate_gates(baseline, run_dir, config, output_dir / "gate")
        artifacts["gate"] = _path(gate_result.output_dir / "gate_results.json")

    return review_run(
        run_dir,
        output_dir,
        baseline=baseline,
        config_path=config,
        extra_artifacts=artifacts,
    )


def review_run(
    run_dir: str | Path,
    output_dir: str | Path,
    baseline: str | Path | None = None,
    config_path: str | Path | None = None,
    extra_artifacts: dict[str, str] | None = None,
) -> dict[str, Any]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts = dict(extra_artifacts or {})
    if baseline is not None and "comparison" not in artifacts:
        compare_index = compare_runs(baseline, run_dir, output_dir / "compare")
        artifacts["comparison"] = _path(compare_index)
    data = load_report_data(run_dir)
    advice = build_advice(data, output_dir, config_path=config_path, extra_artifacts=artifacts)
    write_advice(advice, output_dir)
    return advice


def build_advice(
    data: ReportData,
    output_dir: str | Path,
    config_path: str | Path | None = None,
    extra_artifacts: dict[str, str] | None = None,
) -> dict[str, Any]:
    output_dir = Path(output_dir)
    findings = _findings(data)
    table_recommendations = _table_recommendations(data)
    yaml_recommendations = _yaml_recommendations(data, config_path)
    status = "needs_attention" if any(item["severity"] == "warning" for item in findings) else "ok"
    artifact_paths = {
        "run": _path(data.run_dir),
        "timeline": _path(data.run_dir / "timeline.json"),
        "events": _path(data.run_dir / "events.json"),
        "analysis": _path(data.run_dir / "analysis.json"),
        "payback": _path(data.run_dir / "payback.csv"),
        **dict(extra_artifacts or {}),
    }
    summary = _summary(status, findings, table_recommendations, yaml_recommendations)
    return {
        "schema_version": 1,
        "scenario_id": data.scenario_id,
        "status": status,
        "summary": summary,
        "findings": findings,
        "table_recommendations": table_recommendations,
        "yaml_recommendations": yaml_recommendations,
        "verification": {
            "run_artifacts_read": True,
            "source_tables_modified": False,
            "recommendations_apply_tables": False,
            "output_dir": _path(output_dir),
        },
        "artifact_paths": artifact_paths,
    }


def write_advice(advice: dict[str, Any], output_dir: str | Path) -> None:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "advice.json").write_text(
        json.dumps(advice, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (output_dir / "advice.md").write_text(
        render_advice_markdown(advice),
        encoding="utf-8",
        newline="\n",
    )


def render_advice_markdown(advice: dict[str, Any]) -> str:
    lines = [
        "# IGESS Agent Advice",
        "",
        f"Scenario: `{advice['scenario_id']}`",
        f"Status: `{advice['status']}`",
        "",
        advice["summary"],
        "",
        "## Findings",
        "",
    ]
    if advice["findings"]:
        for finding in advice["findings"]:
            lines.append(
                f"- [{finding['severity']}] `{finding['category']}`: {finding['message']}"
            )
    else:
        lines.append("- No issues found.")
    lines.extend(["", "## Table Recommendations", ""])
    if advice["table_recommendations"]:
        for rec in advice["table_recommendations"]:
            lines.append(
                f"- `{rec['workbook']}` row `{rec['row_id']}` field `{rec['field']}`: "
                f"{rec['suggested_value']} ({rec['reason']})"
            )
    else:
        lines.append("- None.")
    lines.extend(["", "## YAML Recommendations", ""])
    if advice["yaml_recommendations"]:
        for rec in advice["yaml_recommendations"]:
            lines.append(
                f"- `{rec['section']}` in `{rec['file']}`: {rec['change_type']} "
                "(requires human approval)"
            )
    else:
        lines.append("- None.")
    lines.extend(["", "## Verification", ""])
    verification = advice["verification"]
    lines.append(f"- Source tables modified: `{verification['source_tables_modified']}`")
    lines.append(f"- Table recommendations are human-only: `{not verification['recommendations_apply_tables']}`")
    return "\n".join(lines) + "\n"


def _findings(data: ReportData) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    bottlenecks = data.analysis.get("bottleneck_report", {})
    for profile_id, gaps in sorted(bottlenecks.items()):
        if not gaps:
            continue
        worst = max(gaps, key=lambda item: int(item.get("duration", 0)))
        findings.append(
            {
                "id": f"progression_gap.{profile_id}.001",
                "severity": "warning",
                "category": "progression_gap",
                "profile_id": profile_id,
                "message": (
                    f"{profile_id} has a {worst['duration']}s progression gap "
                    f"between {worst['start']}s and {worst['end']}s."
                ),
                "evidence": {
                    "metric": "bottleneck_gap_seconds",
                    "actual": str(worst["duration"]),
                    "expected": "<60",
                    "source": "analysis.json",
                },
            }
        )
        break

    invalid = data.analysis.get("invalid_content_report", {})
    never_purchased = list(invalid.get("never_purchased", []))
    if never_purchased:
        findings.append(
            {
                "id": "invalid_content.never_purchased.001",
                "severity": "warning",
                "category": "invalid_content",
                "profile_id": None,
                "message": f"{len(never_purchased)} configured items were never purchased.",
                "evidence": {
                    "metric": "never_purchased",
                    "actual": ", ".join(never_purchased[:5]),
                    "source": "analysis.json",
                },
            }
        )

    payback = _worst_payback(data.payback_rows)
    if payback is not None:
        severity = "warning" if payback.get("payback_seconds") == "Infinity" else "info"
        findings.append(
            {
                "id": f"payback.{payback.get('profile_id')}.{payback.get('kind')}.{payback.get('item_id')}",
                "severity": severity,
                "category": "payback",
                "profile_id": payback.get("profile_id"),
                "message": (
                    f"{payback.get('profile_id')} has payback "
                    f"{payback.get('payback_seconds')}s for {payback.get('kind')} "
                    f"{payback.get('item_id')}."
                ),
                "evidence": {
                    "metric": "payback_seconds",
                    "actual": str(payback.get("payback_seconds") or ""),
                    "source": "payback.csv",
                    "source_ref": payback.get("source_ref", ""),
                },
            }
        )

    overpowered = data.analysis.get("overpowered_content_report", [])
    if overpowered:
        first = dict(overpowered[0])
        findings.append(
            {
                "id": f"overpowered.{first.get('item_id')}",
                "severity": "warning",
                "category": "overpowered_content",
                "profile_id": None,
                "message": (
                    f"{first.get('item_id')} accounts for purchase share "
                    f"{first.get('purchase_share')}."
                ),
                "evidence": {
                    "metric": "purchase_share",
                    "actual": str(first.get("purchase_share") or ""),
                    "source": "analysis.json",
                },
            }
        )
    return findings


def _table_recommendations(data: ReportData) -> list[dict[str, Any]]:
    payback = _worst_payback(data.payback_rows)
    if payback is None:
        return []
    kind = str(payback.get("kind") or "item")
    item_id = str(payback.get("item_id") or "")
    field = "cost_growth" if kind == "generator" else "base_cost"
    workbook = str(payback.get("source_workbook") or f"{kind}s.xlsx")
    table = str(payback.get("source_table") or f"{kind}s")
    return [
        {
            "id": f"table.{table}.{item_id}.{field}",
            "kind": "table_recommendation",
            "table": table,
            "workbook": workbook,
            "row_id": item_id,
            "source_row": str(payback.get("source_row") or ""),
            "field": field,
            "current_value": str(payback.get("cost") or ""),
            "suggested_value": "review a 5-10% softer early-game value",
            "reason": "Largest current payback pressure in the run artifacts.",
            "evidence": {
                "metric": "payback_seconds",
                "actual": str(payback.get("payback_seconds") or ""),
                "source": "payback.csv",
                "source_ref": payback.get("source_ref", ""),
            },
            "apply_mode": "human_only",
        }
    ]


def _yaml_recommendations(
    data: ReportData,
    config_path: str | Path | None,
) -> list[dict[str, Any]]:
    config_name = Path(config_path).name if config_path is not None else "economy.yaml"
    scenario_id = data.scenario_id or "scenario"
    return [
        {
            "id": f"yaml.regression_gates.{scenario_id}",
            "kind": "yaml_recommendation",
            "file": config_name,
            "section": f"regression_gates.{scenario_id}",
            "change_type": "add_or_update",
            "proposal_path": "yaml_plan.json",
            "requires_human_approval": True,
            "reason": "Capture reviewed scenario health as explicit regression gates.",
        }
    ]


def _summary(
    status: str,
    findings: list[dict[str, Any]],
    table_recommendations: list[dict[str, Any]],
    yaml_recommendations: list[dict[str, Any]],
) -> str:
    if status == "ok":
        return "Run artifacts look healthy. No table edits were applied."
    return (
        f"Found {len(findings)} analysis signals, "
        f"{len(table_recommendations)} human-only table recommendation, and "
        f"{len(yaml_recommendations)} YAML proposal candidate."
    )


def _worst_payback(rows: list[dict[str, str]]) -> dict[str, str] | None:
    if not rows:
        return None
    return max(rows, key=lambda row: _payback_sort_key(row.get("payback_seconds", "")))


def _payback_sort_key(value: str) -> Decimal:
    try:
        if value == "Infinity":
            return Decimal("Infinity")
        return Decimal(str(value or "0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _path(path: str | Path) -> str:
    return Path(path).as_posix()
