from __future__ import annotations

from pathlib import Path

from fish_test_support import _snapshot
from igess.behavior import (
    BehaviorRuntimeState,
    BehaviorScheduler,
)
from igess.builder import ModelBuilder
from igess.fish_barbell import FishBarbellDataAdapter
from igess.fish_behavior import (
    TRASH_MAN_REBIRTH_BEHAVIOR_ID,
    FishBehaviorAdapter,
)
from igess.fish_hall import FishHallDataAdapter
from igess.fish_production import FishProductionRuntime, settle_fish_production
from igess.fish_simulator import FishEconomySimulator
from igess.fish_state import FishCheckpointCodec, PlayerState, TrashStock
from igess.fish_throw_data import FishThrowDataAdapter, ProductionThrowConfig
from igess.fish_trash import FishTrashDataAdapter
from igess.loader import ConfigLoader
from igess.numbers import SimNumber


def _behavior_adapter(snapshot) -> FishBehaviorAdapter:
    throw_config = ProductionThrowConfig.from_mapping(
        {
            "initial_strength": "50",
            "interval_seconds": 1,
            "regular_luck_multiplier": "1",
            "bonus_base_luck": "1",
            "max_bonus_layers": 4,
        }
    )
    return FishBehaviorAdapter(
        throw_adapter=FishThrowDataAdapter(
            snapshot,
            bonus_base_luck=1,
            max_bonus_layers=4,
        ),
        hall_adapter=FishHallDataAdapter(snapshot),
        trash_adapter=FishTrashDataAdapter(snapshot),
        barbell_adapter=FishBarbellDataAdapter(snapshot),
        throw_config=throw_config,
    )


def test_trash_man_rebirth_behavior_settles_old_multiplier_before_reset(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path, trash_duration=10)
    adapter = _behavior_adapter(snapshot)
    profile = ConfigLoader.load_rules_only(
        "projects/fish/economy.yaml"
    ).rules.player_profiles["default"]
    profile.behavior_weights = {
        TRASH_MAN_REBIRTH_BEHAVIOR_ID: SimNumber.one()
    }
    profile.behavior_durations = {
        TRASH_MAN_REBIRTH_BEHAVIOR_ID: {
            "type": "fixed",
            "seconds": 4,
        }
    }
    state = PlayerState.new(
        initial_torpedo_id=1,
        initial_strength=50,
        initial_trash_man_realm_id=3,
    )
    state.trash_man.processing.active_trash_id = 1
    state.trash_man.processing.stocks = [TrashStock(1, 1)]
    candidate = adapter.candidates(state, profile)[0]
    decision = BehaviorScheduler(29).decide(
        (candidate,),
        adapter.behavior_profile(profile),
        sequence_id=0,
        started_at_seconds=0,
    )

    completion = adapter.complete(
        state,
        decision,
        root_random_seed=29,
        next_throw_id=0,
    )

    assert candidate.available
    assert candidate.targets == ()
    assert completion.event_kind == "trash_man_reborn"
    assert completion.item_id == "trash_man_rebirth:1"
    assert completion.details["trash_material_added"] == "16"
    assert completion.details[
        "trash_man_rebirth_material_multiplier_before"
    ] == "1"
    assert completion.details[
        "trash_man_rebirth_material_multiplier_after"
    ] == "2"
    assert completion.state.wallet.material.to_sim_number() == (
        SimNumber.parse(16)
    )
    assert completion.state.trash_man.realm_id == 1
    assert completion.state.trash_man.highest_realm_id == 3
    assert completion.state.rebirth.trash_man_completed_count == 1

    post_rebirth = settle_fish_production(
        completion.state,
        5,
        hall_adapter=adapter.hall_adapter,
        trash_adapter=adapter.trash_adapter,
        barbell_adapter=adapter.barbell_adapter,
        runtime=completion.production_runtime,
    )
    assert post_rebirth.material_added == SimNumber.parse(5)
    assert post_rebirth.state.wallet.material.to_sim_number() == (
        SimNumber.parse(21)
    )

    second_candidate = adapter.candidates(
        completion.state,
        profile,
    )[0]
    assert not second_candidate.available


def test_trash_man_rebirth_checkpoint_does_not_reset_mid_behavior(
    tmp_path: Path,
) -> None:
    raw = ConfigLoader.load(
        "projects/fish/economy.yaml",
        "projects/fish/luban_exports",
    )
    model = ModelBuilder.build(raw)
    model.scenarios["smoke"].duration_hours = 4 / 3600
    profile = model.player_profiles["default"]
    profile.behavior_weights = {
        TRASH_MAN_REBIRTH_BEHAVIOR_ID: SimNumber.one()
    }
    profile.behavior_durations = {
        TRASH_MAN_REBIRTH_BEHAVIOR_ID: {
            "type": "fixed",
            "seconds": 4,
        }
    }
    snapshot = _snapshot(tmp_path)
    model_digest = "sha256:" + ("6" * 64)
    simulator = FishEconomySimulator(
        model,
        snapshot,
        model_digest=model_digest,
    )
    initial_state = PlayerState.new(
        initial_torpedo_id=1,
        initial_strength=50,
        initial_trash_man_realm_id=3,
    )
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

    assert first.checkpoint.engine_state["trashMan"]["realmId"] == 3
    assert first.checkpoint.engine_state["rebirth"][
        "trashManCompletedCount"
    ] == 0
    assert first.checkpoint.engine_state["production"]["lastSettledAt"] == 0
    assert first.checkpoint.event_counters == {
        "behavior_decisions_started": 1
    }
    assert first.checkpoint.behavior_state["active"]["behavior_id"] == (
        TRASH_MAN_REBIRTH_BEHAVIOR_ID
    )
    assert resumed.checkpoint.engine_state == continuous.checkpoint.engine_state
    assert resumed.checkpoint.behavior_state == (
        continuous.checkpoint.behavior_state
    )
    assert resumed.checkpoint.event_counters == (
        continuous.checkpoint.event_counters
    )
    assert continuous.checkpoint.engine_state["trashMan"]["realmId"] == 1
    assert continuous.checkpoint.engine_state["trashMan"][
        "highestRealmId"
    ] == 3
    assert continuous.checkpoint.engine_state["rebirth"][
        "trashManCompletedCount"
    ] == 1
    assert continuous.checkpoint.event_counters == {
        "behavior_decisions_started": 1,
        "behavior_completed": 1,
        f"{TRASH_MAN_REBIRTH_BEHAVIOR_ID}_completed": 1,
        "fish_hall_settled": 1,
    }
    event = next(
        event
        for event in continuous.result.events
        if event.kind == "trash_man_reborn"
    )
    assert event.time_seconds == 4
    assert event.item_id == "trash_man_rebirth:1"
    assert event.details["behavior_target_id"] == ""
