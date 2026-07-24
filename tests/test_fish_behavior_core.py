from __future__ import annotations

from pathlib import Path

import pytest

from fish_test_support import _snapshot
from igess.behavior import BehaviorScheduler
from igess.builder import ModelBuilder
from igess.fish_barbell import FishBarbellDataAdapter
from igess.fish_behavior import FishBehaviorAdapter, FishBehaviorConfigError
from igess.fish_commands import apply_throw_resolution, lock_throw_request
from igess.fish_hall import FishHallDataAdapter
from igess.fish_simulator import FishEconomySimulator
from igess.fish_state import BigNumberDTO, PlayerState
from igess.fish_throw_data import (
    FishThrowDataAdapter,
    ProductionThrowConfig,
    ProductionThrowRequest,
)
from igess.fish_trash import FishTrashDataAdapter
from igess.loader import ConfigLoader
from igess.numbers import SimNumber


def test_active_throw_config_requires_attributable_non_table_values() -> None:
    config = ProductionThrowConfig.from_mapping(
        {
            "initial_strength": "50",
            "interval_seconds": 1,
            "regular_luck_multiplier": "1",
            "bonus_base_luck": "1",
            "max_bonus_layers": 4,
        }
    )

    assert config.manifest_parameters() == {
        "initial_strength": "50",
        "interval_seconds": 1,
        "regular_luck_multiplier": "1",
        "bonus_base_luck": "1",
        "max_bonus_layers": 4,
    }


def test_throw_request_locks_strength_and_torpedo_from_player_state(
    tmp_path: Path,
) -> None:
    adapter = FishThrowDataAdapter(
        _snapshot(tmp_path),
        bonus_base_luck=1,
        max_bonus_layers=4,
    )
    state = PlayerState.new(
        initial_torpedo_id=1,
        initial_strength="75",
    )

    request = lock_throw_request(
        state,
        adapter=adapter,
        root_random_seed=123,
        throw_id=0,
    )
    state.wallet.strength = state.wallet.strength.from_value("100")

    assert request.strength == 75
    assert request.torpedo_id == 1
    assert request.throw_id == 0


def test_active_throw_loop_matches_checkpoint_segmented_resume(
    tmp_path: Path,
) -> None:
    raw = ConfigLoader.load(
        "projects/fish/economy.yaml",
        "projects/fish/luban_exports",
    )
    model = ModelBuilder.build(raw)
    simulator = FishEconomySimulator(
        model,
        _snapshot(tmp_path),
        model_digest="sha256:" + ("a" * 64),
    )

    continuous = simulator.run_scenario("smoke")
    first_half = simulator.run_scenario("smoke", until_seconds=5)
    second_half = simulator.run_scenario(
        "smoke",
        first_half.checkpoint,
    )

    def throw_events(run):
        return [
            event for event in run.result.events if event.kind == "fish_throw_resolved"
        ]

    continuous_throws = throw_events(continuous)
    segmented_throws = throw_events(first_half) + throw_events(second_half)
    assert segmented_throws == continuous_throws
    assert [event.time_seconds for event in continuous_throws] == list(range(1, 11))
    assert all(
        event.details["strength_source"] == "player_state_snapshot"
        and event.details["input_strength"] == "50"
        for event in continuous_throws
    )
    assert second_half.checkpoint.engine_state == continuous.checkpoint.engine_state
    assert second_half.checkpoint.next_throw_id == 10
    assert second_half.checkpoint.event_counters == {
        "active_throw_resolved": 10,
        "fish_hall_settled": 10,
    }
    assert continuous.result.timeline[0].total_cps == "0"
    assert all(row.total_cps != "0" for row in continuous.result.timeline[1:])
    previous_money = "0"
    previous_cps = "0"
    for row in continuous.result.timeline[1:]:
        expected_money = (
            SimNumber.parse(previous_money) + SimNumber.parse(previous_cps)
        ).to_decimal_string()
        assert SimNumber.parse(row.resources["money"]) == SimNumber.parse(
            expected_money
        )
        previous_money = row.resources["money"]
        previous_cps = row.total_cps
    assert (
        first_half.result.timeline + second_half.result.timeline[1:]
        == continuous.result.timeline
    )


def test_weighted_manual_throw_behavior_replays_across_mid_action_checkpoint(
    tmp_path: Path,
) -> None:
    raw = ConfigLoader.load(
        "projects/fish/economy.yaml",
        "projects/fish/luban_exports",
    )
    model = ModelBuilder.build(raw)
    profile = model.player_profiles["default"]
    profile.behavior_weights = {"manual_throw": SimNumber.one()}
    profile.behavior_durations = {"manual_throw": {"type": "fixed", "seconds": 3}}
    simulator = FishEconomySimulator(
        model,
        _snapshot(tmp_path),
        model_digest="sha256:" + ("b" * 64),
    )

    continuous = simulator.run_scenario("smoke")
    first = simulator.run_scenario("smoke", until_seconds=5)
    resumed = simulator.run_scenario("smoke", first.checkpoint)

    def behavior_events(run):
        return [
            event for event in run.result.events if event.kind != "fish_engine_ready"
        ]

    assert behavior_events(first) + behavior_events(resumed) == (
        behavior_events(continuous)
    )
    assert (
        first.result.timeline + resumed.result.timeline[1:]
        == continuous.result.timeline
    )
    assert resumed.checkpoint.engine_state == continuous.checkpoint.engine_state
    assert resumed.checkpoint.behavior_state == (continuous.checkpoint.behavior_state)
    assert resumed.checkpoint.event_counters == (continuous.checkpoint.event_counters)
    assert first.checkpoint.behavior_state["active"] == {
        "sequence_id": 1,
        "profile_id": "default",
        "behavior_id": "manual_throw",
        "target_id": None,
        "duration_seconds": 3,
        "started_at_seconds": 3,
        "completes_at_seconds": 6,
    }


def test_upgrade_behavior_settles_old_income_before_level_change(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path)
    throw_config = ProductionThrowConfig.from_mapping(
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
        throw_config=throw_config,
    )
    state = PlayerState.new(
        initial_torpedo_id=1,
        initial_strength=50,
        initial_trash_man_realm_id=1,
    )
    resolution = throw_adapter.resolve(
        ProductionThrowRequest(
            root_random_seed=9,
            throw_id=0,
            strength=50,
            torpedo_id=1,
        )
    )
    state = apply_throw_resolution(
        state,
        resolution,
        adapter=throw_adapter,
        hall_adapter=hall_adapter,
    ).state
    state.wallet.money = BigNumberDTO.from_value("100")
    profile = ConfigLoader.load_rules_only(
        "projects/fish/economy.yaml"
    ).rules.player_profiles["default"]
    profile.behavior_weights = {"upgrade_fish": SimNumber.one()}
    profile.behavior_durations = {"upgrade_fish": {"type": "fixed", "seconds": 4}}
    profile.behavior_target_policies = {"upgrade_fish": "random_affordable"}
    decision = BehaviorScheduler(23).decide(
        adapter.candidates(state, profile),
        adapter.behavior_profile(profile),
        sequence_id=0,
        started_at_seconds=0,
    )
    old_income = hall_adapter.snapshot(state).total_income_per_second

    completion = adapter.complete(
        state,
        decision,
        root_random_seed=23,
        next_throw_id=1,
    )

    upgraded = completion.state.fish.items[0]
    price = hall_adapter.upgrade_price(state.fish.items[0])
    assert upgraded.level == 2
    assert completion.event_kind == "fish_upgraded"
    assert (
        completion.details["fish_hall_money_added"]
        == (old_income * SimNumber.parse(4)).to_decimal_string()
    )
    assert completion.state.wallet.money.to_sim_number() == (
        SimNumber.parse(100) + old_income * SimNumber.parse(4) - price
    )


def test_upgrade_behavior_requires_explicit_known_target_policy(
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
    profile.behavior_weights = {"upgrade_fish": SimNumber.one()}
    profile.behavior_durations = {"upgrade_fish": {"type": "fixed", "seconds": 1}}

    with pytest.raises(FishBehaviorConfigError, match="explicit target"):
        adapter.behavior_profile(profile)

    profile.behavior_target_policies = {"upgrade_fish": "highest_income"}
    with pytest.raises(FishBehaviorConfigError, match="unknown"):
        adapter.behavior_profile(profile)
