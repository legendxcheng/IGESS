from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from .loader import ReportData


def build_report_view_model(data: ReportData) -> dict[str, Any]:
    resource_ids = sorted(
        {
            str(resource_id)
            for row in data.timeline
            for resource_id in dict(row.get("resources", {}))
        }
    )
    return {
        "schema_version": 1,
        "scenario": {
            "id": data.scenario_id,
            "model_id": data.manifest.get("model_id"),
            "profiles": data.profiles,
        },
        "overview": {
            "timeline_rows": len(data.timeline),
            "event_count": len(data.events),
            "missing_artifacts": list(data.missing_artifacts),
            "resource_ids": resource_ids,
        },
        "series": {
            "resources": _resource_series(data.timeline, resource_ids),
            "total_cps": _total_cps_series(data.timeline),
            "events": _event_series(data.events),
        },
        "diagnostics": _diagnostics(data),
        "evidence": _evidence(data),
        "artifacts": {
            "timeline": (data.run_dir / "timeline.json").as_posix(),
            "events": (data.run_dir / "events.json").as_posix(),
            "analysis": (data.run_dir / "analysis.json").as_posix(),
            "payback": (data.run_dir / "payback.csv").as_posix(),
            "manifest": (data.run_dir / "run_manifest.json").as_posix(),
        },
    }


def chart_value(value: Any) -> float | None:
    if value in (None, "", "Infinity"):
        return None
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not decimal.is_finite():
        return None
    if abs(decimal) > Decimal("1e308"):
        return None
    return float(decimal)


def chart_point(value: Any) -> dict[str, Any]:
    return {
        "display_value": "" if value is None else str(value),
        "chart_value": chart_value(value),
    }


def _resource_series(timeline: list[dict[str, Any]], resource_ids: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in timeline:
        resources = dict(row.get("resources", {}))
        for resource_id in resource_ids:
            point = chart_point(resources.get(resource_id, 0))
            rows.append(
                {
                    "time_seconds": row.get("time_seconds", 0),
                    "profile_id": row.get("profile_id", ""),
                    "resource_id": resource_id,
                    **point,
                }
            )
    return rows


def _total_cps_series(timeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in timeline:
        point = chart_point(row.get("total_cps", 0))
        rows.append(
            {
                "time_seconds": row.get("time_seconds", 0),
                "profile_id": row.get("profile_id", ""),
                **point,
            }
        )
    return rows


def _event_series(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "time_seconds": event.get("time_seconds", 0),
            "profile_id": event.get("profile_id", ""),
            "kind": event.get("kind", ""),
            "item_id": event.get("item_id", ""),
            "details": event.get("details", {}),
        }
        for event in events
    ]


def _diagnostics(data: ReportData) -> dict[str, Any]:
    analysis = data.analysis
    return {
        "bottlenecks": analysis.get("bottleneck_report", {}),
        "invalid_content": analysis.get("invalid_content_report", {}),
        "overpowered_content": analysis.get("overpowered_content_report", []),
        "payback": [
            {
                **row,
                **chart_point(row.get("payback_seconds")),
            }
            for row in data.payback_rows
        ],
    }


def _evidence(data: ReportData) -> dict[str, Any]:
    traces = []
    source_refs = []
    for event in data.events:
        details = event.get("details", {})
        if isinstance(details, dict) and details.get("formula_trace"):
            traces.append(
                {
                    "profile_id": event.get("profile_id", ""),
                    "time_seconds": event.get("time_seconds", 0),
                    "kind": event.get("kind", ""),
                    "item_id": event.get("item_id", ""),
                    "formula_trace": details.get("formula_trace", ""),
                }
            )
    for row in data.payback_rows:
        if row.get("formula_trace"):
            traces.append(
                {
                    "profile_id": row.get("profile_id", ""),
                    "kind": row.get("kind", ""),
                    "item_id": row.get("item_id", ""),
                    "formula_trace": row.get("formula_trace", ""),
                }
            )
        if row.get("source_ref"):
            source_refs.append(
                {
                    "profile_id": row.get("profile_id", ""),
                    "kind": row.get("kind", ""),
                    "item_id": row.get("item_id", ""),
                    "source_ref": row.get("source_ref", ""),
                    "source_workbook": row.get("source_workbook", ""),
                    "source_table": row.get("source_table", ""),
                    "source_row": row.get("source_row", ""),
                }
            )
    return {"traces": traces, "source_refs": source_refs}
