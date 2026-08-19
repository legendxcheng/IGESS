from __future__ import annotations

from pathlib import Path

import pytest

from fish_test_support import _snapshot
from igess.builder import ModelBuilder
from igess.fish_barbell import FishBarbellDataAdapter
from igess.fish_hall import FishHallDataAdapter
from igess.fish_production import settle_fish_production
from igess.fish_rewards import FishRewardMultipliers
from igess.fish_state import (
    FishInstance,
    OwnedBarbell,
    PlayerState,
    TrashStock,
)
from igess.fish_trash import FishTrashDataAdapter
from igess.linter import ConfigLinter
from igess.loader import ConfigLoader
from igess.numbers import SimNumber


def test_fish_profiles_load_distinct_reward_multipliers() -> None:
    raw = ConfigLoader.load_rules_only("projects/fish/economy.yaml")
    ConfigLinter.validate(raw)
    model = ModelBuilder.build(raw)

    free = FishRewardMultipliers.from_profile(
        model.player_profiles["default"]
    )
    paid = FishRewardMultipliers.from_profile(
        model.player_profiles["paid_20pct"]
    )

    assert free.manifest_parameters() == {
        "fish_hall_money": "1",
        "trash_material": "1",
        "barbell_strength": "1",
    }
    assert paid.manifest_parameters() == {
        "fish_hall_money": "1.2",
        "trash_material": "1.2",
        "barbell_strength": "1.2",
    }


def test_profile_reward_multipliers_compose_with_fish_production(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path, trash_duration=10)
    state = PlayerState.new(
        initial_torpedo_id=1,
        initial_strength=10,
        initial_trash_man_realm_id=1,
    )
    state.fish.items = [FishInstance(1, 101, 7, 1, 100, 1)]
    state.fish.next_instance_id = 2
    state.trash_man.processing.active_trash_id = 1
    state.trash_man.processing.stocks = [
        TrashStock(trash_id=1, count=1)
    ]
    state.barbell.owned = [OwnedBarbell(1, 1)]
    state.barbell.equipped_id = 1

    settlement = settle_fish_production(
        state,
        1,
        hall_adapter=FishHallDataAdapter(snapshot),
        trash_adapter=FishTrashDataAdapter(snapshot),
        barbell_adapter=FishBarbellDataAdapter(snapshot),
        barbell_training_active=True,
        reward_multipliers=FishRewardMultipliers(
            fish_hall_money=SimNumber.parse("1.5"),
            trash_material=SimNumber.parse("2"),
            barbell_strength=SimNumber.parse("3"),
        ),
    )

    assert settlement.money_base_added == SimNumber.parse(10)
    assert settlement.money_added == SimNumber.parse(15)
    assert settlement.material_base_added == SimNumber.parse(2)
    assert settlement.material_added == SimNumber.parse(4)
    assert settlement.strength_base_added == SimNumber.parse(2)
    assert settlement.strength_added == SimNumber.parse(6)
    assert settlement.state.wallet.money.to_sim_number() == SimNumber.parse(15)
    assert settlement.state.wallet.material.to_sim_number() == SimNumber.parse(4)
    assert settlement.state.wallet.strength.to_sim_number() == SimNumber.parse(16)
    details = settlement.event_details()
    assert details["fish_hall_money_reward_multiplier"] == "1.5"
    assert details["trash_material_reward_multiplier"] == "2"
    assert details["barbell_strength_reward_multiplier"] == "3"


def test_fish_reward_multipliers_reject_negative_values() -> None:
    with pytest.raises(ValueError, match="must be non-negative"):
        FishRewardMultipliers(trash_material=SimNumber.parse("-0.1"))
