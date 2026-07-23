from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .checkpoint import SimulationCheckpoint
from .fish_commands import apply_throw_resolution, lock_throw_request
from .fish_data import FishDataSnapshot
from .fish_state import FishCheckpointCodec, PlayerState
from .fish_throw_data import (
    FishThrowDataAdapter,
    ProductionThrowConfig,
)
from .schema import EconomyModel, Event, SimulationResult, TimelineRow
from .time_engine import TimeEngine


@dataclass(frozen=True)
class FishSimulationRun:
    result: SimulationResult
    checkpoint: SimulationCheckpoint


class FishEconomySimulator:
    """Fish event loop backed by production throw data and PlayerState.

    Active throws run on explicit recurring boundaries. Each event locks its
    strength and torpedo from PlayerState before resolving and committing.
    """

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
        active_throw = self.model.engine_settings.get("active_throw")
        self.active_throw_config = (
            None
            if active_throw is None
            else ProductionThrowConfig.from_mapping(active_throw)
        )
        self.throw_adapter = (
            None
            if self.active_throw_config is None
            else FishThrowDataAdapter(
                self.data,
                bonus_base_luck=self.active_throw_config.bonus_base_luck,
                max_bonus_layers=self.active_throw_config.max_bonus_layers,
            )
        )
        self.time_engine = TimeEngine(self.model.config.tick_seconds)

    def run_scenario(
        self,
        scenario_id: str,
        checkpoint: SimulationCheckpoint | None = None,
        *,
        until_seconds: int | None = None,
    ) -> FishSimulationRun:
        if scenario_id not in self.model.scenarios:
            available = ", ".join(sorted(self.model.scenarios)) or "none"
            raise ValueError(
                f"unknown scenario '{scenario_id}'; available: {available}"
            )
        scenario = self.model.scenarios[scenario_id]
        if len(scenario.profiles) != 1:
            raise ValueError("Phase-0 Fish scenarios require exactly one profile")
        profile_id = scenario.profiles[0]
        duration_seconds = int(scenario.duration_hours * 3600)

        if checkpoint is None:
            initial_torpedo_id = (
                0
                if self.throw_adapter is None
                else self.throw_adapter.initial_torpedo_id
            )
            state = PlayerState.new(
                0,
                initial_torpedo_id=initial_torpedo_id,
                initial_strength=(
                    0
                    if self.active_throw_config is None
                    else Decimal(str(self.active_throw_config.initial_strength))
                ),
            )
            start_time = 0
            root_random_seed = self.model.config.random_seed
            next_throw_id = 0
            event_counters: dict[str, int] = {}
        else:
            state = FishCheckpointCodec.decode_state(
                checkpoint,
                expected_model_digest=self.model_digest,
            )
            if checkpoint.scenario_id != scenario_id:
                raise ValueError("checkpoint scenario does not match the requested scenario")
            if checkpoint.profile_id != profile_id:
                raise ValueError("checkpoint profile does not match the requested profile")
            start_time = checkpoint.simulated_time_seconds
            root_random_seed = checkpoint.root_random_seed
            next_throw_id = checkpoint.next_throw_id
            event_counters = dict(checkpoint.event_counters)
            if self.active_throw_config is not None:
                self._validate_active_throw_checkpoint(
                    state,
                    start_time,
                    next_throw_id,
                    event_counters,
                    self.active_throw_config.interval_seconds,
                )
        if start_time > duration_seconds:
            raise ValueError("checkpoint time exceeds the scenario duration")

        target_time = duration_seconds if until_seconds is None else until_seconds
        if type(target_time) is not int or not start_time <= target_time <= duration_seconds:
            raise ValueError(
                "until_seconds must be an integer within the remaining scenario"
            )
        if (
            until_seconds is not None
            and target_time != duration_seconds
            and self.active_throw_config is not None
            and target_time % self.active_throw_config.interval_seconds != 0
        ):
            raise ValueError(
                "intermediate checkpoint must be on an active-throw event boundary"
            )

        timeline = [self._timeline_row(scenario_id, profile_id, start_time, state)]
        events: list[Event] = [
            Event(
                scenario_id=scenario_id,
                profile_id=profile_id,
                time_seconds=start_time,
                kind="fish_engine_ready",
                item_id="active_throw_loop",
                details={
                    "engine_id": "fish",
                    "model_digest": self.model_digest,
                    "production_data": str(self.data.production_data).lower(),
                    "table_count": str(len(self.data.files)),
                },
            )
        ]
        throw_times = (
            set()
            if self.active_throw_config is None
            else set(
                self.time_engine.recurring_event_times(
                    start_time,
                    target_time,
                    self.active_throw_config.interval_seconds,
                )
            )
        )
        record_times = set(
            self.time_engine.recurring_event_times(
                start_time,
                target_time,
                scenario.record_interval_seconds,
            )
        )
        if target_time > start_time:
            record_times.add(target_time)

        for event_time in sorted(throw_times | record_times):
            if event_time in throw_times:
                if self.active_throw_config is None or self.throw_adapter is None:
                    raise AssertionError("active throw schedule requires its adapter")
                config = self.active_throw_config
                request = lock_throw_request(
                    state,
                    adapter=self.throw_adapter,
                    root_random_seed=root_random_seed,
                    throw_id=next_throw_id,
                    regular_luck_multiplier=config.regular_luck_multiplier,
                )
                resolution = self.throw_adapter.resolve(request)
                application = apply_throw_resolution(
                    state,
                    resolution,
                    adapter=self.throw_adapter,
                )
                state = application.state
                event_details = resolution.event_details()
                event_details.update(application.event_details())
                event_details["strength_source"] = "player_state_snapshot"
                events.append(
                    Event(
                        scenario_id=scenario_id,
                        profile_id=profile_id,
                        time_seconds=event_time,
                        kind="fish_throw_resolved",
                        item_id=f"throw:{next_throw_id}",
                        details=event_details,
                    )
                )
                next_throw_id += 1
                event_counters["active_throw_resolved"] = (
                    event_counters.get("active_throw_resolved", 0) + 1
                )

            if event_time in record_times:
                timeline.append(
                    self._timeline_row(
                        scenario_id,
                        profile_id,
                        event_time,
                        state,
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
        )
        return FishSimulationRun(result=result, checkpoint=final_checkpoint)

    @staticmethod
    def _validate_active_throw_checkpoint(
        state: PlayerState,
        simulated_time_seconds: int,
        next_throw_id: int,
        event_counters: dict[str, int],
        interval_seconds: int,
    ) -> None:
        resolved_count = event_counters.get("active_throw_resolved", 0)
        if type(resolved_count) is not int or resolved_count < 0:
            raise ValueError(
                "checkpoint active_throw_resolved counter must be non-negative"
            )
        if type(interval_seconds) is not int or interval_seconds <= 0:
            raise ValueError("active throw interval must be positive")
        expected_count = simulated_time_seconds // interval_seconds
        trash_count = sum(
            stock.count for stock in state.trash_man.processing.stocks
        )
        if (
            simulated_time_seconds < 0
            or resolved_count != expected_count
            or next_throw_id != resolved_count
            or state.statistics.total_throws != resolved_count
            or state.statistics.total_fish_caught != resolved_count
            or state.meta.revision != resolved_count
            or len(state.fish.items) != resolved_count
            or trash_count != resolved_count
        ):
            raise ValueError(
                "checkpoint active-throw progress does not match committed rewards"
            )

    def _timeline_row(
        self,
        scenario_id: str,
        profile_id: str,
        time_seconds: int,
        state: PlayerState,
    ) -> TimelineRow:
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
            total_cps="0",
        )
