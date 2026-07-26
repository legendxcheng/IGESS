from __future__ import annotations

import json
from decimal import Decimal

from .behavior import (
    IDLE_BEHAVIOR_ID,
    BehaviorDecision,
    BehaviorRuntimeState,
    BehaviorScheduler,
)
from .checkpoint import SimulationCheckpoint
from .fish_barbell import FishBarbellDataAdapter
from .fish_behavior import (
    EXERCISE_BARBELL_BEHAVIOR_ID,
    FishBehaviorAdapter,
    MANUAL_THROW_BEHAVIOR_ID,
)
from .fish_behavior_simulation_support import (
    decision_details,
    display_state,
    fit_candidates_to_online_window,
    increment_counter,
    output_event_details,
    record_production_counters,
    timeline_row,
    validate_checkpoint,
)
from .fish_behavior_weights import ManualThrowRefillRule
from .fish_session import FishDailySessionSchedule
from .fish_data import FishDataSnapshot
from .fish_hall import FishHallDataAdapter
from .fish_production import (
    FishProductionRuntime,
    settle_fish_production,
)
from .fish_state import FishCheckpointCodec, PlayerState
from .fish_trash import FishTrashDataAdapter
from .fish_throw_data import (
    FishThrowDataAdapter,
    ProductionThrowConfig,
)
from .schema import EconomyModel, Event, SimulationResult
from .time_engine import TimeEngine


class FishBehaviorSimulator:
    """Event-driven Fish loop for weighted, duration-bearing player behavior."""

    def __init__(
        self,
        model: EconomyModel,
        data: FishDataSnapshot,
        *,
        model_digest: str,
        _mutate_state: bool = True,
    ) -> None:
        if type(_mutate_state) is not bool:
            raise TypeError("_mutate_state must be a bool")
        self.model = model
        self.data = data
        self.model_digest = model_digest
        self._mutate_state = _mutate_state
        raw_throw_config = model.engine_settings.get("active_throw")
        if raw_throw_config is None:
            raise ValueError(
                "Fish weighted behaviors require engine.active_throw settings"
            )
        self.throw_config = ProductionThrowConfig.from_mapping(
            raw_throw_config
        )
        self.throw_adapter = FishThrowDataAdapter(
            data,
            bonus_base_luck=self.throw_config.bonus_base_luck,
            max_bonus_layers=self.throw_config.max_bonus_layers,
        )
        self.hall_adapter = FishHallDataAdapter(data)
        self.trash_adapter = FishTrashDataAdapter(data)
        self.barbell_adapter = FishBarbellDataAdapter(data)
        self.manual_throw_refill_rule = (
            ManualThrowRefillRule.from_engine_settings(
                model.engine_settings
            )
        )
        self.adapter = FishBehaviorAdapter(
            throw_adapter=self.throw_adapter,
            hall_adapter=self.hall_adapter,
            trash_adapter=self.trash_adapter,
            barbell_adapter=self.barbell_adapter,
            throw_config=self.throw_config,
            manual_throw_refill_rule=self.manual_throw_refill_rule,
            _validate_state=not _mutate_state,
        )
        self.time_engine = TimeEngine(model.config.tick_seconds)

    def run_scenario(
        self,
        scenario_id: str,
        checkpoint: SimulationCheckpoint | None = None,
        *,
        until_seconds: int | None = None,
    ) -> tuple[SimulationResult, SimulationCheckpoint]:
        scenario = self.model.scenarios[scenario_id]
        compact_event_details = (
            "compact_event_details" in scenario.outputs
        )
        profile_id = scenario.profiles[0]
        profile = self.model.player_profiles[profile_id]
        behavior_profile = self.adapter.behavior_profile(profile)
        session_schedule = FishDailySessionSchedule.from_mapping(
            self.model.session_patterns[profile.session_pattern]
        )
        duration_seconds = int(scenario.duration_hours * 3600)

        if checkpoint is None:
            state = PlayerState.new(
                0,
                initial_torpedo_id=self.throw_adapter.initial_torpedo_id,
                initial_strength=Decimal(
                    str(self.throw_config.initial_strength)
                ),
                initial_trash_man_realm_id=(
                    self.trash_adapter.initial_realm_id
                ),
            )
            state.validate(self.hall_adapter.validation_context())
            start_time = 0
            root_random_seed = self.model.config.random_seed
            next_throw_id = 0
            event_counters: dict[str, int] = {}
            runtime = BehaviorRuntimeState()
            production_runtime = FishProductionRuntime()
        else:
            state = FishCheckpointCodec.decode_state(
                checkpoint,
                expected_model_digest=self.model_digest,
                context=self.hall_adapter.validation_context(),
            )
            state = self.trash_adapter.initialize_realm(state)
            if checkpoint.scenario_id != scenario_id:
                raise ValueError(
                    "checkpoint scenario does not match the requested scenario"
                )
            if checkpoint.profile_id != profile_id:
                raise ValueError(
                    "checkpoint profile does not match the requested profile"
                )
            if not checkpoint.behavior_state:
                raise ValueError(
                    "weighted behavior checkpoint is missing behavior_state"
                )
            runtime = BehaviorRuntimeState.from_dict(
                checkpoint.behavior_state
            )
            production_runtime = FishProductionRuntime.from_dict(
                checkpoint.engine_runtime_state
            )
            start_time = checkpoint.simulated_time_seconds
            root_random_seed = checkpoint.root_random_seed
            next_throw_id = checkpoint.next_throw_id
            event_counters = dict(checkpoint.event_counters)
            validate_checkpoint(
                state,
                runtime,
                profile_id=profile_id,
                simulated_time_seconds=start_time,
                next_throw_id=next_throw_id,
                event_counters=event_counters,
                barbell_adapter=self.barbell_adapter,
            )

        if start_time > duration_seconds:
            raise ValueError("checkpoint time exceeds the scenario duration")
        target_time = (
            duration_seconds if until_seconds is None else until_seconds
        )
        if (
            type(target_time) is not int
            or not start_time <= target_time <= duration_seconds
        ):
            raise ValueError(
                "until_seconds must be an integer within the remaining scenario"
            )

        scheduler = BehaviorScheduler(root_random_seed)
        timeline = [
            timeline_row(
                scenario_id,
                profile_id,
                start_time,
                display_state(
                    state,
                    start_time,
                    production_runtime,
                    online=session_schedule.is_online(start_time),
                    active_behavior_id=(
                        None
                        if runtime.active is None
                        else runtime.active.behavior_id
                    ),
                    hall_adapter=self.hall_adapter,
                    trash_adapter=self.trash_adapter,
                    barbell_adapter=self.barbell_adapter,
                ),
                model=self.model,
                hall_adapter=self.hall_adapter,
            )
        ]
        events = [
            Event(
                scenario_id=scenario_id,
                profile_id=profile_id,
                time_seconds=start_time,
                kind="fish_engine_ready",
                item_id="weighted_behavior_loop",
                details={
                    "engine_id": "fish",
                    "model_digest": self.model_digest,
                    "behavior_scheduler": "weighted_duration_v1",
                    "manual_throw_refill_condition": (
                        "fish_hall_not_full_or_trash_processing_empty"
                    ),
                    "manual_throw_refill_weight_multiplier": (
                        self.manual_throw_refill_rule.weight_multiplier
                        .to_decimal_string()
                    ),
                    "daily_online_seconds": str(
                        session_schedule.daily_online_seconds
                    ),
                    "barbell_strength_source": (
                        EXERCISE_BARBELL_BEHAVIOR_ID
                    ),
                    "offline_barbell_strength": "0",
                    "production_data": str(
                        self.data.production_data
                    ).lower(),
                    "table_count": str(len(self.data.files)),
                },
            )
        ]
        record_times = sorted(
            set(
                self.time_engine.recurring_event_times(
                    start_time,
                    target_time,
                    scenario.record_interval_seconds,
                )
            )
            | ({target_time} if target_time > start_time else set())
        )
        record_index = 0
        current_time = start_time

        while current_time < target_time:
            online = session_schedule.is_online(current_time)
            next_session_transition = (
                session_schedule.next_transition_after(current_time)
            )
            next_record = (
                record_times[record_index]
                if record_index < len(record_times)
                else target_time
            )

            if not online:
                if runtime.active is not None:
                    raise ValueError(
                        "offline checkpoint cannot contain an active behavior"
                    )
                boundary = min(
                    target_time,
                    next_record,
                    (
                        next_session_transition
                        if next_session_transition is not None
                        else target_time
                    ),
                )
                reached_session_transition = (
                    next_session_transition is not None
                    and boundary == next_session_transition
                )
                if reached_session_transition:
                    settlement = settle_fish_production(
                        state,
                        boundary,
                        hall_adapter=self.hall_adapter,
                        trash_adapter=self.trash_adapter,
                        barbell_adapter=self.barbell_adapter,
                        runtime=production_runtime,
                        online=False,
                    )
                    state = settlement.state
                    production_runtime = settlement.runtime
                    record_production_counters(
                        event_counters,
                        settlement.elapsed_seconds,
                        settlement.trash_processing.completed_count,
                    )
                    increment_counter(
                        event_counters,
                        "fish_offline_settled",
                    )
                    events.append(
                        Event(
                            scenario_id=scenario_id,
                            profile_id=profile_id,
                            time_seconds=boundary,
                            kind="fish_offline_settled",
                            item_id="session:offline",
                            details=settlement.event_details(),
                        )
                    )
                    events.append(
                        Event(
                            scenario_id=scenario_id,
                            profile_id=profile_id,
                            time_seconds=boundary,
                            kind="fish_session_online_started",
                            item_id="session:online",
                            details={
                                "daily_online_seconds": str(
                                    session_schedule.daily_online_seconds
                                )
                            },
                        )
                    )

                current_time = boundary
                if (
                    record_index < len(record_times)
                    and record_times[record_index] == boundary
                ):
                    timeline.append(
                        timeline_row(
                            scenario_id,
                            profile_id,
                            boundary,
                            display_state(
                                state,
                                boundary,
                                production_runtime,
                                online=False,
                                active_behavior_id=None,
                                hall_adapter=self.hall_adapter,
                                trash_adapter=self.trash_adapter,
                                barbell_adapter=self.barbell_adapter,
                            ),
                            model=self.model,
                            hall_adapter=self.hall_adapter,
                        )
                    )
                    record_index += 1
                continue

            if runtime.active is None:
                remaining_online_seconds = (
                    session_schedule.online_seconds_remaining(current_time)
                )
                raw_candidates = self.adapter.candidates(state, profile)
                candidates = (
                    raw_candidates
                    if next_session_transition is None
                    else fit_candidates_to_online_window(
                        raw_candidates,
                        remaining_online_seconds,
                    )
                )
                if candidates:
                    effective_behavior_profile = (
                        self.adapter.effective_behavior_profile(
                            state,
                            behavior_profile,
                        )
                    )
                    decision = scheduler.decide(
                        candidates,
                        effective_behavior_profile,
                        sequence_id=runtime.next_sequence_id,
                        started_at_seconds=current_time,
                    )
                else:
                    decision = BehaviorDecision(
                        sequence_id=runtime.next_sequence_id,
                        profile_id=profile_id,
                        behavior_id=IDLE_BEHAVIOR_ID,
                        target_id=None,
                        duration_seconds=remaining_online_seconds,
                        started_at_seconds=current_time,
                        completes_at_seconds=(
                            current_time + remaining_online_seconds
                        ),
                    )
                runtime = BehaviorRuntimeState(
                    next_sequence_id=runtime.next_sequence_id + 1,
                    active=decision,
                )
                increment_counter(
                    event_counters,
                    "behavior_decisions_started",
                )
                events.append(
                    Event(
                        scenario_id=scenario_id,
                        profile_id=profile_id,
                        time_seconds=current_time,
                        kind="fish_behavior_started",
                        item_id=f"behavior:{decision.sequence_id}",
                        details=decision_details(decision),
                    )
                )

            active = runtime.active
            if active is None:
                raise AssertionError("behavior scheduler did not create an action")
            boundary = min(
                active.completes_at_seconds,
                next_record,
                target_time,
                (
                    next_session_transition
                    if next_session_transition is not None
                    else target_time
                ),
            )
            completed = active.completes_at_seconds == boundary
            reached_session_transition = (
                next_session_transition is not None
                and boundary == next_session_transition
            )
            if reached_session_transition and not completed:
                raise ValueError(
                    "active behavior crosses the daily offline boundary"
                )
            if completed:
                completion = self.adapter.complete(
                    state,
                    active,
                    root_random_seed=root_random_seed,
                    next_throw_id=next_throw_id,
                    production_runtime=production_runtime,
                    _mutate=self._mutate_state,
                )
                state = completion.state
                production_runtime = completion.production_runtime
                next_throw_id = completion.next_throw_id
                runtime = BehaviorRuntimeState(
                    next_sequence_id=runtime.next_sequence_id,
                )
                increment_counter(event_counters, "behavior_completed")
                increment_counter(
                    event_counters,
                    f"{active.behavior_id}_completed",
                )
                record_production_counters(
                    event_counters,
                    int(
                        completion.details[
                            "fish_hall_settlement_elapsed_seconds"
                        ]
                    ),
                    int(completion.details["trash_completed_count"]),
                )
                _append_breakthrough_completion_events(
                    events,
                    event_counters,
                    scenario_id=scenario_id,
                    profile_id=profile_id,
                    settlement_details=completion.details,
                )
                events.append(
                    Event(
                        scenario_id=scenario_id,
                        profile_id=profile_id,
                        time_seconds=boundary,
                        kind=completion.event_kind,
                        item_id=completion.item_id,
                        details=output_event_details(
                            completion.event_kind,
                            completion.details,
                            compact=compact_event_details,
                        ),
                    )
                )
                if reached_session_transition:
                    events.append(
                        Event(
                            scenario_id=scenario_id,
                            profile_id=profile_id,
                            time_seconds=boundary,
                            kind="fish_session_offline_started",
                            item_id="session:offline",
                            details={
                                "daily_online_seconds": str(
                                    session_schedule.daily_online_seconds
                                ),
                                "barbell_strength_offline_efficiency": "0",
                            },
                        )
                    )

            current_time = boundary
            if (
                record_index < len(record_times)
                and record_times[record_index] == boundary
            ):
                timeline.append(
                    timeline_row(
                        scenario_id,
                        profile_id,
                        boundary,
                        display_state(
                            state,
                            boundary,
                            production_runtime,
                            online=session_schedule.is_online(boundary),
                            active_behavior_id=(
                                None
                                if runtime.active is None
                                else runtime.active.behavior_id
                            ),
                            hall_adapter=self.hall_adapter,
                            trash_adapter=self.trash_adapter,
                            barbell_adapter=self.barbell_adapter,
                        ),
                        model=self.model,
                        hall_adapter=self.hall_adapter,
                    )
                )
                record_index += 1

        # Intermediate checkpoints do not split a behavior's passive settlement.
        # A completed scenario still persists all production earned by its end.
        if (
            target_time == duration_seconds
            and state.production.last_settled_at < target_time
        ):
            final_settlement = settle_fish_production(
                state,
                target_time,
                hall_adapter=self.hall_adapter,
                trash_adapter=self.trash_adapter,
                barbell_adapter=self.barbell_adapter,
                runtime=production_runtime,
                online=session_schedule.is_online(target_time),
                barbell_training_active=(
                    session_schedule.is_online(target_time)
                    and runtime.active is not None
                    and runtime.active.behavior_id
                    == EXERCISE_BARBELL_BEHAVIOR_ID
                ),
            )
            state = final_settlement.state
            production_runtime = final_settlement.runtime
            if final_settlement.elapsed_seconds > 0:
                completed_trash = (
                    final_settlement.trash_processing.completed_count
                )
                record_production_counters(
                    event_counters,
                    final_settlement.elapsed_seconds,
                    completed_trash,
                )
                if not final_settlement.online:
                    increment_counter(
                        event_counters,
                        "fish_offline_settled",
                    )
                final_settlement_details = final_settlement.event_details()
                _append_breakthrough_completion_events(
                    events,
                    event_counters,
                    scenario_id=scenario_id,
                    profile_id=profile_id,
                    settlement_details=final_settlement_details,
                )
                events.append(
                    Event(
                        scenario_id=scenario_id,
                        profile_id=profile_id,
                        time_seconds=target_time,
                        kind=(
                            "fish_hall_settled"
                            if final_settlement.online
                            else "fish_offline_settled"
                        ),
                        item_id=(
                            "fish_hall:scenario_end"
                            if final_settlement.online
                            else "session:scenario_end"
                        ),
                        details=final_settlement_details,
                    )
                )

        result = SimulationResult(
            scenario_id=scenario_id,
            timeline=timeline,
            events=events,
        )
        final_checkpoint = FishCheckpointCodec.new(
            state,
            model_digest=self.model_digest,
            scenario_id=scenario_id,
            profile_id=profile_id,
            root_random_seed=root_random_seed,
            simulated_time_seconds=target_time,
            next_throw_id=next_throw_id,
            event_counters=event_counters,
            behavior_state=runtime.to_dict(),
            engine_runtime_state=production_runtime.to_dict(),
            context=self.hall_adapter.validation_context(),
        )
        return result, final_checkpoint


def _append_breakthrough_completion_events(
    events: list[Event],
    event_counters: dict[str, int],
    *,
    scenario_id: str,
    profile_id: str,
    settlement_details: dict[str, str],
) -> None:
    payload = settlement_details.get(
        "trash_man_breakthrough_completions",
        "[]",
    )
    try:
        completions = json.loads(payload)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "invalid trash-man breakthrough completion trace"
        ) from exc
    if not isinstance(completions, list):
        raise ValueError(
            "trash-man breakthrough completion trace must be a list"
        )
    settlement_from = int(
        settlement_details["fish_production_settlement_from_seconds"]
    )
    for completion in completions:
        if not isinstance(completion, dict):
            raise ValueError(
                "trash-man breakthrough completion must be an object"
            )
        from_realm = int(completion["from_realm_id"])
        to_realm = int(completion["to_realm_id"])
        at_elapsed = int(completion["at_elapsed_seconds"])
        required_seconds = int(completion["required_seconds"])
        price = str(completion["price"])
        increment_counter(
            event_counters,
            "trash_man_realm_broken_through",
        )
        events.append(
            Event(
                scenario_id=scenario_id,
                profile_id=profile_id,
                time_seconds=settlement_from + at_elapsed,
                kind="trash_man_realm_broken_through",
                item_id=f"trash_man_realm:{to_realm}",
                details={
                    "trash_man_realm_before": str(from_realm),
                    "trash_man_realm_after": str(to_realm),
                    "trash_man_highest_realm_before": str(from_realm),
                    "trash_man_highest_realm_after": str(to_realm),
                    "trash_man_breakthrough_price": price,
                    "trash_man_breakthrough_price_source": (
                        "tbtrashmanrealm"
                        f"[id={from_realm}].moneyRequireToNextRealm"
                    ),
                    "trash_man_breakthrough_required_online_seconds": str(
                        required_seconds
                    ),
                    "trash_man_breakthrough_duration_source": (
                        "tbtrashmanrealm"
                        f"[id={from_realm}]"
                        ".cultivationSecondsToNextRealm"
                    ),
                    "trash_man_breakthrough_online_only": "true",
                    "trash_man_breakthrough_processing_continued": "true",
                    "is_persistent_progression": "true",
                },
            )
        )
