from __future__ import annotations

from decimal import Decimal
from typing import Any

from .fish_data import FishDataSnapshot
from .fish_progression_common import (
    decimal_text,
    decimal_value,
    duration_seconds,
    optional_decimal,
    profile_events,
    profile_schedule,
)
from .fish_session import FishDailySessionSchedule
from .fish_throw import (
    map_strength_to_fish_luck,
    map_torpedo_power_to_trash_luck,
)
from .fish_throw_data import FishThrowDataAdapter, ProductionThrowConfig
from .schema import EconomyModel, Event, SimulationResult


DEFAULT_ACTIVE_SAMPLE_SECONDS = 5 * 60
_CORE_MARKER_KINDS = frozenset(
    {
        "barbell_synthesized",
        "fish_hall_upgraded",
        "strength_reborn",
        "trash_man_reborn",
        "trash_man_realm_broken_through",
        "torpedo_purchased",
        "torpedo_upgraded",
    }
)


def build_core_strength_progression(
    result: SimulationResult,
    model: EconomyModel,
    data: FishDataSnapshot,
    *,
    sample_interval_active_seconds: int = DEFAULT_ACTIVE_SAMPLE_SECONDS,
) -> dict[str, Any]:
    scenario = model.scenarios[result.scenario_id]
    wall_duration = duration_seconds(scenario.duration_hours)
    throw_config = ProductionThrowConfig.from_mapping(
        model.engine_settings["active_throw"]
    )
    throw_adapter = FishThrowDataAdapter(
        data,
        bonus_base_luck=throw_config.bonus_base_luck,
        max_bonus_layers=throw_config.max_bonus_layers,
    )
    profiles: dict[str, Any] = {}
    for profile_id in scenario.profiles:
        schedule = profile_schedule(model, profile_id)
        profiles[profile_id] = _core_profile(
            result.scenario_id,
            profile_id,
            profile_events(result.events, profile_id),
            duration_seconds=wall_duration,
            schedule=schedule,
            sample_interval_active_seconds=sample_interval_active_seconds,
            throw_config=throw_config,
            throw_adapter=throw_adapter,
        )
    return {
        "schema_version": 1,
        "report_id": "core_strength_progression",
        "scenario_id": result.scenario_id,
        "time_basis": "cumulative_active_seconds",
        "sample_interval_active_seconds": sample_interval_active_seconds,
        "profiles": profiles,
    }


def _core_profile(
    scenario_id: str,
    profile_id: str,
    events: list[Event],
    *,
    duration_seconds: int,
    schedule: FishDailySessionSchedule,
    sample_interval_active_seconds: int,
    throw_config: ProductionThrowConfig,
    throw_adapter: FishThrowDataAdapter,
) -> dict[str, Any]:
    active_duration = schedule.active_seconds_at(duration_seconds)
    points: dict[int, set[str]] = {}
    for active_time in range(
        0,
        active_duration + 1,
        sample_interval_active_seconds,
    ):
        points.setdefault(
            schedule.wall_time_for_active_seconds(active_time),
            set(),
        ).add("periodic")
    points.setdefault(
        schedule.wall_time_for_active_seconds(active_duration),
        set(),
    ).add("periodic")
    for event in events:
        if event.kind in _CORE_MARKER_KINDS:
            points.setdefault(event.time_seconds, set()).add(event.kind)

    initial_strength = decimal_value(throw_config.initial_strength)
    strength = initial_strength
    strength_peak = initial_strength
    fish_luck = _fish_luck(
        throw_adapter,
        strength,
        throw_config.regular_luck_multiplier,
    )
    fish_luck_peak = fish_luck
    trash_luck = _initial_trash_luck(
        throw_adapter,
        throw_config.regular_luck_multiplier,
    )
    trash_luck_peak = trash_luck
    strength_rebirth_count = 0
    trash_man_rebirth_count = 0
    last_fish_growth_active = 0
    last_trash_growth_active = 0
    fish_growth_times = [0]
    trash_growth_times = [0]
    event_index = 0
    rows: list[dict[str, Any]] = []
    previous_row_strength = strength
    previous_row_fish_luck = fish_luck
    previous_row_trash_luck = trash_luck
    previous_row_active = 0

    for wall_time in sorted(points):
        while (
            event_index < len(events)
            and events[event_index].time_seconds <= wall_time
        ):
            event = events[event_index]
            active_time = schedule.active_seconds_at(event.time_seconds)
            before_fish_luck = fish_luck
            before_trash_luck = trash_luck
            added = optional_decimal(
                event.details.get("barbell_strength_added")
            )
            if added is not None:
                strength += added
            settled_strength = optional_decimal(
                event.details.get("strength_after_settlement")
            )
            if settled_strength is not None:
                strength = settled_strength
            elif event.kind == "fish_throw_resolved":
                locked_strength = optional_decimal(
                    event.details.get("input_strength")
                )
                if locked_strength is not None:
                    strength = locked_strength
            strength_peak = max(strength_peak, strength)
            fish_luck = _fish_luck(
                throw_adapter,
                strength,
                throw_config.regular_luck_multiplier,
            )
            fish_luck_peak = max(fish_luck_peak, fish_luck)
            if fish_luck > before_fish_luck:
                last_fish_growth_active = active_time
                _append_distinct(fish_growth_times, active_time)

            if event.kind == "strength_reborn":
                before_reset = optional_decimal(
                    event.details.get("strength_before_rebirth")
                )
                if before_reset is not None:
                    strength_peak = max(strength_peak, before_reset)
                    fish_luck_peak = max(
                        fish_luck_peak,
                        _fish_luck(
                            throw_adapter,
                            before_reset,
                            throw_config.regular_luck_multiplier,
                        ),
                    )
                strength = decimal_value(
                    event.details.get("strength_after_rebirth", "0")
                )
                fish_luck = _fish_luck(
                    throw_adapter,
                    strength,
                    throw_config.regular_luck_multiplier,
                )
                strength_rebirth_count = int(
                    event.details.get(
                        "strength_rebirth_completed_count_after",
                        strength_rebirth_count + 1,
                    )
                )
            if event.kind == "trash_man_reborn":
                trash_man_rebirth_count = int(
                    event.details.get(
                        "trash_man_rebirth_completed_count_after",
                        trash_man_rebirth_count + 1,
                    )
                )
            event_trash_luck = optional_decimal(
                event.details.get("trash_luck")
            )
            if event_trash_luck is not None:
                trash_luck = event_trash_luck
                trash_luck_peak = max(trash_luck_peak, trash_luck)
            if trash_luck > before_trash_luck:
                last_trash_growth_active = active_time
                _append_distinct(trash_growth_times, active_time)
            event_index += 1

        active_time = schedule.active_seconds_at(wall_time)
        elapsed_active = active_time - previous_row_active
        markers = sorted(points[wall_time] - {"periodic"})
        sample_kind = (
            "periodic+milestone"
            if markers and "periodic" in points[wall_time]
            else "milestone"
            if markers
            else "periodic"
        )
        rows.append(
            {
                "scenario_id": scenario_id,
                "profile_id": profile_id,
                "wall_time_seconds": wall_time,
                "active_time_seconds": active_time,
                "sample_kind": sample_kind,
                "strength_current": decimal_text(strength),
                "strength_peak": decimal_text(strength_peak),
                "strength_delta": decimal_text(
                    strength - previous_row_strength
                ),
                "fish_luck_current": decimal_text(fish_luck),
                "fish_luck_peak": decimal_text(fish_luck_peak),
                "fish_luck_delta": decimal_text(
                    fish_luck - previous_row_fish_luck
                ),
                "trash_luck_current": decimal_text(trash_luck),
                "trash_luck_peak": decimal_text(trash_luck_peak),
                "trash_luck_delta": decimal_text(
                    trash_luck - previous_row_trash_luck
                ),
                "fish_luck_delta_per_active_hour": _rate_per_hour(
                    fish_luck - previous_row_fish_luck,
                    elapsed_active,
                ),
                "trash_luck_delta_per_active_hour": _rate_per_hour(
                    trash_luck - previous_row_trash_luck,
                    elapsed_active,
                ),
                "time_since_fish_luck_growth_seconds": max(
                    0,
                    active_time - last_fish_growth_active,
                ),
                "time_since_trash_luck_growth_seconds": max(
                    0,
                    active_time - last_trash_growth_active,
                ),
                "strength_rebirth_count": strength_rebirth_count,
                "trash_man_rebirth_count": trash_man_rebirth_count,
                "reset_or_milestone_marker": ",".join(markers),
            }
        )
        previous_row_strength = strength
        previous_row_fish_luck = fish_luck
        previous_row_trash_luck = trash_luck
        previous_row_active = active_time

    return {
        "summary": {
            "wall_duration_seconds": duration_seconds,
            "active_duration_seconds": active_duration,
            "sample_count": len(rows),
            "strength_initial": decimal_text(initial_strength),
            "strength_final": decimal_text(strength),
            "strength_peak": decimal_text(strength_peak),
            "fish_luck_initial": decimal_text(
                rows[0]["fish_luck_current"]
            ),
            "fish_luck_final": decimal_text(fish_luck),
            "fish_luck_peak": decimal_text(fish_luck_peak),
            "fish_luck_net_delta": decimal_text(
                fish_luck
                - decimal_value(rows[0]["fish_luck_current"])
            ),
            "trash_luck_initial": decimal_text(
                rows[0]["trash_luck_current"]
            ),
            "trash_luck_final": decimal_text(trash_luck),
            "trash_luck_peak": decimal_text(trash_luck_peak),
            "trash_luck_net_delta": decimal_text(
                trash_luck
                - decimal_value(rows[0]["trash_luck_current"])
            ),
            "longest_fish_luck_stagnation_seconds": _longest_gap(
                fish_growth_times,
                active_duration,
            ),
            "longest_trash_luck_stagnation_seconds": _longest_gap(
                trash_growth_times,
                active_duration,
            ),
            "strength_rebirth_count": strength_rebirth_count,
            "trash_man_rebirth_count": trash_man_rebirth_count,
        },
        "rows": rows,
    }


def _initial_trash_luck(
    adapter: FishThrowDataAdapter,
    multiplier: float,
) -> Decimal:
    torpedo = adapter.torpedo(adapter.initial_torpedo_id)
    return decimal_value(
        map_torpedo_power_to_trash_luck(
            torpedo.power,
            adapter.trash_luck_pools,
            multiplier,
        ).trash_luck
    )


def _fish_luck(
    adapter: FishThrowDataAdapter,
    strength: Decimal,
    multiplier: float,
) -> Decimal:
    max_strength = decimal_value(
        adapter.rules.strength_luck_pools[-1].strength_upper_bound
    )
    clamped_strength = min(
        max(strength, Decimal(1)),
        max_strength,
    )
    return decimal_value(
        map_strength_to_fish_luck(
            float(clamped_strength),
            adapter.rules.strength_luck_pools,
            multiplier,
        ).fish_luck
    )


def _rate_per_hour(delta: Decimal, elapsed_active: int) -> str:
    if elapsed_active <= 0:
        return "0"
    return decimal_text(
        delta * Decimal(3600) / Decimal(elapsed_active)
    )


def _longest_gap(times: list[int], active_duration: int) -> int:
    normalized = sorted(set([0, *times, active_duration]))
    return max(
        (
            normalized[index] - normalized[index - 1]
            for index in range(1, len(normalized))
        ),
        default=0,
    )


def _append_distinct(values: list[int], value: int) -> None:
    if values[-1] != value:
        values.append(value)
