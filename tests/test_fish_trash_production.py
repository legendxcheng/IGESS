from __future__ import annotations

import json
from pathlib import Path

from fish_test_support import _snapshot
from igess.behavior import BehaviorRuntimeState
from igess.builder import ModelBuilder
from igess.fish_hall import FishHallDataAdapter
from igess.fish_production import FishProductionRuntime, settle_fish_production
from igess.fish_simulator import FishEconomySimulator
from igess.fish_state import FishCheckpointCodec, PlayerState, TrashStock
from igess.fish_trash import FishTrashDataAdapter, TrashProcessingRuntime
from igess.loader import ConfigLoader
from igess.numbers import SimNumber


def test_trash_processing_batches_queue_and_preserves_fractional_work(
    tmp_path: Path,
) -> None:
    adapter = FishTrashDataAdapter(_snapshot(tmp_path))
    state = PlayerState.new(initial_trash_man_realm_id=1)
    state.trash_man.processing.active_trash_id = 1
    state.trash_man.processing.active_progress_seconds = 100
    state.trash_man.processing.stocks = [
        TrashStock(trash_id=2, count=1),
        TrashStock(trash_id=1, count=2),
    ]

    settlement = adapter.settle(
        state,
        500,
        runtime=TrashProcessingRuntime(SimNumber.parse("0.5")),
    )

    assert settlement.completed_by_trash == ((1, 2),)
    assert settlement.completed_count == 2
    assert settlement.material_added == SimNumber.parse("1001")
    assert settlement.work_consumed == SimNumber.parse("500")
    assert settlement.unused_work == SimNumber.zero()
    assert settlement.processing.stocks == [TrashStock(trash_id=2, count=1)]
    assert settlement.processing.active_trash_id == 2
    assert settlement.processing.active_progress_seconds == 0
    assert settlement.runtime.progress_remainder == SimNumber.parse("0.5")


def test_trash_processing_speed_change_preserves_total_batch_yield(
    tmp_path: Path,
) -> None:
    adapter = FishTrashDataAdapter(_snapshot(tmp_path))
    state = PlayerState.new(initial_trash_man_realm_id=2)
    state.rebirth.trash_man_completed_count = 1
    state.trash_man.processing.active_trash_id = 1
    state.trash_man.processing.stocks = [TrashStock(trash_id=1, count=1)]

    first = adapter.settle(state, 1)
    assert first.decompose_speed_multiplier == SimNumber.parse("1.25")
    assert first.material_output_multiplier == SimNumber.parse("2")
    assert first.material_added == SimNumber.parse("5")
    assert first.processing.active_progress_seconds == 1
    assert first.runtime.progress_remainder == SimNumber.parse("0.25")

    changed = state.copy()
    changed.trash_man.processing = first.processing
    changed.trash_man.realm_id = 3
    changed.trash_man.highest_realm_id = 3
    second = adapter.settle(
        changed,
        150,
        runtime=first.runtime,
    )

    assert second.completed_count == 1
    assert second.material_added == SimNumber.parse("1195")
    assert second.unused_work == SimNumber.parse("1.25")
    assert second.processing.stocks == []
    assert first.material_added + second.material_added == SimNumber.parse("1200")


def test_fish_production_atomically_settles_material_and_queue(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path)
    state = PlayerState.new(initial_trash_man_realm_id=1)
    state.trash_man.processing.active_trash_id = 1
    state.trash_man.processing.stocks = [TrashStock(trash_id=1, count=1)]

    settlement = settle_fish_production(
        state,
        300,
        hall_adapter=FishHallDataAdapter(snapshot),
        trash_adapter=FishTrashDataAdapter(snapshot),
        runtime=FishProductionRuntime(),
    )

    assert state.wallet.material.to_sim_number() == SimNumber.zero()
    assert settlement.material_added == SimNumber.parse("600")
    assert settlement.state.wallet.material.to_sim_number() == SimNumber.parse("600")
    assert settlement.state.trash_man.processing.stocks == []
    assert settlement.state.production.last_settled_at == 300
    assert settlement.state.meta.revision == 1
    details = settlement.event_details()
    assert details["trash_processing_queue_policy"] == "trash_id_ascending"
    assert details["trash_completed_count"] == "1"
    assert details["trash_material_added"] == "600"


def test_online_cultivation_splits_trash_work_at_realm_boundary(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path, trash_duration=10)
    hall_adapter = FishHallDataAdapter(snapshot)
    trash_adapter = FishTrashDataAdapter(snapshot)
    state = PlayerState.new(initial_trash_man_realm_id=2)
    state.trash_man.highest_realm_id = 3
    state.trash_man.processing.active_trash_id = 1
    state.trash_man.processing.stocks = [TrashStock(trash_id=1, count=1)]

    first = settle_fish_production(
        state,
        1,
        hall_adapter=hall_adapter,
        trash_adapter=trash_adapter,
    )

    assert first.state.trash_man.realm_id == 3
    assert first.state.trash_man.highest_realm_id == 3
    assert first.state.trash_man.training_progress_seconds == 0
    assert first.material_added == SimNumber.parse("2.5")
    assert first.trash_processing.work_consumed == SimNumber.parse("1.25")
    assert first.trash_processing.runtime.progress_remainder == (
        SimNumber.parse("0.25")
    )
    assert [
        transition.to_dict() for transition in first.trash_processing.transitions
    ] == [
        {
            "from_realm_id": 2,
            "to_realm_id": 3,
            "at_elapsed_seconds": 1,
        }
    ]

    second = settle_fish_production(
        first.state,
        2,
        hall_adapter=hall_adapter,
        trash_adapter=trash_adapter,
        runtime=first.runtime,
    )

    assert second.material_added == SimNumber.parse("4")
    assert second.state.wallet.material.to_sim_number() == SimNumber.parse("6.5")
    details = first.event_details()
    assert details["trash_man_cultivation_online_only"] == "true"
    assert details["trash_man_cultivation_ceiling"] == ("historical_highest_realm")
    assert details["trash_man_realm_id_before"] == "2"
    assert details["trash_man_realm_id_after"] == "3"
    assert json.loads(details["trash_processing_realm_segments"]) == [
        {
            "decompose_speed_multiplier": "1.25",
            "elapsed_seconds": 1,
            "material_added": "2.5",
            "realm_id": 2,
            "unused_work": "0",
            "work_consumed": "1.25",
        }
    ]


def test_online_cultivation_handles_zero_duration_and_stops_at_highest(
    tmp_path: Path,
) -> None:
    adapter = FishTrashDataAdapter(_snapshot(tmp_path, trash_duration=10))
    state = PlayerState.new(initial_trash_man_realm_id=1)
    state.trash_man.highest_realm_id = 3
    state.trash_man.processing.active_trash_id = 1
    state.trash_man.processing.stocks = [TrashStock(trash_id=1, count=1)]

    settlement = adapter.settle_online(state, 5)

    assert settlement.realm_id_after == 3
    assert settlement.training_progress_seconds_after == 0
    assert settlement.material_added == SimNumber.parse("18.5")
    assert [transition.to_dict() for transition in settlement.transitions] == [
        {
            "from_realm_id": 1,
            "to_realm_id": 2,
            "at_elapsed_seconds": 0,
        },
        {
            "from_realm_id": 2,
            "to_realm_id": 3,
            "at_elapsed_seconds": 1,
        },
    ]
    assert [
        (segment.realm_id, segment.elapsed_seconds) for segment in settlement.segments
    ] == [(2, 1), (3, 4)]

    already_at_highest = settlement.processing
    capped = state.copy()
    capped.trash_man.realm_id = 3
    capped.trash_man.highest_realm_id = 3
    capped.trash_man.processing = already_at_highest
    capped.trash_man.training_progress_seconds = 7

    capped_settlement = adapter.settle_online(
        capped,
        2,
        runtime=settlement.runtime,
    )

    assert capped_settlement.realm_id_after == 3
    assert capped_settlement.training_progress_seconds_after == 7
    assert capped_settlement.transitions == ()


def test_online_cultivation_checkpoint_resume_does_not_split_active_behavior(
    tmp_path: Path,
) -> None:
    raw = ConfigLoader.load(
        "projects/fish/economy.yaml",
        "projects/fish/luban_exports",
    )
    model = ModelBuilder.build(raw)
    profile = model.player_profiles["default"]
    profile.behavior_weights = {"idle": SimNumber.one()}
    profile.behavior_durations = {"idle": {"type": "fixed", "seconds": 4}}
    snapshot = _snapshot(tmp_path)
    model_digest = "sha256:" + ("d" * 64)
    simulator = FishEconomySimulator(
        model,
        snapshot,
        model_digest=model_digest,
    )
    initial_state = PlayerState.new(
        initial_torpedo_id=1,
        initial_strength=50,
        initial_trash_man_realm_id=1,
    )
    initial_state.trash_man.highest_realm_id = 3
    initial_checkpoint = FishCheckpointCodec.new(
        initial_state,
        model_digest=model_digest,
        scenario_id="smoke",
        profile_id="default",
        root_random_seed=model.config.random_seed,
        behavior_state=BehaviorRuntimeState().to_dict(),
        engine_runtime_state=FishProductionRuntime().to_dict(),
        context=FishHallDataAdapter(snapshot).validation_context(),
    )

    continuous = simulator.run_scenario("smoke", initial_checkpoint)
    first = simulator.run_scenario(
        "smoke",
        initial_checkpoint,
        until_seconds=2,
    )
    resumed = simulator.run_scenario("smoke", first.checkpoint)

    assert first.checkpoint.engine_state["trashMan"]["realmId"] == 1
    assert first.checkpoint.engine_state["production"]["lastSettledAt"] == 0
    assert continuous.checkpoint.engine_state["trashMan"]["realmId"] == 3
    assert resumed.checkpoint.engine_state == (continuous.checkpoint.engine_state)
    assert resumed.checkpoint.engine_runtime_state == (
        continuous.checkpoint.engine_runtime_state
    )
    assert resumed.checkpoint.event_counters == (continuous.checkpoint.event_counters)
    assert (
        first.result.timeline + resumed.result.timeline[1:]
        == continuous.result.timeline
    )

    def behavior_events(run):
        return [
            event for event in run.result.events if event.kind != "fish_engine_ready"
        ]

    assert behavior_events(first) + behavior_events(resumed) == (
        behavior_events(continuous)
    )
    first_idle = next(
        event
        for event in continuous.result.events
        if event.kind == "fish_behavior_idle_completed"
    )
    assert first_idle.details["trash_man_realm_advance_count"] == "2"


def test_active_throw_loop_processes_trash_and_replays_checkpoint(
    tmp_path: Path,
) -> None:
    raw = ConfigLoader.load(
        "projects/fish/economy.yaml",
        "projects/fish/luban_exports",
    )
    model = ModelBuilder.build(raw)
    simulator = FishEconomySimulator(
        model,
        _snapshot(tmp_path, trash_duration=3),
        model_digest="sha256:" + ("c" * 64),
    )

    continuous = simulator.run_scenario("smoke")
    first = simulator.run_scenario("smoke", until_seconds=5)
    resumed = simulator.run_scenario("smoke", first.checkpoint)
    final_processing = continuous.checkpoint.engine_state["trashMan"]["processing"]

    assert continuous.checkpoint.event_counters["trash_processed"] == 3
    assert sum(stock["count"] for stock in final_processing["stocks"]) == 7
    assert continuous.checkpoint.engine_state["wallet"]["material"]["sign"] == 1
    assert resumed.checkpoint.engine_state == continuous.checkpoint.engine_state
    assert (
        resumed.checkpoint.engine_runtime_state
        == continuous.checkpoint.engine_runtime_state
    )
    assert resumed.checkpoint.event_counters == continuous.checkpoint.event_counters
