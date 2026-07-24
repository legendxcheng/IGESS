from __future__ import annotations

from pathlib import Path

import pytest

from fish_test_support import _snapshot
from igess.behavior import BehaviorRuntimeState, BehaviorScheduler
from igess.builder import ModelBuilder
from igess.fish_barbell import FishBarbellDataAdapter
from igess.fish_behavior import (
    UPGRADE_FISH_HALL_BEHAVIOR_ID,
    FishBehaviorAdapter,
    FishBehaviorConfigError,
)
from igess.fish_commands import apply_throw_resolution
from igess.fish_hall import FishHallDataAdapter
from igess.fish_production import FishProductionRuntime
from igess.fish_simulator import FishEconomySimulator
from igess.fish_state import BigNumberDTO, FishCheckpointCodec, PlayerState
from igess.fish_throw_data import (
    FishThrowDataAdapter,
    ProductionThrowConfig,
    ProductionThrowRequest,
)
from igess.fish_trash import FishTrashDataAdapter
from igess.loader import ConfigLoader
from igess.numbers import SimNumber


def test_fish_hall_upgrade_behavior_is_targetless_and_ignores_fish_count(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path)
    config = ProductionThrowConfig.from_mapping(
        {
            "initial_strength": "50",
            "interval_seconds": 1,
            "regular_luck_multiplier": "1",
            "bonus_base_luck": "1",
            "max_bonus_layers": 4,
        }
    )
    throw_adapter = FishThrowDataAdapter(
        snapshot,
        bonus_base_luck=1,
        max_bonus_layers=4,
    )
    hall_adapter = FishHallDataAdapter(snapshot)
    adapter = FishBehaviorAdapter(
        throw_adapter=throw_adapter,
        hall_adapter=hall_adapter,
        trash_adapter=FishTrashDataAdapter(snapshot),
        barbell_adapter=FishBarbellDataAdapter(snapshot),
        throw_config=config,
    )
    profile = ConfigLoader.load_rules_only(
        "projects/fish/economy.yaml"
    ).rules.player_profiles["default"]
    profile.behavior_weights = {
        UPGRADE_FISH_HALL_BEHAVIOR_ID: SimNumber.one()
    }
    profile.behavior_durations = {
        UPGRADE_FISH_HALL_BEHAVIOR_ID: {
            "type": "fixed",
            "seconds": 4,
        }
    }

    empty_state = PlayerState.new(
        initial_torpedo_id=1,
        initial_strength=50,
        initial_trash_man_realm_id=1,
    )
    empty_state.wallet.material = BigNumberDTO.from_value(100)
    empty_candidate = adapter.candidates(empty_state, profile)[0]
    empty_decision = BehaviorScheduler(23).decide(
        (empty_candidate,),
        adapter.behavior_profile(profile),
        sequence_id=0,
        started_at_seconds=0,
    )

    resolution = throw_adapter.resolve(
        ProductionThrowRequest(
            root_random_seed=9,
            throw_id=0,
            strength=50,
            torpedo_id=1,
        )
    )
    state_with_fish = apply_throw_resolution(
        empty_state,
        resolution,
        adapter=throw_adapter,
        hall_adapter=hall_adapter,
    ).state
    populated_candidate = adapter.candidates(state_with_fish, profile)[0]
    populated_decision = BehaviorScheduler(23).decide(
        (populated_candidate,),
        adapter.behavior_profile(profile),
        sequence_id=0,
        started_at_seconds=0,
    )

    assert empty_candidate.available
    assert empty_candidate.targets == ()
    assert populated_candidate.available
    assert populated_candidate.targets == ()
    assert populated_candidate == empty_candidate
    assert populated_decision == empty_decision
    assert empty_decision.target_id is None

    profile.behavior_target_policies = {
        UPGRADE_FISH_HALL_BEHAVIOR_ID: "random_affordable"
    }
    with pytest.raises(FishBehaviorConfigError, match="unsupported target"):
        adapter.behavior_profile(profile)


def test_fish_hall_upgrade_candidate_requires_material_and_remaining_level(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path)
    config = ProductionThrowConfig.from_mapping(
        {
            "initial_strength": "50",
            "interval_seconds": 1,
            "regular_luck_multiplier": "1",
            "bonus_base_luck": "1",
            "max_bonus_layers": 4,
        }
    )
    adapter = FishBehaviorAdapter(
        throw_adapter=FishThrowDataAdapter(
            snapshot,
            bonus_base_luck=1,
            max_bonus_layers=4,
        ),
        hall_adapter=FishHallDataAdapter(snapshot),
        trash_adapter=FishTrashDataAdapter(snapshot),
        barbell_adapter=FishBarbellDataAdapter(snapshot),
        throw_config=config,
    )
    profile = ConfigLoader.load_rules_only(
        "projects/fish/economy.yaml"
    ).rules.player_profiles["default"]
    profile.behavior_weights = {
        UPGRADE_FISH_HALL_BEHAVIOR_ID: SimNumber.one()
    }
    profile.behavior_durations = {
        UPGRADE_FISH_HALL_BEHAVIOR_ID: {
            "type": "fixed",
            "seconds": 1,
        }
    }
    state = PlayerState.new(
        initial_torpedo_id=1,
        initial_strength=50,
        initial_trash_man_realm_id=1,
    )

    assert not adapter.candidates(state, profile)[0].available

    state.wallet.material = BigNumberDTO.from_value(100)
    assert adapter.candidates(state, profile)[0].available

    maxed = state.copy()
    maxed.fish_hall.upgrade_level = 1
    assert not adapter.candidates(maxed, profile)[0].available


def test_fish_hall_upgrade_checkpoint_does_not_pay_or_reselect_mid_behavior(
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
        UPGRADE_FISH_HALL_BEHAVIOR_ID: SimNumber.one()
    }
    profile.behavior_durations = {
        UPGRADE_FISH_HALL_BEHAVIOR_ID: {
            "type": "fixed",
            "seconds": 4,
        }
    }
    snapshot = _snapshot(tmp_path)
    model_digest = "sha256:" + ("e" * 64)
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
    initial_state.wallet.material = BigNumberDTO.from_value(100)
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

    assert first.checkpoint.engine_state["fishHall"]["upgradeLevel"] == 0
    assert first.checkpoint.engine_state["wallet"]["material"] == (
        initial_checkpoint.engine_state["wallet"]["material"]
    )
    assert first.checkpoint.event_counters == {
        "behavior_decisions_started": 1
    }
    assert first.checkpoint.behavior_state["active"] == {
        "sequence_id": 0,
        "profile_id": "default",
        "behavior_id": UPGRADE_FISH_HALL_BEHAVIOR_ID,
        "target_id": None,
        "duration_seconds": 4,
        "started_at_seconds": 0,
        "completes_at_seconds": 4,
    }
    assert resumed.checkpoint.engine_state == continuous.checkpoint.engine_state
    assert resumed.checkpoint.behavior_state == (
        continuous.checkpoint.behavior_state
    )
    assert resumed.checkpoint.event_counters == (
        continuous.checkpoint.event_counters
    )
    assert continuous.checkpoint.engine_state["fishHall"]["upgradeLevel"] == 1
    assert continuous.checkpoint.engine_state["wallet"]["material"]["sign"] == 0
    assert continuous.checkpoint.event_counters == {
        "behavior_decisions_started": 1,
        "behavior_completed": 1,
        f"{UPGRADE_FISH_HALL_BEHAVIOR_ID}_completed": 1,
        "fish_hall_settled": 1,
    }
    upgrade_event = next(
        event
        for event in continuous.result.events
        if event.kind == "fish_hall_upgraded"
    )
    assert upgrade_event.time_seconds == 4
    assert upgrade_event.item_id == "fish_hall:1"
    assert upgrade_event.details["behavior_target_id"] == ""
    assert (
        upgrade_event.details["fish_hall_settlement_to_seconds"]
        == "4"
    )
    assert upgrade_event.details["fish_hall_upgrade_price_resource"] == "material"
