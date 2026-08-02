from __future__ import annotations

from pathlib import Path

import pytest

from fish_test_support import _BigNumber, _snapshot
from igess.behavior import BehaviorDecision
from igess.fish_barbell import FishBarbellDataAdapter
from igess.fish_behavior import (
    HIGHEST_AFFORDABLE_POLICY_ID,
    PURCHASE_TORPEDO_BEHAVIOR_ID,
    FishBehaviorAdapter,
)
from igess.fish_commands import FishCommandError, purchase_torpedo
from igess.fish_hall import FishHallDataAdapter
from igess.fish_state import BigNumberDTO, PlayerState
from igess.fish_torpedo import FishTorpedoDataAdapter
from igess.fish_throw_data import (
    FishThrowDataAdapter,
    ProductionThrowConfig,
)
from igess.fish_trash import FishTrashDataAdapter
from igess.loader import ConfigLoader
from igess.numbers import SimNumber


def _adapters(tmp_path: Path):
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
    torpedo_adapter = FishTorpedoDataAdapter(
        snapshot,
        trash_luck_pools=throw_adapter.trash_luck_pools,
        regular_luck_multiplier=1,
    )
    behavior_adapter = FishBehaviorAdapter(
        throw_adapter=throw_adapter,
        hall_adapter=hall_adapter,
        trash_adapter=FishTrashDataAdapter(snapshot),
        barbell_adapter=FishBarbellDataAdapter(snapshot),
        throw_config=config,
    )
    return hall_adapter, torpedo_adapter, behavior_adapter


def test_torpedo_adapters_accept_generated_fixed_decimal_power(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path)
    snapshot.table("tbtorpedo")[1].power = _BigNumber(
        1,
        "316.22776601683796",
        0,
    )
    throw_adapter = FishThrowDataAdapter(
        snapshot,
        bonus_base_luck=1,
        max_bonus_layers=4,
    )

    torpedo_adapter = FishTorpedoDataAdapter(
        snapshot,
        trash_luck_pools=throw_adapter.trash_luck_pools,
        regular_luck_multiplier=1,
    )

    assert throw_adapter.torpedo(2).power == pytest.approx(
        316.22776601683796
    )
    assert torpedo_adapter.rule(2).power.to_float() == pytest.approx(
        316.22776601683796
    )


def test_torpedo_purchase_uses_only_price_and_selects_stronger_torpedo(
    tmp_path: Path,
) -> None:
    hall_adapter, torpedo_adapter, _ = _adapters(tmp_path)
    state = PlayerState.new(
        initial_torpedo_id=1,
        initial_strength=0,
        initial_trash_man_realm_id=1,
    )
    state.wallet.material = BigNumberDTO.from_value(100)
    state.wallet.money = BigNumberDTO.from_value(999)

    application = purchase_torpedo(
        state,
        2,
        hall_adapter=hall_adapter,
        torpedo_adapter=torpedo_adapter,
    )

    assert state.torpedo.selected_id == 1
    assert application.state.torpedo.selected_id == 2
    assert application.state.torpedo.owned_ids == [1, 2]
    assert application.state.wallet.material.to_sim_number().is_zero()
    assert application.state.wallet.money.to_sim_number() == SimNumber.parse(999)
    assert application.event_details()["torpedo_purchase_price_resource"] == (
        "material"
    )
    assert application.trash_luck_after > application.trash_luck_before
    assert application.event_details()["torpedo_purchase_price"] == "100"
    assert application.event_details()["trash_luck"] == format(
        application.trash_luck_after,
        ".17g",
    )


def test_torpedo_behavior_targets_highest_affordable_without_strength_gate(
    tmp_path: Path,
) -> None:
    _, _, adapter = _adapters(tmp_path)
    profile = ConfigLoader.load_rules_only(
        "projects/fish/economy.yaml"
    ).rules.player_profiles["default"]
    profile.behavior_weights = {
        PURCHASE_TORPEDO_BEHAVIOR_ID: SimNumber.one()
    }
    profile.behavior_durations = {
        PURCHASE_TORPEDO_BEHAVIOR_ID: {
            "type": "fixed",
            "seconds": 1,
        }
    }
    profile.behavior_target_policies = {
        PURCHASE_TORPEDO_BEHAVIOR_ID: HIGHEST_AFFORDABLE_POLICY_ID
    }
    state = PlayerState.new(
        initial_torpedo_id=1,
        initial_strength=0,
        initial_trash_man_realm_id=1,
    )
    state.wallet.material = BigNumberDTO.from_value(1_000)

    adapter.behavior_profile(profile)
    candidate = adapter.candidates(state, profile)[0]

    assert candidate.available
    assert [target.target_id for target in candidate.targets] == ["3"]
    completion = adapter.complete(
        state,
        BehaviorDecision(
            sequence_id=0,
            profile_id=profile.id,
            behavior_id=PURCHASE_TORPEDO_BEHAVIOR_ID,
            target_id="3",
            duration_seconds=1,
            started_at_seconds=0,
            completes_at_seconds=1,
        ),
        root_random_seed=7,
        next_throw_id=0,
    )
    assert completion.event_kind == "torpedo_purchased"
    assert completion.state.torpedo.selected_id == 3
    assert completion.details["material_after_torpedo_purchase"] == "0"


def test_torpedo_purchase_rejects_unaffordable_or_owned_target(
    tmp_path: Path,
) -> None:
    hall_adapter, torpedo_adapter, _ = _adapters(tmp_path)
    state = PlayerState.new(
        initial_torpedo_id=1,
        initial_trash_man_realm_id=1,
    )

    with pytest.raises(FishCommandError, match="insufficient material"):
        purchase_torpedo(
            state,
            2,
            hall_adapter=hall_adapter,
            torpedo_adapter=torpedo_adapter,
        )
    with pytest.raises(FishCommandError, match="already owned"):
        purchase_torpedo(
            state,
            1,
            hall_adapter=hall_adapter,
            torpedo_adapter=torpedo_adapter,
        )
