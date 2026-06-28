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
from .luban_exporter import export_registered_workbooks
from .outputs import OutputWriter
from .simulator import Simulator


def review_proposal(proposal_path: str | Path, output_dir: str | Path) -> dict[str, Any]:
    proposal_path = Path(proposal_path)
    output_dir = Path(output_dir)
    payload = json.loads(proposal_path.read_text(encoding="utf-8"))
    recommendations = [
        _normalize_recommendation(item, index)
        for index, item in enumerate(_extract_recommendations(payload), start=1)
    ]
    if not recommendations:
        raise ValueError("proposal contains no table recommendations")
    review = {
        "schema_version": 1,
        "proposal_path": proposal_path.as_posix(),
        "scenario_id": payload.get("scenario_id"),
        "recommendation_count": len(recommendations),
        "recommendations": recommendations,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "proposal_review.json").write_text(
        json.dumps(review, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (output_dir / "proposal_review.md").write_text(
        render_proposal_review_markdown(review),
        encoding="utf-8",
        newline="\n",
    )
    return review


def verify_edits(
    config: str | Path,
    proposal_path: str | Path,
    scenario_id: str,
    output_dir: str | Path,
    tables: str | Path | None = None,
    datas: str | Path | None = None,
    baseline: str | Path | None = None,
) -> dict[str, Any]:
    if (tables is None) == (datas is None):
        raise ValueError("verify-edits requires exactly one of --tables or --datas")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    proposal_path = Path(proposal_path)
    payload = json.loads(proposal_path.read_text(encoding="utf-8"))
    recommendations = [
        _normalize_recommendation(item, index)
        for index, item in enumerate(_extract_recommendations(payload), start=1)
    ]
    if not recommendations:
        raise ValueError("proposal contains no table recommendations")

    tables_dir = Path(tables) if tables is not None else output_dir / "exported_tables"
    if datas is not None:
        export_registered_workbooks(datas, tables_dir)

    table_checks = [_check_recommendation(tables_dir, item) for item in recommendations]

    raw = ConfigLoader.load(config, tables_dir)
    ConfigLinter.validate(raw)
    model = ModelBuilder.build(raw)
    result = Simulator(model).run_scenario(scenario_id)
    run_dir = output_dir / "run"
    OutputWriter.write_all(result, run_dir, model)

    artifacts: dict[str, str | None] = {
        "tables": tables_dir.as_posix(),
        "run": "run",
        "comparison": None,
        "gate": None,
    }
    gate_ok = True
    if baseline is not None:
        comparison_index = compare_runs(baseline, run_dir, output_dir / "compare")
        artifacts["comparison"] = comparison_index.as_posix()
        gate_result = evaluate_gates(baseline, run_dir, config, output_dir / "gate")
        artifacts["gate"] = (gate_result.output_dir / "gate_results.json").as_posix()
        gate_ok = gate_result.ok

    status = _rollup_status(table_checks, gate_ok)
    report = {
        "schema_version": 1,
        "scenario_id": scenario_id,
        "status": status,
        "summary": _verification_summary(status, table_checks),
        "proposal": {
            "path": proposal_path.as_posix(),
            "recommendation_count": len(recommendations),
        },
        "table_checks": table_checks,
        "artifacts": artifacts,
    }
    (output_dir / "verification_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (output_dir / "verification_report.md").write_text(
        render_verification_markdown(report),
        encoding="utf-8",
        newline="\n",
    )
    return report


def render_proposal_review_markdown(review: dict[str, Any]) -> str:
    lines = [
        "# IGESS Proposal Review",
        "",
        f"Scenario: `{review.get('scenario_id') or ''}`",
        f"Recommendations: `{review['recommendation_count']}`",
        "",
        "## Table Recommendations",
        "",
    ]
    for recommendation in review["recommendations"]:
        lines.append(
            f"- `{recommendation['workbook']}` row `{recommendation['row_id']}` "
            f"field `{recommendation['field']}`: {recommendation['suggested_value']}"
        )
    return "\n".join(lines) + "\n"


def render_verification_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# IGESS Edit Verification",
        "",
        f"Scenario: `{report['scenario_id']}`",
        f"Status: `{report['status']}`",
        "",
        report["summary"],
        "",
        "## Table Checks",
        "",
    ]
    for check in report["table_checks"]:
        lines.append(
            f"- [{check['status']}] `{check['table']}` row `{check['row_id']}` "
            f"field `{check['field']}`: expected `{check['expected']}`, actual `{check['actual']}`"
        )
    lines.extend(["", "## Artifacts", ""])
    for key, value in sorted(report["artifacts"].items()):
        lines.append(f"- {key}: `{value}`")
    return "\n".join(lines) + "\n"


def _extract_recommendations(payload: dict[str, Any]) -> list[dict[str, Any]]:
    recommendations = list(payload.get("table_recommendations") or [])
    recommendations.extend(payload.get("recommendations") or [])
    recommendations.extend(payload.get("changes") or [])
    for candidate in payload.get("best_candidates") or []:
        candidate_id = str(candidate.get("candidate_id") or "")
        for change in candidate.get("changes") or []:
            item = dict(change)
            if candidate_id:
                item["candidate_id"] = candidate_id
            recommendations.append(item)
    return recommendations


def _normalize_recommendation(item: dict[str, Any], index: int) -> dict[str, Any]:
    table = str(item.get("table") or "")
    row_id = str(item.get("row_id") or "")
    field = str(item.get("field") or "")
    recommendation_id = str(item.get("id") or f"table.{table}.{row_id}.{field}")
    return {
        "id": recommendation_id,
        "kind": "table_recommendation",
        "table": table,
        "workbook": str(item.get("workbook") or f"{table}.xlsx"),
        "row_id": row_id,
        "field": field,
        "current_value": str(item.get("current_value") or ""),
        "suggested_value": str(item.get("suggested_value") or ""),
        "reason": str(item.get("reason") or ""),
        "apply_mode": str(item.get("apply_mode") or "human_only"),
        **({"candidate_id": str(item["candidate_id"])} if item.get("candidate_id") else {}),
    }


def _check_recommendation(tables_dir: Path, recommendation: dict[str, Any]) -> dict[str, Any]:
    actual = _load_table_value(tables_dir, recommendation)
    expected = recommendation["suggested_value"]
    status = _match_status(actual, expected)
    return {
        "id": recommendation["id"],
        "status": status,
        "table": recommendation["table"],
        "workbook": recommendation["workbook"],
        "row_id": recommendation["row_id"],
        "field": recommendation["field"],
        "expected": expected,
        "actual": "" if actual is None else str(actual),
        "reason": recommendation.get("reason", ""),
    }


def _load_table_value(tables_dir: Path, recommendation: dict[str, Any]) -> Any:
    table_path = tables_dir / f"{recommendation['table']}.json"
    rows = json.loads(table_path.read_text(encoding="utf-8"))
    for row in rows:
        if str(row.get("id")) == recommendation["row_id"]:
            if recommendation["field"] not in row:
                return None
            return row[recommendation["field"]]
    return None


def _match_status(actual: Any, expected: str) -> str:
    if actual is None:
        return "missing"
    expected = str(expected)
    if _is_descriptive_suggestion(expected):
        return "needs_manual_review"
    expected_range = _parse_range(expected)
    actual_decimal = _decimal(actual)
    if expected_range is not None:
        if actual_decimal is None:
            return "mismatched"
        start, end = expected_range
        return "matched" if start <= actual_decimal <= end else "mismatched"
    expected_decimal = _decimal(expected)
    if expected_decimal is not None and actual_decimal is not None:
        return "matched" if actual_decimal == expected_decimal else "mismatched"
    return "matched" if str(actual) == expected else "mismatched"


def _parse_range(value: str) -> tuple[Decimal, Decimal] | None:
    parts = [part.strip() for part in value.split(" - ", maxsplit=1)]
    if len(parts) != 2:
        return None
    start = _decimal(parts[0])
    end = _decimal(parts[1])
    if start is None or end is None:
        return None
    return (start, end) if start <= end else (end, start)


def _decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _is_descriptive_suggestion(value: str) -> bool:
    text = value.strip().lower()
    return text.startswith(("review ", "consider ", "try ")) or "%" in text


def _rollup_status(table_checks: list[dict[str, Any]], gate_ok: bool) -> str:
    if not gate_ok or any(item["status"] in {"missing", "mismatched"} for item in table_checks):
        return "failed"
    if any(item["status"] == "needs_manual_review" for item in table_checks):
        return "needs_review"
    return "passed"


def _verification_summary(status: str, table_checks: list[dict[str, Any]]) -> str:
    matched = sum(1 for item in table_checks if item["status"] == "matched")
    review = sum(1 for item in table_checks if item["status"] == "needs_manual_review")
    failed = sum(1 for item in table_checks if item["status"] in {"missing", "mismatched"})
    if status == "passed":
        return f"{matched} recommendation(s) matched current exported tables."
    if status == "needs_review":
        return f"{matched} recommendation(s) matched; {review} need manual review."
    return f"{failed} recommendation check(s) failed."
