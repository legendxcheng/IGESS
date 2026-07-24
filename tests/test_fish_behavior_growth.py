from __future__ import annotations

from pathlib import Path

import pytest

from fish_test_support import _snapshot
from igess.behavior import (
    BehaviorDecision,
    BehaviorRuntimeState,
    BehaviorScheduler,
)
from igess.builder import ModelBuilder
from igess.fish_barbell import FishBarbellDataAdapter
from igess.fish_behavior import (
    STRENGTH_REBIRTH_BEHAVIOR_ID,
    SYNTHESIZE_BARBELL_BEHAVIOR_ID,
    FishBehaviorAdapter,
    FishBehaviorConfigError,
)
from igess.fish_hall import FishHallDataAdapter
from igess.fish_production import FishProductionRuntime, settle_fish_production
from igess.fish_simulator import FishEconomySimulator
from igess.fish_state import (
    BigNumberDTO,
    FishCheckpointCodec,
    FishInstance,
    OwnedBarbell,
    PlayerState,
)
from igess.fish_throw_data import FishThrowDataAdapter, ProductionThrowConfig
from igess.fish_trash import FishTrashDataAdapter
from igess.loader import ConfigLoader
from igess.numbers import SimNumber


def test_strength_rebirth_behavior_settles_old_multiplier_before_reset(
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
    hall_adapter = FishHallDataAdapter(snapshot)
    adapter = FishBehaviorAdapter(
        throw_adapter=FishThrowDataAdapter(
            snapshot,
            bonus_base_luck=1,
            max_bonus_layers=4,
        ),
        hall_adapter=hall_adapter,
        trash_adapter=FishTrashDataAdapter(snapshot),
        barbell_adapter=FishBarbellDataAdapter(snapshot),
        throw_config=config,
    )
    profile = ConfigLoader.load_rules_only(
        "projects/fish/economy.yaml"
    ).rules.player_profiles["default"]
    profile.behavior_weights = {
        STRENGTH_REBIRTH_BEHAVIOR_ID: SimNumber.one()
    }
    profile.behavior_durations = {
        STRENGTH_REBIRTH_BEHAVIOR_ID: {
            "type": "fixed",
            "seconds": 4,
        }
    }
    state = PlayerState.new(
        initial_torpedo_id=1,
        initial_strength=1000,
        initial_trash_man_realm_id=1,
    )
    state.fish.items = [FishInstance(1, 1, 7, 1, 100, 1)]
    state.fish.next_instance_id = 2
    candidate = adapter.candidates(state, profile)[0]
    decision = BehaviorScheduler(23).decide(
        (candidate,),
        adapter.behavior_profile(profile),
        sequence_id=0,
        started_at_seconds=0,
    )

    completion = adapter.complete(
        state,
        decision,
        root_random_seed=23,
        next_throw_id=0,
    )

    assert candidate.available
    assert candidate.targets == ()
    assert completion.event_kind == "strength_reborn"
    assert completion.item_id == "strength_rebirth:1"
    assert completion.state.wallet.money.to_sim_number() == SimNumber.parse(40)
    assert completion.state.wallet.strength.to_sim_number() == SimNumber.zero()
    assert completion.state.rebirth.strength_completed_count == 1
    assert completion.details["fish_hall_money_added"] == "40"
    assert completion.details["strength_rebirth_multiplier_before"] == "1"
    assert completion.details["strength_rebirth_multiplier_after"] == "2"
    assert (
        hall_adapter.snapshot(
            completion.state
        ).total_income_per_second
        == SimNumber.parse(20)
    )

    below_requirement = state.copy()
    below_requirement.wallet.strength = BigNumberDTO.from_value(999)
    assert not adapter.candidates(below_requirement, profile)[0].available
    maxed = state.copy()
    maxed.rebirth.strength_completed_count = 2
    assert not adapter.candidates(maxed, profile)[0].available


def test_strength_rebirth_checkpoint_does_not_reset_mid_behavior(
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
        STRENGTH_REBIRTH_BEHAVIOR_ID: SimNumber.one()
    }
    profile.behavior_durations = {
        STRENGTH_REBIRTH_BEHAVIOR_ID: {
            "type": "fixed",
            "seconds": 4,
        }
    }
    snapshot = _snapshot(tmp_path)
    model_digest = "sha256:" + ("7" * 64)
    simulator = FishEconomySimulator(
        model,
        snapshot,
        model_digest=model_digest,
    )
    initial_state = PlayerState.new(
        initial_torpedo_id=1,
        initial_strength=1000,
        initial_trash_man_realm_id=1,
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

    assert first.checkpoint.engine_state["wallet"]["strength"] == (
        initial_checkpoint.engine_state["wallet"]["strength"]
    )
    assert first.checkpoint.engine_state["rebirth"][
        "strengthCompletedCount"
    ] == 0
    assert first.checkpoint.engine_state["production"]["lastSettledAt"] == 0
    assert first.checkpoint.event_counters == {
        "behavior_decisions_started": 1
    }
    assert first.checkpoint.behavior_state["active"] == {
        "sequence_id": 0,
        "profile_id": "default",
        "behavior_id": STRENGTH_REBIRTH_BEHAVIOR_ID,
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
    assert continuous.checkpoint.engine_state["rebirth"][
        "strengthCompletedCount"
    ] == 1
    assert continuous.checkpoint.engine_state["wallet"]["strength"][
        "sign"
    ] == 0
    assert continuous.checkpoint.event_counters == {
        "behavior_decisions_started": 1,
        "behavior_completed": 1,
        f"{STRENGTH_REBIRTH_BEHAVIOR_ID}_completed": 1,
        "fish_hall_settled": 1,
    }
    event = next(
        event
        for event in continuous.result.events
        if event.kind == "strength_reborn"
    )
    assert event.time_seconds == 4
    assert event.item_id == "strength_rebirth:1"
    assert event.details["behavior_target_id"] == ""


def test_barbell_synthesis_behavior_uses_explicit_affordable_unowned_targets(
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
        SYNTHESIZE_BARBELL_BEHAVIOR_ID: SimNumber.one()
    }
    profile.behavior_durations = {
        SYNTHESIZE_BARBELL_BEHAVIOR_ID: {
            "type": "fixed",
            "seconds": 1,
        }
    }
    state = PlayerState.new(
        initial_torpedo_id=1,
        initial_trash_man_realm_id=1,
    )
    state.wallet.material = BigNumberDTO.from_value(20)

    with pytest.raises(FishBehaviorConfigError, match="explicit target"):
        adapter.behavior_profile(profile)

    profile.behavior_target_policies = {
        SYNTHESIZE_BARBELL_BEHAVIOR_ID: "random_affordable"
    }
    candidate = adapter.candidates(state, profile)[0]
    assert candidate.available
    assert [target.target_id for target in candidate.targets] == ["1"]

    state.barbell.owned = [OwnedBarbell(1, 1)]
    state.barbell.equipped_id = 1
    state.wallet.material = BigNumberDTO.from_value(75)
    candidate = adapter.candidates(state, profile)[0]
    assert [target.target_id for target in candidate.targets] == ["2"]


def test_barbell_synthesis_settles_old_equipment_before_auto_equip(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path)
    adapter = FishBehaviorAdapter(
        throw_adapter=FishThrowDataAdapter(
            snapshot,
            bonus_base_luck=1,
            max_bonus_layers=4,
        ),
        hall_adapter=FishHallDataAdapter(snapshot),
        trash_adapter=FishTrashDataAdapter(snapshot),
        barbell_adapter=FishBarbellDataAdapter(snapshot),
        throw_config=ProductionThrowConfig.from_mapping(
            {
                "initial_strength": "50",
                "interval_seconds": 1,
                "regular_luck_multiplier": "1",
                "bonus_base_luck": "1",
                "max_bonus_layers": 4,
            }
        ),
    )
    state = PlayerState.new(
        initial_torpedo_id=1,
        initial_strength=0,
        initial_trash_man_realm_id=1,
    )
    state.wallet.material = BigNumberDTO.from_value(75)
    state.barbell.owned = [OwnedBarbell(1, 1)]
    state.barbell.equipped_id = 1
    decision = BehaviorDecision(
        sequence_id=0,
        profile_id="default",
        behavior_id=SYNTHESIZE_BARBELL_BEHAVIOR_ID,
        target_id="2",
        duration_seconds=4,
        started_at_seconds=0,
        completes_at_seconds=4,
    )

    completion = adapter.complete(
        state,
        decision,
        root_random_seed=7,
        next_throw_id=0,
    )

    assert completion.details["barbell_strength_added"] == "8"
    assert (
        completion.state.wallet.strength.to_sim_number()
        == SimNumber.parse(8)
    )
    assert completion.state.wallet.material.to_sim_number().is_zero()
    assert completion.state.barbell.equipped_id == 2
    assert completion.details[
        "barbell_strength_per_second_before_command"
    ] == "2"
    assert completion.details[
        "barbell_strength_per_second_after_synthesis"
    ] == "5"


def test_barbell_synthesis_checkpoint_does_not_pay_or_produce_mid_behavior(
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
        SYNTHESIZE_BARBELL_BEHAVIOR_ID: SimNumber.one()
    }
    profile.behavior_durations = {
        SYNTHESIZE_BARBELL_BEHAVIOR_ID: {
            "type": "fixed",
            "seconds": 4,
        }
    }
    profile.behavior_target_policies = {
        SYNTHESIZE_BARBELL_BEHAVIOR_ID: "random_affordable"
    }
    snapshot = _snapshot(tmp_path)
    model_digest = "sha256:" + ("f" * 64)
    simulator = FishEconomySimulator(
        model,
        snapshot,
        model_digest=model_digest,
    )
    initial_state = PlayerState.new(
        initial_torpedo_id=1,
        initial_strength=0,
        initial_trash_man_realm_id=1,
    )
    initial_state.wallet.material = BigNumberDTO.from_value(20)
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

    assert first.checkpoint.engine_state["barbell"] == {
        "equippedId": 0,
        "owned": [],
    }
    assert first.checkpoint.engine_state["wallet"]["material"] == (
        initial_checkpoint.engine_state["wallet"]["material"]
    )
    assert first.checkpoint.engine_state["wallet"]["strength"]["sign"] == 0
    assert resumed.checkpoint.engine_state == continuous.checkpoint.engine_state
    assert resumed.checkpoint.behavior_state == (
        continuous.checkpoint.behavior_state
    )
    assert resumed.checkpoint.event_counters == (
        continuous.checkpoint.event_counters
    )
    assert continuous.checkpoint.engine_state["barbell"] == {
        "equippedId": 1,
        "owned": [{"barbellId": 1, "count": 1}],
    }
    assert continuous.checkpoint.engine_state["wallet"]["material"]["sign"] == 0
    assert continuous.checkpoint.engine_state["wallet"]["strength"]["sign"] == 0
    assert continuous.checkpoint.event_counters == {
        "behavior_decisions_started": 1,
        "behavior_completed": 1,
        f"{SYNTHESIZE_BARBELL_BEHAVIOR_ID}_completed": 1,
        "fish_hall_settled": 1,
    }
    synthesis_event = next(
        event
        for event in continuous.result.events
        if event.kind == "barbell_synthesized"
    )
    assert synthesis_event.time_seconds == 4
    assert synthesis_event.item_id == "barbell:1"
    assert synthesis_event.details["barbell_strength_added"] == "0"

    final_state = FishCheckpointCodec.decode_state(
        continuous.checkpoint,
        expected_model_digest=model_digest,
        context=FishHallDataAdapter(snapshot).validation_context(),
    )
    post_synthesis = settle_fish_production(
        final_state,
        6,
        hall_adapter=FishHallDataAdapter(snapshot),
        trash_adapter=FishTrashDataAdapter(snapshot),
        barbell_adapter=FishBarbellDataAdapter(snapshot),
        runtime=FishProductionRuntime.from_dict(
            continuous.checkpoint.engine_runtime_state
        ),
    )
    assert post_synthesis.strength_added == SimNumber.parse(4)
