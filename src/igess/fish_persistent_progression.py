from __future__ import annotations

import math
from collections import Counter
from decimal import Decimal
from typing import Any

from .fish_progression_common import (
    decimal_text,
    decimal_value,
    duration_seconds,
    optional_decimal,
    percentile,
    profile_events,
    profile_schedule,
)
from .fish_session import FishDailySessionSchedule, SECONDS_PER_DAY
from .schema import EconomyModel, Event, SimulationResult


_PERSISTENT_EVENT_KINDS = frozenset(
    {
        "barbell_synthesized",
        "fish_hall_upgraded",
        "strength_reborn",
        "trash_man_reborn",
        "trash_man_realm_broken_through",
        "torpedo_purchased",
        "torpedo_upgraded",
        "fish_system_unlocked",
        "fish_ability_unlocked",
        "fish_strategy_unlocked",
    }
)


def build_persistent_progression(
    result: SimulationResult,
    model: EconomyModel,
) -> dict[str, Any]:
    scenario = model.scenarios[result.scenario_id]
    wall_duration = duration_seconds(scenario.duration_hours)
    profiles: dict[str, Any] = {}
    for profile_id in scenario.profiles:
        schedule = profile_schedule(model, profile_id)
        active_duration = schedule.active_seconds_at(wall_duration)
        rows: list[dict[str, Any]] = []
        previous_active = 0
        for event in profile_events(result.events, profile_id):
            row = _persistent_event_row(
                event,
                schedule=schedule,
                previous_active_time=previous_active,
            )
            if row is None:
                continue
            rows.append(row)
            previous_active = int(row["active_time_seconds"])
        profiles[profile_id] = {
            "summary": _behavior_summary(
                rows,
                duration_seconds=wall_duration,
                active_duration_seconds=active_duration,
                schedule=schedule,
            ),
            "density_by_active_hour": _density_by_active_hour(
                rows,
                active_duration,
            ),
            "rows": rows,
        }
    return {
        "schema_version": 1,
        "report_id": "persistent_progression",
        "scenario_id": result.scenario_id,
        "time_basis": "cumulative_active_seconds",
        "excluded_event_kinds": [
            "fish_upgraded",
            "barbell_exercise_completed",
            "temporary_buff_applied",
        ],
        "profiles": profiles,
    }


def _persistent_event_row(
    event: Event,
    *,
    schedule: FishDailySessionSchedule,
    previous_active_time: int,
) -> dict[str, Any] | None:
    details = event.details
    if event.kind == "fish_throw_resolved":
        if details.get("is_persistent_progression") != "true":
            return None
        category = "best_hall_fish"
        metric_id = "fish_hall_cps"
        before = details.get("fish_hall_cps_before")
        after = details.get("fish_hall_cps_after")
    elif event.kind == "barbell_synthesized":
        category = "barbell"
        metric_id = "barbell_strength_per_second"
        before = details.get(
            "barbell_strength_per_second_before_synthesis"
        )
        after = details.get(
            "barbell_strength_per_second_after_synthesis"
        )
        if not _strictly_increases(before, after):
            return None
    elif event.kind == "fish_hall_upgraded":
        category = "fish_hall"
        metric_id = "fish_hall_level"
        before = details.get("fish_hall_upgrade_level_before")
        after = details.get("fish_hall_upgrade_level_after")
    elif event.kind == "strength_reborn":
        category = "strength_rebirth"
        metric_id = "fish_hall_output_multiplier"
        before = details.get("strength_rebirth_multiplier_before")
        after = details.get("strength_rebirth_multiplier_after")
    elif event.kind == "trash_man_reborn":
        category = "trash_man_rebirth"
        metric_id = "material_output_multiplier"
        before = details.get(
            "trash_man_rebirth_material_multiplier_before"
        )
        after = details.get(
            "trash_man_rebirth_material_multiplier_after"
        )
    elif event.kind in {"torpedo_purchased", "torpedo_upgraded"}:
        category = "torpedo"
        metric_id = "trash_luck"
        before = _first_detail(
            details,
            "trash_luck_before",
            "torpedo_trash_luck_before",
        )
        after = _first_detail(
            details,
            "trash_luck_after",
            "torpedo_trash_luck_after",
        )
    elif event.kind == "trash_man_realm_broken_through":
        category = "trash_man_realm"
        metric_id = "trash_man_realm_id"
        before = details.get("trash_man_realm_before")
        after = details.get("trash_man_realm_after")
    elif event.kind in {
        "fish_system_unlocked",
        "fish_ability_unlocked",
        "fish_strategy_unlocked",
    }:
        category = "permanent_unlock"
        metric_id = "unlock_state"
        before = details.get("metric_before", "0")
        after = details.get("metric_after", "1")
    elif event.kind in _PERSISTENT_EVENT_KINDS:
        return None
    else:
        return None

    before_value = optional_decimal(before)
    after_value = optional_decimal(after)
    if before_value is None or after_value is None:
        return None
    delta = after_value - before_value
    active_time = schedule.active_seconds_at(event.time_seconds)
    denominator = max(abs(before_value), Decimal(1))
    return {
        "scenario_id": event.scenario_id,
        "profile_id": event.profile_id,
        "wall_time_seconds": event.time_seconds,
        "active_time_seconds": active_time,
        "stage_id": (
            f"online_day_{event.time_seconds // SECONDS_PER_DAY + 1}"
        ),
        "source_event_kind": event.kind,
        "progression_category": category,
        "item_id": event.item_id,
        "is_persistent": True,
        "metric_id": metric_id,
        "metric_before": decimal_text(before_value),
        "metric_after": decimal_text(after_value),
        "metric_delta": decimal_text(delta),
        "relative_delta": decimal_text(delta / denominator),
        "gap_from_previous_progression_seconds": (
            active_time - previous_active_time
        ),
    }


def _behavior_summary(
    rows: list[dict[str, Any]],
    *,
    duration_seconds: int,
    active_duration_seconds: int,
    schedule: FishDailySessionSchedule,
) -> dict[str, Any]:
    event_times = [int(row["active_time_seconds"]) for row in rows]
    intervals = [
        event_times[index] - event_times[index - 1]
        for index in range(1, len(event_times))
    ]
    first_wait = event_times[0] if event_times else active_duration_seconds
    tail_gap = (
        active_duration_seconds - event_times[-1]
        if event_times
        else active_duration_seconds
    )
    counts = Counter(str(row["progression_category"]) for row in rows)
    dominant = max(counts.values(), default=0)
    earned_rows = [
        row
        for row in rows
        if not (
            row["source_event_kind"] == "trash_man_reborn"
            and row["metric_before"] == "1"
            and row["active_time_seconds"] <= 1
        )
    ]
    system_times = [
        int(row["active_time_seconds"])
        for row in rows
        if row["progression_category"] != "best_hall_fish"
    ]
    system_intervals = [
        system_times[index] - system_times[index - 1]
        for index in range(1, len(system_times))
    ]
    complete_sessions = duration_seconds // SECONDS_PER_DAY
    if (
        duration_seconds % SECONDS_PER_DAY
        >= schedule.daily_online_seconds
    ):
        complete_sessions += 1
    session_event_days = {
        int(row["wall_time_seconds"]) // SECONDS_PER_DAY
        for row in rows
        if int(row["wall_time_seconds"]) < duration_seconds
    }
    system_event_days = {
        int(row["wall_time_seconds"]) // SECONDS_PER_DAY
        for row in rows
        if (
            row["progression_category"] != "best_hall_fish"
            and int(row["wall_time_seconds"]) < duration_seconds
        )
    }
    return {
        "wall_duration_seconds": duration_seconds,
        "active_duration_seconds": active_duration_seconds,
        "total_progression_count": len(rows),
        "earned_progression_count": len(earned_rows),
        "events_per_active_hour": decimal_text(
            Decimal(len(rows))
            * Decimal(3600)
            / Decimal(active_duration_seconds)
            if active_duration_seconds
            else Decimal(0)
        ),
        "first_progression_wait_seconds": first_wait,
        "tail_gap_seconds": tail_gap,
        "interval_p50_seconds": percentile(intervals, 0.50),
        "interval_p75_seconds": percentile(intervals, 0.75),
        "interval_p90_seconds": percentile(intervals, 0.90),
        "interval_p95_seconds": percentile(intervals, 0.95),
        "max_interval_seconds": max(intervals, default=0),
        "system_progression_count": len(system_times),
        "system_events_per_active_hour": decimal_text(
            Decimal(len(system_times))
            * Decimal(3600)
            / Decimal(active_duration_seconds)
            if active_duration_seconds
            else Decimal(0)
        ),
        "system_progression_interval_p90_seconds": percentile(
            system_intervals,
            0.90,
        ),
        "system_progression_max_interval_seconds": max(
            system_intervals,
            default=0,
        ),
        "system_progression_tail_gap_seconds": (
            active_duration_seconds - system_times[-1]
            if system_times
            else active_duration_seconds
        ),
        "complete_online_sessions": complete_sessions,
        "complete_online_sessions_without_progression": max(
            0,
            complete_sessions
            - len(
                {
                    day
                    for day in session_event_days
                    if day < complete_sessions
                }
            ),
        ),
        "complete_online_sessions_without_system_progression": max(
            0,
            complete_sessions
            - len(
                {
                    day
                    for day in system_event_days
                    if day < complete_sessions
                }
            ),
        ),
        "progression_category_counts": dict(sorted(counts.items())),
        "progression_category_diversity": len(counts),
        "dominant_category_share": decimal_text(
            Decimal(dominant) / Decimal(len(rows))
            if rows
            else Decimal(0)
        ),
    }


def _density_by_active_hour(
    rows: list[dict[str, Any]],
    active_duration_seconds: int,
) -> list[dict[str, Any]]:
    bucket_count = math.ceil(active_duration_seconds / 3600)
    buckets = [
        {
            "active_hour_index": index,
            "active_time_start_seconds": index * 3600,
            "active_time_end_seconds": min(
                (index + 1) * 3600,
                active_duration_seconds,
            ),
            "event_count": 0,
            "average_relative_delta": "0",
            "progression_category_counts": {},
        }
        for index in range(bucket_count)
    ]
    relative_totals = [Decimal(0) for _ in buckets]
    category_counts = [Counter() for _ in buckets]
    for row in rows:
        if not buckets:
            break
        index = min(
            int(row["active_time_seconds"]) // 3600,
            len(buckets) - 1,
        )
        buckets[index]["event_count"] += 1
        relative_totals[index] += abs(
            decimal_value(row["relative_delta"])
        )
        category_counts[index][str(row["progression_category"])] += 1
    for index, bucket in enumerate(buckets):
        count = int(bucket["event_count"])
        bucket["average_relative_delta"] = decimal_text(
            relative_totals[index] / Decimal(count)
            if count
            else Decimal(0)
        )
        bucket["progression_category_counts"] = dict(
            sorted(category_counts[index].items())
        )
    return buckets


def _strictly_increases(before: Any, after: Any) -> bool:
    before_value = optional_decimal(before)
    after_value = optional_decimal(after)
    return (
        before_value is not None
        and after_value is not None
        and after_value > before_value
    )


def _first_detail(
    details: dict[str, str],
    *keys: str,
) -> str | None:
    for key in keys:
        if key in details:
            return details[key]
    return None
