from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation
from typing import Any

from igess.human_numbers import human_number

from .kpis import build_overview
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
        "schema_version": 3,
        "scenario": {
            "id": data.scenario_id,
            "model_id": data.manifest.get("model_id"),
            "model_digest": data.manifest.get("model_digest"),
            "profiles": data.profiles,
        },
        "overview": _overview(data, resource_ids),
        "series": {
            "resources": _resource_series(data.timeline, resource_ids),
            "total_cps": _total_cps_series(data.timeline),
            "events": _event_series(data.events),
        },
        "diagnostics": _diagnostics(data),
        "fish_progression": _fish_progression(data),
        "evidence": _evidence(data),
        "artifacts": {
            "timeline": (data.run_dir / "timeline.json").as_posix(),
            "events": (data.run_dir / "events.json").as_posix(),
            "analysis": (data.run_dir / "analysis.json").as_posix(),
            "payback": (data.run_dir / "payback.csv").as_posix(),
            "manifest": (data.run_dir / "run_manifest.json").as_posix(),
            "luck_progression": (
                data.run_dir / "luck_progression.json"
            ).as_posix(),
            "behavior_progression": (
                data.run_dir / "behavior_progression.json"
            ).as_posix(),
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
    try:
        result = float(decimal)
    except (OverflowError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    if not decimal.is_zero() and result == 0.0:
        return None
    return result


def chart_point(value: Any) -> dict[str, Any]:
    return {
        **human_number(value),
        "chart_value": chart_value(value),
    }


def _overview(data: ReportData, resource_ids: list[str]) -> dict[str, Any]:
    exact = build_overview(data)
    first_key_unlock = _numeric_record(exact.get("first_key_unlock"), ("time_seconds",))
    worst_payback = _numeric_record(
        exact.get("worst_payback"),
        ("payback_seconds", "cost", "delta_cps"),
    )
    final_resources = {
        profile_id: {
            resource_id: chart_point(value)
            for resource_id, value in resources.items()
        }
        for profile_id, resources in exact["final_resources"].items()
    }
    return {
        "timeline_rows": chart_point(len(data.timeline)),
        "event_count": chart_point(len(data.events)),
        "missing_artifacts": list(data.missing_artifacts),
        "resource_ids": resource_ids,
        "duration_seconds": chart_point(exact["duration_seconds"]),
        "profiles": exact["profiles"],
        "final_resources": final_resources,
        "purchase_count": chart_point(exact["purchase_count"]),
        "first_key_unlock": first_key_unlock,
        "prestige_reset_count": chart_point(exact["prestige_reset_count"]),
        "worst_payback": worst_payback,
        "never_purchased_count": chart_point(exact["never_purchased_count"]),
        "never_unlocked_count": chart_point(exact["never_unlocked_count"]),
        "warning_category_count": chart_point(exact["warning_category_count"]),
    }


def _numeric_record(
    record: dict[str, Any] | None,
    numeric_fields: tuple[str, ...],
) -> dict[str, Any] | None:
    if record is None:
        return None
    result = dict(record)
    for field in numeric_fields:
        if field in result:
            result[field] = chart_point(result[field])
    return result


def _resource_series(timeline: list[dict[str, Any]], resource_ids: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in timeline:
        resources = dict(row.get("resources", {}))
        for resource_id in resource_ids:
            point = chart_point(resources.get(resource_id, 0))
            rows.append(
                {
                    "time_seconds": row.get("time_seconds", 0),
                    "time": chart_point(row.get("time_seconds", 0)),
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
                "time": chart_point(row.get("time_seconds", 0)),
                "profile_id": row.get("profile_id", ""),
                **point,
            }
        )
    return rows


def _event_series(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "time_seconds": event.get("time_seconds", 0),
            "time": chart_point(event.get("time_seconds", 0)),
            "profile_id": event.get("profile_id", ""),
            "kind": event.get("kind", ""),
            "item_id": event.get("item_id", ""),
            "details": event.get("details", {}),
        }
        for event in events
    ]


def _fish_progression(data: ReportData) -> dict[str, Any]:
    core_profiles = _progression_profiles(
        data.luck_progression,
        numeric_fields=(
            "strength_current",
            "strength_peak",
            "strength_delta",
            "fish_luck_current",
            "fish_luck_peak",
            "fish_luck_delta",
            "trash_luck_current",
            "trash_luck_peak",
            "trash_luck_delta",
            "fish_luck_delta_per_active_hour",
            "trash_luck_delta_per_active_hour",
            "time_since_fish_luck_growth_seconds",
            "time_since_trash_luck_growth_seconds",
            "strength_rebirth_count",
            "trash_man_rebirth_count",
        ),
    )
    behavior_profiles = _behavior_progression_profiles(
        data.behavior_progression
    )
    return {
        "available": bool(core_profiles or behavior_profiles),
        "core": {
            "time_basis": data.luck_progression.get("time_basis"),
            "sample_interval_active_seconds": chart_point(
                data.luck_progression.get(
                    "sample_interval_active_seconds",
                    0,
                )
            ),
            "profiles": core_profiles,
        },
        "persistent": {
            "time_basis": data.behavior_progression.get("time_basis"),
            "excluded_event_kinds": list(
                data.behavior_progression.get(
                    "excluded_event_kinds",
                    [],
                )
            ),
            "profiles": behavior_profiles,
        },
    }


def _progression_profiles(
    payload: dict[str, Any],
    *,
    numeric_fields: tuple[str, ...],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    raw_profiles = payload.get("profiles", {})
    if not isinstance(raw_profiles, dict):
        return result
    for profile_id, raw_profile in raw_profiles.items():
        if not isinstance(raw_profile, dict):
            continue
        rows = []
        for raw_row in raw_profile.get("rows", []):
            if not isinstance(raw_row, dict):
                continue
            row = dict(raw_row)
            row["active_time"] = chart_point(
                raw_row.get("active_time_seconds", 0)
            )
            row["wall_time"] = chart_point(
                raw_row.get("wall_time_seconds", 0)
            )
            for field in numeric_fields:
                row[field] = chart_point(raw_row.get(field, 0))
            rows.append(row)
        summary = _numeric_summary(
            raw_profile.get("summary", {}),
        )
        result[str(profile_id)] = {
            "summary": summary,
            "rows": rows,
        }
    return result


def _behavior_progression_profiles(
    payload: dict[str, Any],
) -> dict[str, Any]:
    result = _progression_profiles(
        payload,
        numeric_fields=(
            "metric_before",
            "metric_after",
            "metric_delta",
            "relative_delta",
            "gap_from_previous_progression_seconds",
        ),
    )
    raw_profiles = payload.get("profiles", {})
    if not isinstance(raw_profiles, dict):
        return result
    for profile_id, profile in result.items():
        raw_profile = raw_profiles.get(profile_id, {})
        density = []
        if isinstance(raw_profile, dict):
            for raw_row in raw_profile.get(
                "density_by_active_hour",
                [],
            ):
                if not isinstance(raw_row, dict):
                    continue
                row = dict(raw_row)
                for field in (
                    "active_hour_index",
                    "active_time_start_seconds",
                    "active_time_end_seconds",
                    "event_count",
                    "average_relative_delta",
                ):
                    row[field] = chart_point(raw_row.get(field, 0))
                density.append(row)
        profile["density_by_active_hour"] = density
    return result


def _numeric_summary(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    for key, item in value.items():
        if isinstance(item, dict):
            result[key] = dict(item)
        elif isinstance(item, (str, int, float, Decimal)):
            result[key] = chart_point(item)
        else:
            result[key] = item
    return result


def _diagnostics(data: ReportData) -> dict[str, Any]:
    analysis = data.analysis
    bottlenecks = analysis.get("bottleneck_report", {})
    return {
        "bottlenecks": bottlenecks,
        "bottleneck_gap_counts": _bottleneck_gap_counts(bottlenecks),
        "invalid_content": analysis.get("invalid_content_report", {}),
        "overpowered_content": analysis.get("overpowered_content_report", []),
        "payback": [
            _payback_diagnostic(row)
            for row in data.payback_rows
        ],
    }


def _bottleneck_gap_counts(bottlenecks: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(bottlenecks, dict):
        return {}
    return {
        str(profile_id): chart_point(len(gaps) if isinstance(gaps, list) else 0)
        for profile_id, gaps in sorted(
            bottlenecks.items(),
            key=lambda item: str(item[0]),
        )
    }


def _payback_diagnostic(row: dict[str, str]) -> dict[str, Any]:
    result: dict[str, Any] = dict(row)
    for field in ("payback_seconds", "cost", "delta_cps"):
        result[field] = chart_point(row.get(field))
    return result


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
                    "time": chart_point(event.get("time_seconds", 0)),
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
