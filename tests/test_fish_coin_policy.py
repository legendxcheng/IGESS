from __future__ import annotations

from pathlib import Path

import pytest

from fish_test_support import _snapshot
from igess.fish_barbell import FishBarbellDataAdapter
from igess.fish_behavior import FishBehaviorAdapter
from igess.fish_hall import FishHallDataAdapter
from igess.fish_state import OwnedBarbell, BigNumberDTO, FishInstance, PlayerState
from igess.fish_throw_data import FishThrowDataAdapter, ProductionThrowConfig
from igess.fish_trash import FishTrashDataAdapter
from igess.loader import ConfigLoader
from igess.numbers import SimNumber


def setup_policy(tmp_path: Path, *, cached: bool = False, next_price: int = 75):
    snapshot = _snapshot(tmp_path)
    snapshot.table("tbbarbell")[1].price = next_price
    profile = ConfigLoader.load_rules_only("projects/fish/economy.yaml").rules.player_profiles["default"]
    profile.behavior_weights = {"upgrade_fish": SimNumber.one(), "synthesize_barbell": SimNumber.one()}
    profile.behavior_target_policies = {
        "upgrade_fish": "deployed_quality_lowest_level",
        "synthesize_barbell": "cheapest_improvement",
    }
    hall = FishHallDataAdapter(snapshot)
    adapter = FishBehaviorAdapter(
        throw_adapter=FishThrowDataAdapter(snapshot, bonus_base_luck=1, max_bonus_layers=4),
        hall_adapter=hall,
        trash_adapter=FishTrashDataAdapter(snapshot),
        barbell_adapter=FishBarbellDataAdapter(snapshot),
        throw_config=ProductionThrowConfig(50, 1, 1, 1, 4),
        _validate_state=not cached,
    )
    state = PlayerState.new(initial_torpedo_id=1, initial_trash_man_realm_id=1)
    state.wallet.money = BigNumberDTO.from_value("1e40")
    state.barbell.owned = [OwnedBarbell(1, 1), OwnedBarbell(2, 1)]
    state.barbell.equipped_id = 2
    return adapter, hall, state, profile


def deploy(hall, state, items):
    state.fish.items = items
    state.fish.next_instance_id = max((item.instance_id for item in items), default=0) + 1
    layout = hall.expected_layout(state)
    for item in items:
        item.hall_slot = layout.get(item.instance_id, 0)


def upgrade_candidate(adapter, state, profile):
    adapter.behavior_profile(profile)
    return next(c for c in adapter.candidates(state, profile) if c.behavior_id == "upgrade_fish")


def test_quality_group_upgrades_lowest_level_deployed_fish(tmp_path: Path) -> None:
    adapter, hall, state, profile = setup_policy(tmp_path)
    deploy(hall, state, [
        FishInstance(1, 101, 2, 4, 100, 0),
        FishInstance(2, 101, 7, 2, 100, 0),
        FishInstance(3, 201, 7, 1, 100, 0),
    ])
    candidate = upgrade_candidate(adapter, state, profile)
    assert candidate.available
    assert [target.target_id for target in candidate.targets] == ["2"]


@pytest.mark.parametrize("price,allowed", [(75, False), (80, False), (81, True)])
def test_upgrade_must_strictly_shorten_barbell_wait(tmp_path: Path, price: int, allowed: bool) -> None:
    adapter, hall, state, profile = setup_policy(tmp_path, next_price=price)
    state.wallet.money = BigNumberDTO.from_value(10)
    state.barbell.owned = [OwnedBarbell(1, 1)]
    state.barbell.equipped_id = 1
    deploy(hall, state, [FishInstance(1, 101, 7, 1, 100, 0)])
    # 10 coins/s, upgrade costs 10, adds 2.5/s after three seconds.
    # At K=80 both paths reach the barbell at exactly seven seconds.
    assert upgrade_candidate(adapter, state, profile).available is allowed


def test_affordable_target_barbell_prevents_fish_spending(tmp_path: Path) -> None:
    adapter, hall, state, profile = setup_policy(tmp_path)
    state.barbell.owned = [OwnedBarbell(1, 1)]
    state.barbell.equipped_id = 1
    deploy(hall, state, [FishInstance(1, 101, 7, 1, 100, 0)])
    candidates = {c.behavior_id: c for c in adapter.candidates(state, profile)}
    assert not candidates["upgrade_fish"].available
    assert [t.target_id for t in candidates["synthesize_barbell"].targets] == ["2"]


@pytest.mark.parametrize("cached", [False, True])
def test_undeployed_high_quality_fish_does_not_block_intersection(tmp_path: Path, cached: bool) -> None:
    adapter, hall, state, profile = setup_policy(tmp_path, cached=cached)
    deploy(hall, state, [
        FishInstance(1, 101, 7, 10, 100, 0),
        FishInstance(2, 101, 2, 1, 100, 0),
        FishInstance(3, 101, 7, 3, 100, 0),
    ])
    # Top quality contains 2 and 1. Only 1 is deployed; cheaper deployed 3
    # is outside that group and must not be used as a replacement.
    candidate = upgrade_candidate(adapter, state, profile)
    assert [t.target_id for t in candidate.targets] == ["1"]
    state.wallet.money = BigNumberDTO.from_value(25)
    assert not upgrade_candidate(adapter, state, profile).available


@pytest.mark.parametrize("cached", [False, True])
def test_same_quality_retains_investment_and_recomputes_after_capacity_change(tmp_path: Path, cached: bool) -> None:
    adapter, hall, state, profile = setup_policy(tmp_path, cached=cached)
    deploy(hall, state, [
        FishInstance(3, 101, 7, 1, 100, 0),
        FishInstance(2, 101, 7, 2, 100, 0),
        FishInstance(1, 101, 7, 2, 100, 0),
    ])
    assert [t.target_id for t in upgrade_candidate(adapter, state, profile).targets] == ["1"]
    state.fish_hall.upgrade_level = 1
    deploy(hall, state, state.fish.items)
    assert [t.target_id for t in upgrade_candidate(adapter, state, profile).targets] == ["3"]


def test_max_level_group_does_not_admit_lower_quality_replacements(tmp_path: Path) -> None:
    adapter, hall, state, profile = setup_policy(tmp_path)
    deploy(hall, state, [
        FishInstance(1, 101, 2, 100, 100, 0),
        FishInstance(2, 101, 7, 100, 100, 0),
        FishInstance(3, 201, 7, 1, 100, 0),
    ])
    assert not upgrade_candidate(adapter, state, profile).available
    deploy(hall, state, [])
    assert not upgrade_candidate(adapter, state, profile).available


def test_equal_level_uses_quality_then_saves_for_selected_target(tmp_path: Path) -> None:
    adapter, hall, state, profile = setup_policy(tmp_path)
    deploy(hall, state, [FishInstance(1, 101, 7, 1, 100, 0), FishInstance(2, 101, 2, 1, 100, 0)])
    assert [t.target_id for t in upgrade_candidate(adapter, state, profile).targets] == ["2"]
    state.wallet.money = BigNumberDTO.from_value(10)
    assert not upgrade_candidate(adapter, state, profile).available
    state.wallet.money = BigNumberDTO.from_value(15)
    assert upgrade_candidate(adapter, state, profile).available


def test_reward_multiplier_affects_saving_estimate_but_not_price(tmp_path: Path) -> None:
    adapter, hall, state, profile = setup_policy(tmp_path, next_price=90)
    state.wallet.money = BigNumberDTO.from_value(10)
    state.barbell.owned = [OwnedBarbell(1, 1)]
    state.barbell.equipped_id = 1
    deploy(hall, state, [FishInstance(1, 101, 7, 1, 100, 0)])
    assert upgrade_candidate(adapter, state, profile).available
    # Faster gross income makes the same upgrade postpone an already close purchase.
    profile.source_efficiency["fish_hall_money"] = SimNumber.parse(2)
    assert not upgrade_candidate(adapter, state, profile).available
    assert hall.upgrade_price(state.fish.items[0]) == SimNumber.parse(10)
    profile.source_efficiency["fish_hall_money"] = SimNumber.zero()
    assert not upgrade_candidate(adapter, state, profile).available


def test_no_useful_barbell_removes_wait_gate(tmp_path: Path) -> None:
    adapter, hall, state, profile = setup_policy(tmp_path)
    deploy(hall, state, [FishInstance(1, 101, 7, 1, 100, 0)])
    profile.source_efficiency["fish_hall_money"] = SimNumber.zero()
    assert upgrade_candidate(adapter, state, profile).available
