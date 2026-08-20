from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation
from typing import Any

from igess.human_numbers import human_number

from .kpis import build_overview
from .loader import ReportData


_SECONDS_PER_DAY = 24 * 60 * 60
_DEFAULT_FISH_RATE_SAMPLE_SECONDS = 5 * 60


def build_report_view_model(data: ReportData) -> dict[str, Any]:
    resource_ids = sorted(
        {
            str(resource_id)
            for row in data.timeline
            for resource_id in dict(row.get("resources", {}))
        }
    )
    return {
        "schema_version": 5,
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
    balance_profiles = _fish_balance_profiles(
        data,
        behavior_profiles=behavior_profiles,
    )
    return {
        "available": bool(core_profiles or behavior_profiles),
        "balance": {
            "time_basis": "cumulative_active_seconds",
            "rate_definition": (
                "online_gross_acquisition_per_active_sample_window"
            ),
            "rate_sample_interval_active_seconds": chart_point(
                _fish_rate_sample_seconds(data)
            ),
            "profiles": balance_profiles,
        },
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


def _fish_balance_profiles(
    data: ReportData,
    *,
    behavior_profiles: dict[str, Any],
) -> dict[str, Any]:
    raw_core_profiles = data.luck_progression.get("profiles", {})
    if not isinstance(raw_core_profiles, dict):
        raw_core_profiles = {}
    profile_ids = list(
        dict.fromkeys(
            [
                *data.profiles,
                *[str(value) for value in raw_core_profiles],
                *behavior_profiles,
            ]
        )
    )
    interval_seconds = _fish_rate_sample_seconds(data)
    result: dict[str, Any] = {}
    for profile_id in profile_ids:
        raw_core = raw_core_profiles.get(profile_id, {})
        if not isinstance(raw_core, dict):
            raw_core = {}
        active_duration = _active_duration_seconds(raw_core)
        daily_online_seconds = _daily_online_seconds(data, profile_id)
        rate_rows, cumulative_rows = _fish_economy_rows(
            data.events,
            profile_id=profile_id,
            active_duration_seconds=active_duration,
            daily_online_seconds=daily_online_seconds,
            interval_seconds=interval_seconds,
        )
        result[profile_id] = {
            "active_duration_seconds": chart_point(active_duration),
            "daily_online_seconds": chart_point(daily_online_seconds),
            "rate_rows": rate_rows,
            "cumulative_rows": cumulative_rows,
        }
        behavior_profile = behavior_profiles.get(profile_id)
        if isinstance(behavior_profile, dict):
            behavior_profile["daily_online_seconds"] = chart_point(
                daily_online_seconds
            )
            days = _daily_progression_days(
                behavior_profile.get("rows", []),
                active_duration_seconds=active_duration,
                daily_online_seconds=daily_online_seconds,
            )
            behavior_profile["days"] = days
            behavior_profile["weeks"] = _weekly_progression_weeks(
                days,
                active_duration_seconds=active_duration,
                daily_online_seconds=daily_online_seconds,
            )
    return result


def _fish_rate_sample_seconds(data: ReportData) -> int:
    value = data.luck_progression.get(
        "sample_interval_active_seconds",
        _DEFAULT_FISH_RATE_SAMPLE_SECONDS,
    )
    try:
        result = int(value)
    except (TypeError, ValueError):
        return _DEFAULT_FISH_RATE_SAMPLE_SECONDS
    return result if result > 0 else _DEFAULT_FISH_RATE_SAMPLE_SECONDS


def _active_duration_seconds(raw_core_profile: dict[str, Any]) -> int:
    summary = raw_core_profile.get("summary", {})
    if isinstance(summary, dict):
        value = summary.get("active_duration_seconds")
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            pass
    rows = raw_core_profile.get("rows", [])
    if not isinstance(rows, list):
        return 0
    values = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            values.append(int(row.get("active_time_seconds", 0)))
        except (TypeError, ValueError):
            continue
    return max(values, default=0)


def _daily_online_seconds(data: ReportData, profile_id: str) -> int:
    try:
        value = data.manifest["strategy"]["parameters"][
            "behavior_scheduler"
        ]["profiles"][profile_id]["session"]["daily_online_seconds"]
        result = int(value)
    except (KeyError, TypeError, ValueError):
        return _SECONDS_PER_DAY
    if result <= 0 or result > _SECONDS_PER_DAY:
        return _SECONDS_PER_DAY
    return result


def _fish_economy_rows(
    events: list[dict[str, Any]],
    *,
    profile_id: str,
    active_duration_seconds: int,
    daily_online_seconds: int,
    interval_seconds: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if active_duration_seconds <= 0:
        return [], []
    bucket_count = math.ceil(active_duration_seconds / interval_seconds)
    bucket_money = [Decimal(0) for _ in range(bucket_count)]
    bucket_material = [Decimal(0) for _ in range(bucket_count)]
    for event in events:
        if str(event.get("profile_id", "")) != profile_id:
            continue
        if event.get("kind") == "fish_offline_settled":
            continue
        details = event.get("details", {})
        if not isinstance(details, dict):
            continue
        try:
            wall_time = max(0, int(event.get("time_seconds", 0)))
        except (TypeError, ValueError):
            continue
        active_time = _active_seconds_at(
            wall_time,
            daily_online_seconds=daily_online_seconds,
        )
        if active_time > active_duration_seconds:
            continue
        bucket_index = min(
            max(0, (max(1, active_time) - 1) // interval_seconds),
            bucket_count - 1,
        )
        bucket_money[bucket_index] += _positive_decimal(
            details.get("fish_hall_money_added")
        )
        bucket_material[bucket_index] += _positive_decimal(
            details.get("trash_material_added")
        )

    rate_rows: list[dict[str, Any]] = []
    cumulative_rows: list[dict[str, Any]] = []
    cumulative_money = Decimal(0)
    cumulative_material = Decimal(0)
    for index in range(bucket_count):
        start = index * interval_seconds
        end = min((index + 1) * interval_seconds, active_duration_seconds)
        elapsed = max(1, end - start)
        cumulative_money += bucket_money[index]
        cumulative_material += bucket_material[index]
        common = {
            "active_time_seconds": end,
            "active_time": chart_point(end),
            "profile_id": profile_id,
        }
        rate_rows.append(
            {
                **common,
                "resource_per_second": chart_point(
                    bucket_material[index] / Decimal(elapsed)
                ),
                "money_per_second": chart_point(
                    bucket_money[index] / Decimal(elapsed)
                ),
                "resource_acquired": chart_point(bucket_material[index]),
                "money_acquired": chart_point(bucket_money[index]),
            }
        )
        cumulative_rows.append(
            {
                **common,
                "money_acquired_cumulative": chart_point(
                    cumulative_money
                ),
                "resource_acquired_cumulative": chart_point(
                    cumulative_material
                ),
            }
        )
    return rate_rows, cumulative_rows


def _active_seconds_at(
    wall_time_seconds: int,
    *,
    daily_online_seconds: int,
) -> int:
    full_days, day_seconds = divmod(wall_time_seconds, _SECONDS_PER_DAY)
    return (
        full_days * daily_online_seconds
        + min(day_seconds, daily_online_seconds)
    )


def _positive_decimal(value: Any) -> Decimal:
    if value in (None, ""):
        return Decimal(0)
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(0)
    if not result.is_finite() or result <= 0:
        return Decimal(0)
    return result


def _daily_progression_days(
    rows: Any,
    *,
    active_duration_seconds: int,
    daily_online_seconds: int,
) -> list[dict[str, Any]]:
    source_rows = rows if isinstance(rows, list) else []
    day_count = math.ceil(active_duration_seconds / daily_online_seconds)
    grouped: dict[int, list[dict[str, Any]]] = {
        day: [] for day in range(1, day_count + 1)
    }
    for source_row in source_rows:
        if not isinstance(source_row, dict):
            continue
        try:
            active_time = max(
                0,
                int(source_row.get("active_time_seconds", 0)),
            )
        except (TypeError, ValueError):
            continue
        day = _progression_day_index(source_row, active_time, daily_online_seconds)
        grouped.setdefault(day, [])
        local_time = max(
            0,
            min(
                daily_online_seconds,
                active_time - (day - 1) * daily_online_seconds,
            ),
        )
        grouped[day].append(
            {
                **source_row,
                "day_index": day,
                "day_active_time_seconds": local_time,
                "day_active_time": chart_point(local_time),
            }
        )
    result = []
    for day in sorted(grouped):
        day_start = (day - 1) * daily_online_seconds
        duration = max(
            0,
            min(
                daily_online_seconds,
                active_duration_seconds - day_start,
            ),
        )
        day_rows = sorted(
            grouped[day],
            key=lambda row: (
                int(row.get("day_active_time_seconds", 0)),
                str(row.get("progression_category", "")),
            ),
        )
        result.append(
            {
                "day_index": day,
                "stage_id": f"online_day_{day}",
                "duration_seconds": chart_point(duration),
                "event_count": chart_point(len(day_rows)),
                "rows": day_rows,
            }
        )
    return result


def _weekly_progression_weeks(
    days: list[dict[str, Any]],
    *,
    active_duration_seconds: int,
    daily_online_seconds: int,
) -> list[dict[str, Any]]:
    weekly_online_seconds = daily_online_seconds * 7
    week_count = math.ceil(active_duration_seconds / weekly_online_seconds)
    grouped: dict[int, list[dict[str, Any]]] = {
        week: [] for week in range(1, week_count + 1)
    }
    for day in days:
        try:
            day_index = max(1, int(day.get("day_index", 1)))
        except (TypeError, ValueError):
            continue
        week_index = (day_index - 1) // 7 + 1
        day_offset = (day_index - (week_index - 1) * 7 - 1) * daily_online_seconds
        grouped.setdefault(week_index, [])
        for source_row in day.get("rows", []):
            if not isinstance(source_row, dict):
                continue
            try:
                day_active_time = max(
                    0,
                    int(source_row.get("day_active_time_seconds", 0)),
                )
            except (TypeError, ValueError):
                continue
            week_active_time = day_offset + day_active_time
            grouped[week_index].append(
                {
                    **source_row,
                    "week_index": week_index,
                    "week_active_time_seconds": week_active_time,
                    "week_active_time": chart_point(week_active_time),
                }
            )

    result = []
    for week_index in sorted(grouped):
        week_start = (week_index - 1) * weekly_online_seconds
        duration = max(
            0,
            min(
                weekly_online_seconds,
                active_duration_seconds - week_start,
            ),
        )
        week_rows = sorted(
            grouped[week_index],
            key=lambda row: (
                int(row.get("week_active_time_seconds", 0)),
                str(row.get("progression_category", "")),
            ),
        )
        result.append(
            {
                "week_index": week_index,
                "stage_id": f"online_week_{week_index}",
                "duration_seconds": chart_point(duration),
                "event_count": chart_point(len(week_rows)),
                "rows": week_rows,
            }
        )
    return result


def _progression_day_index(
    row: dict[str, Any],
    active_time_seconds: int,
    daily_online_seconds: int,
) -> int:
    stage_id = str(row.get("stage_id", ""))
    prefix = "online_day_"
    if stage_id.startswith(prefix):
        try:
            parsed = int(stage_id[len(prefix) :])
        except ValueError:
            parsed = 0
        if parsed > 0:
            return parsed
    return max(1, (max(1, active_time_seconds) - 1) // daily_online_seconds + 1)


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
