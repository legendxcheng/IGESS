from __future__ import annotations

from decimal import Decimal

from .behavior import (
    IDLE_BEHAVIOR_ID,
    BehaviorCandidate,
    BehaviorDecision,
    BehaviorRuntimeState,
    BehaviorScheduler,
    FixedDuration,
    UniformIntDuration,
)
from .checkpoint import SimulationCheckpoint
from .fish_barbell import FishBarbellDataAdapter
from .fish_behavior import (
    EXERCISE_BARBELL_BEHAVIOR_ID,
    FISH_BEHAVIOR_IDS,
    FishBehaviorAdapter,
    MANUAL_THROW_BEHAVIOR_ID,
    STRENGTH_REBIRTH_BEHAVIOR_ID,
    SYNTHESIZE_BARBELL_BEHAVIOR_ID,
    TRASH_MAN_REBIRTH_BEHAVIOR_ID,
    UPGRADE_FISH_BEHAVIOR_ID,
    UPGRADE_FISH_HALL_BEHAVIOR_ID,
)
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
from .schema import EconomyModel, Event, SimulationResult, TimelineRow
from .time_engine import TimeEngine


class FishBehaviorSimulator:
    """Event-driven Fish loop for weighted, duration-bearing player behavior."""

    def __init__(
        self,
        model: EconomyModel,
        data: FishDataSnapshot,
        *,
        model_digest: str,
    ) -> None:
        self.model = model
        self.data = data
        self.model_digest = model_digest
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
        self.adapter = FishBehaviorAdapter(
            throw_adapter=self.throw_adapter,
            hall_adapter=self.hall_adapter,
            trash_adapter=self.trash_adapter,
            barbell_adapter=self.barbell_adapter,
            throw_config=self.throw_config,
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
            self._validate_checkpoint(
                state,
                runtime,
                profile_id=profile_id,
                simulated_time_seconds=start_time,
                next_throw_id=next_throw_id,
                event_counters=event_counters,
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
            self._timeline_row(
                scenario_id,
                profile_id,
                start_time,
                self._display_state(
                    state,
                    start_time,
                    production_runtime,
                    online=session_schedule.is_online(start_time),
                    active_behavior_id=(
                        None
                        if runtime.active is None
                        else runtime.active.behavior_id
                    ),
                ),
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
                    self._record_production_counters(
                        event_counters,
                        settlement.elapsed_seconds,
                        settlement.trash_processing.completed_count,
                    )
                    self._increment(
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
                        self._timeline_row(
                            scenario_id,
                            profile_id,
                            boundary,
                            self._display_state(
                                state,
                                boundary,
                                production_runtime,
                                online=False,
                            ),
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
                    else self._fit_candidates_to_online_window(
                        raw_candidates,
                        remaining_online_seconds,
                    )
                )
                if candidates:
                    decision = scheduler.decide(
                        candidates,
                        behavior_profile,
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
                self._increment(
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
                        details=self._decision_details(decision),
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
                )
                state = completion.state
                production_runtime = completion.production_runtime
                next_throw_id = completion.next_throw_id
                runtime = BehaviorRuntimeState(
                    next_sequence_id=runtime.next_sequence_id,
                )
                self._increment(event_counters, "behavior_completed")
                self._increment(
                    event_counters,
                    f"{active.behavior_id}_completed",
                )
                self._record_production_counters(
                    event_counters,
                    int(
                        completion.details[
                            "fish_hall_settlement_elapsed_seconds"
                        ]
                    ),
                    int(completion.details["trash_completed_count"]),
                )
                events.append(
                    Event(
                        scenario_id=scenario_id,
                        profile_id=profile_id,
                        time_seconds=boundary,
                        kind=completion.event_kind,
                        item_id=completion.item_id,
                        details=completion.details,
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
                    self._timeline_row(
                        scenario_id,
                        profile_id,
                        boundary,
                        self._display_state(
                            state,
                            boundary,
                            production_runtime,
                            online=session_schedule.is_online(boundary),
                            active_behavior_id=(
                                None
                                if runtime.active is None
                                else runtime.active.behavior_id
                            ),
                        ),
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
                self._record_production_counters(
                    event_counters,
                    final_settlement.elapsed_seconds,
                    completed_trash,
                )
                if not final_settlement.online:
                    self._increment(
                        event_counters,
                        "fish_offline_settled",
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
                        details=final_settlement.event_details(),
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

    def _display_state(
        self,
        state: PlayerState,
        time_seconds: int,
        production_runtime: FishProductionRuntime,
        *,
        online: bool,
        active_behavior_id: str | None = None,
    ) -> PlayerState:
        if state.production.last_settled_at >= time_seconds:
            return state
        return settle_fish_production(
            state,
            time_seconds,
            hall_adapter=self.hall_adapter,
            trash_adapter=self.trash_adapter,
            barbell_adapter=self.barbell_adapter,
            runtime=production_runtime,
            online=online,
            barbell_training_active=(
                online
                and active_behavior_id == EXERCISE_BARBELL_BEHAVIOR_ID
            ),
        ).state

    @staticmethod
    def _fit_candidates_to_online_window(
        candidates: tuple[BehaviorCandidate, ...],
        remaining_seconds: int,
    ) -> tuple[BehaviorCandidate, ...]:
        """Keep actions that can finish before the strict logout boundary."""

        if type(remaining_seconds) is not int or remaining_seconds <= 0:
            return ()
        fitted: list[BehaviorCandidate] = []
        for candidate in candidates:
            if not candidate.available:
                continue
            duration = candidate.duration
            if isinstance(duration, FixedDuration):
                if duration.seconds > remaining_seconds:
                    continue
                fitted_duration = duration
            elif isinstance(duration, UniformIntDuration):
                if duration.min_seconds > remaining_seconds:
                    continue
                fitted_duration = UniformIntDuration(
                    duration.min_seconds,
                    min(duration.max_seconds, remaining_seconds),
                )
            else:
                raise TypeError("unsupported behavior duration")
            fitted.append(
                BehaviorCandidate(
                    behavior_id=candidate.behavior_id,
                    duration=fitted_duration,
                    available=candidate.available,
                    targets=candidate.targets,
                )
            )
        return tuple(fitted)

    @staticmethod
    def _record_production_counters(
        event_counters: dict[str, int],
        elapsed_seconds: int,
        completed_trash: int,
    ) -> None:
        if elapsed_seconds <= 0:
            return
        event_counters["fish_hall_settled"] = (
            event_counters.get("fish_hall_settled", 0) + 1
        )
        if completed_trash > 0:
            event_counters["trash_processed"] = (
                event_counters.get("trash_processed", 0)
                + completed_trash
            )

    def _timeline_row(
        self,
        scenario_id: str,
        profile_id: str,
        time_seconds: int,
        state: PlayerState,
    ) -> TimelineRow:
        hall = self.hall_adapter.snapshot(state)
        return TimelineRow(
            scenario_id=scenario_id,
            profile_id=profile_id,
            time_seconds=time_seconds,
            resources={
                "material": state.wallet.material.to_decimal_string(),
                "money": state.wallet.money.to_decimal_string(),
                "strength": state.wallet.strength.to_decimal_string(),
            },
            generators_owned={
                generator_id: 0 for generator_id in self.model.generators
            },
            upgrades_purchased=[],
            total_cps=hall.total_income_per_second.to_decimal_string(),
        )

    def _validate_checkpoint(
        self,
        state: PlayerState,
        runtime: BehaviorRuntimeState,
        *,
        profile_id: str,
        simulated_time_seconds: int,
        next_throw_id: int,
        event_counters: dict[str, int],
    ) -> None:
        active = runtime.active
        completed = event_counters.get("behavior_completed", 0)
        started = event_counters.get("behavior_decisions_started", 0)
        manual_throws = event_counters.get(
            f"{MANUAL_THROW_BEHAVIOR_ID}_completed",
            0,
        )
        upgrades = event_counters.get(
            f"{UPGRADE_FISH_BEHAVIOR_ID}_completed",
            0,
        )
        hall_upgrades = event_counters.get(
            f"{UPGRADE_FISH_HALL_BEHAVIOR_ID}_completed",
            0,
        )
        barbell_syntheses = event_counters.get(
            f"{SYNTHESIZE_BARBELL_BEHAVIOR_ID}_completed",
            0,
        )
        barbell_exercises = event_counters.get(
            f"{EXERCISE_BARBELL_BEHAVIOR_ID}_completed",
            0,
        )
        strength_rebirths = event_counters.get(
            f"{STRENGTH_REBIRTH_BEHAVIOR_ID}_completed",
            0,
        )
        trash_man_rebirths = event_counters.get(
            f"{TRASH_MAN_REBIRTH_BEHAVIOR_ID}_completed",
            0,
        )
        idle = event_counters.get("idle_completed", 0)
        counters = (
            completed,
            started,
            manual_throws,
            upgrades,
            hall_upgrades,
            barbell_syntheses,
            barbell_exercises,
            strength_rebirths,
            trash_man_rebirths,
            idle,
        )
        if any(type(value) is not int or value < 0 for value in counters):
            raise ValueError(
                "weighted behavior checkpoint has invalid event counters"
            )
        trash_count = sum(
            stock.count for stock in state.trash_man.processing.stocks
        )
        trash_processed = event_counters.get("trash_processed", 0)
        if type(trash_processed) is not int or trash_processed < 0:
            raise ValueError(
                "weighted behavior checkpoint has invalid trash counter"
            )
        owned_barbell_count = sum(
            item.count for item in state.barbell.owned
        )
        if (
            completed
            != (
                manual_throws
                + upgrades
                + hall_upgrades
                + barbell_syntheses
                + barbell_exercises
                + strength_rebirths
                + trash_man_rebirths
                + idle
            )
            or started != completed + int(active is not None)
            or runtime.next_sequence_id != started
            or next_throw_id != manual_throws
            or state.statistics.total_throws != manual_throws
            or state.statistics.total_fish_caught != manual_throws
            or len(state.fish.items) != manual_throws
            or trash_count + trash_processed != manual_throws
            or state.fish_hall.upgrade_level != hall_upgrades
            or owned_barbell_count < barbell_syntheses
            or state.rebirth.strength_completed_count
            != strength_rebirths
            or state.rebirth.trash_man_completed_count
            != trash_man_rebirths
            or state.barbell.equipped_id
            != self.barbell_adapter.best_owned_id(state)
            or state.production.last_settled_at > simulated_time_seconds
        ):
            raise ValueError(
                "weighted behavior checkpoint does not match committed state"
            )
        if active is not None and (
            active.profile_id != profile_id
            or active.behavior_id not in FISH_BEHAVIOR_IDS
            or active.sequence_id != completed
            or not (
                active.started_at_seconds
                <= simulated_time_seconds
                < active.completes_at_seconds
            )
        ):
            raise ValueError(
                "weighted behavior checkpoint has an invalid active behavior"
            )

    @staticmethod
    def _increment(counters: dict[str, int], name: str) -> None:
        counters[name] = counters.get(name, 0) + 1

    @staticmethod
    def _decision_details(
        decision: BehaviorDecision,
    ) -> dict[str, str]:
        return {
            "behavior_sequence_id": str(decision.sequence_id),
            "behavior_id": decision.behavior_id,
            "behavior_target_id": decision.target_id or "",
            "behavior_duration_seconds": str(decision.duration_seconds),
            "behavior_started_at_seconds": str(
                decision.started_at_seconds
            ),
            "behavior_completes_at_seconds": str(
                decision.completes_at_seconds
            ),
        }
