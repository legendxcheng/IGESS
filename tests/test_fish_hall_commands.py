from __future__ import annotations

from pathlib import Path

import pytest

from fish_test_support import _BigNumber, _big, _snapshot
from igess.fish_commands import (
    FishCommandError,
    apply_fish_hall_upgrade,
    apply_strength_rebirth,
    upgrade_fish,
)
from igess.fish_data import FishDataError
from igess.fish_hall import FishHallDataAdapter
from igess.fish_state import (
    BigNumberDTO,
    FishInstance,
    PlayerState,
    TrashStock,
)
from igess.numbers import SimNumber


def test_max_income_layout_uses_capacity_income_and_stable_ties(
    tmp_path: Path,
) -> None:
    hall_adapter = FishHallDataAdapter(_snapshot(tmp_path))
    state = PlayerState.new(initial_torpedo_id=1)
    state.fish.items = [
        FishInstance(1, 1, 7, 1, 100, 0),
        FishInstance(2, 2, 2, 1, 100, 0),
        FishInstance(3, 1, 7, 1, 100, 0),
    ]
    state.fish.next_instance_id = 4

    assert hall_adapter.capacity(0) == 2
    assert hall_adapter.capacity(1) == 3
    assert hall_adapter.expected_layout(state) == {2: 1, 1: 2}

    for item in state.fish.items:
        item.hall_slot = hall_adapter.expected_layout(state).get(
            item.instance_id,
            0,
        )
    snapshot = hall_adapter.snapshot(state)

    assert snapshot.deployed_instance_ids == (2, 1)
    assert snapshot.total_income_per_second.to_decimal_string() == "22"
    assert [
        trace.income_per_second.to_decimal_string() for trace in snapshot.traces
    ] == [
        "12",
        "10",
    ]
    assert state.fish.items[2].hall_slot == 0

    state.rebirth.strength_completed_count = 1
    reborn_snapshot = hall_adapter.snapshot(state)
    assert reborn_snapshot.base_total_income_per_second == SimNumber.parse(22)
    assert reborn_snapshot.strength_rebirth_multiplier == SimNumber.parse(2)
    assert reborn_snapshot.total_income_per_second == SimNumber.parse(44)
    assert (
        reborn_snapshot.event_details()[
            "strength_rebirth_fish_hall_multiplier_source"
        ]
        == "tbstrengthrebirth[id=1].fishHallOutputMultiplier"
    )


def test_fish_level_price_and_income_formulas_use_bignumber(
    tmp_path: Path,
) -> None:
    hall_adapter = FishHallDataAdapter(_snapshot(tmp_path))
    normal = FishInstance(1, 1, 7, 1, 100, 0)
    upgraded = FishInstance(1, 1, 7, 2, 100, 0)
    mutated = FishInstance(1, 1, 2, 3, 100, 0)

    assert hall_adapter.upgrade_price(normal).to_decimal_string() == "10"
    assert hall_adapter.upgrade_price(upgraded).to_decimal_string() == "15"
    assert (
        hall_adapter.upgrade_price(FishInstance(1, 1, 2, 2, 100, 0)).to_decimal_string()
        == "15"
    )
    assert (
        hall_adapter.income_trace(upgraded).income_per_second.to_decimal_string()
        == "12.5"
    )
    mutation_trace = hall_adapter.income_trace(mutated)
    assert mutation_trace.level_income_multiplier.to_decimal_string() == "1.5625"
    assert mutation_trace.level_money_per_second.to_decimal_string() == "15.625"
    assert mutation_trace.mutation_income_multiplier.to_decimal_string() == "1.5"
    assert mutation_trace.income_per_second.to_decimal_string() == "23.4375"
    assert (
        mutation_trace.event_entry()["formula"]
        == "base_money_per_second*1.25^(level-1)*mutation_income_multiplier"
    )

    at_cap = FishInstance(1, 1, 7, 100, 100, 0)
    with pytest.raises(FishDataError, match="already at max level"):
        hall_adapter.upgrade_price(at_cap)


def test_fish_upgrade_atomically_pays_levels_and_reorders_hall(
    tmp_path: Path,
) -> None:
    hall_adapter = FishHallDataAdapter(_snapshot(tmp_path))
    state = PlayerState.new(initial_torpedo_id=1)
    state.wallet.money = state.wallet.money.from_value("100")
    state.fish.items = [
        FishInstance(1, 1, 7, 1, 100, 2),
        FishInstance(2, 2, 2, 1, 100, 1),
    ]
    state.fish.next_instance_id = 3
    original = state.to_dict(context=hall_adapter.validation_context())

    application = upgrade_fish(state, 1, hall_adapter=hall_adapter)

    assert state.to_dict(context=hall_adapter.validation_context()) == original
    assert application.from_level == 1
    assert application.to_level == 2
    assert application.price.to_decimal_string() == "10"
    assert application.money_before.to_decimal_string() == "100"
    assert application.money_after.to_decimal_string() == "90"
    assert application.income_before.income_per_second.to_decimal_string() == "10"
    assert application.income_after.income_per_second.to_decimal_string() == "12.5"
    assert application.state.wallet.money.to_sim_number() == SimNumber.parse("90")
    assert application.state.fish.items[0].level == 2
    assert application.state.fish.items[0].hall_slot == 1
    assert application.state.fish.items[1].hall_slot == 2
    assert application.state.meta.revision == 1
    details = application.event_details()
    assert details["fish_upgrade_price_formula"] == (
        "base_money_per_second*1.5^(current_level-1)"
    )
    assert details["fish_upgrade_price_uses_mutation"] == "false"
    assert details["fish_income_formula"] == (
        "base_money_per_second*1.25^(level-1)*mutation_income_multiplier"
    )
    assert details["fish_hall_deployed_instance_ids_after_upgrade"] == "[1,2]"


def test_fish_upgrade_rejects_insufficient_money_without_mutation(
    tmp_path: Path,
) -> None:
    hall_adapter = FishHallDataAdapter(_snapshot(tmp_path))
    state = PlayerState.new(initial_torpedo_id=1)
    state.wallet.money = state.wallet.money.from_value("9")
    state.fish.items = [FishInstance(1, 1, 7, 1, 100, 1)]
    state.fish.next_instance_id = 2
    original = state.to_dict(context=hall_adapter.validation_context())

    with pytest.raises(FishCommandError, match="insufficient money"):
        upgrade_fish(state, 1, hall_adapter=hall_adapter)

    assert state.to_dict(context=hall_adapter.validation_context()) == original


def test_hall_upgrade_uses_current_row_price_and_last_row_is_max(
    tmp_path: Path,
) -> None:
    hall_adapter = FishHallDataAdapter(_snapshot(tmp_path))

    assert hall_adapter.can_upgrade_hall(0) is True
    assert hall_adapter.hall_upgrade_price(0) == SimNumber.parse(100)
    assert hall_adapter.can_upgrade_hall(1) is False
    with pytest.raises(FishDataError, match="already at max"):
        hall_adapter.hall_upgrade_price(1)


def test_hall_upgrade_rejects_zero_price_in_a_purchasable_row(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path)
    snapshot.table("tbfishhallupgrade")[0].upgradePrice = _big(0)

    with pytest.raises(
        FishDataError,
        match=r"tbfishhallupgrade\.0\.upgradePrice",
    ):
        FishHallDataAdapter(snapshot)


def test_hall_upgrade_requires_zero_final_price_and_increasing_capacity(
    tmp_path: Path,
) -> None:
    nonzero_final = _snapshot(tmp_path)
    nonzero_final.table("tbfishhallupgrade")[-1].upgradePrice = _big(1)
    with pytest.raises(FishDataError, match="max-level sentinel"):
        FishHallDataAdapter(nonzero_final)

    flat_capacity = _snapshot(tmp_path)
    flat_capacity.table("tbfishhallupgrade")[-1].slotQty = 2
    with pytest.raises(FishDataError, match="strictly increasing"):
        FishHallDataAdapter(flat_capacity)


def test_strength_rebirth_uses_implicit_one_x_then_one_based_table_rows(
    tmp_path: Path,
) -> None:
    adapter = FishHallDataAdapter(_snapshot(tmp_path))

    assert adapter.max_strength_rebirth_count == 2
    assert adapter.strength_rebirth_multiplier(0) == SimNumber.one()
    first = adapter.next_strength_rebirth_rule(0)
    assert first.completed_count == 1
    assert first.strength_requirement == SimNumber.parse(1000)
    assert first.fish_hall_output_multiplier == SimNumber.parse(2)
    assert adapter.strength_rebirth_multiplier(1) == SimNumber.parse(2)
    second = adapter.next_strength_rebirth_rule(1)
    assert second.completed_count == 2
    assert second.strength_requirement == SimNumber.parse(10000)
    assert second.fish_hall_output_multiplier == SimNumber.parse(3)
    assert adapter.strength_rebirth_multiplier(2) == SimNumber.parse(3)

    with pytest.raises(FishDataError, match="default 1x"):
        adapter.strength_rebirth_rule(0)
    with pytest.raises(FishDataError, match="already at max"):
        adapter.next_strength_rebirth_rule(2)

    zero_based = _snapshot(tmp_path)
    zero_based.table("tbstrengthrebirth")[0].id = 0
    with pytest.raises(FishDataError, match="positive integer"):
        FishHallDataAdapter(zero_based)


def test_strength_rebirth_resets_only_strength_and_applies_hall_multiplier(
    tmp_path: Path,
) -> None:
    adapter = FishHallDataAdapter(_snapshot(tmp_path))
    state = PlayerState.new(
        initial_torpedo_id=1,
        initial_strength=1500,
        initial_trash_man_realm_id=1,
    )
    state.wallet.money = BigNumberDTO.from_value(123)
    state.wallet.material = BigNumberDTO.from_value(456)
    state.fish.items = [FishInstance(1, 1, 7, 1, 100, 1)]
    state.fish.next_instance_id = 2
    state.trash_man.processing.stocks = [TrashStock(1, 2)]
    before = state.to_dict(context=adapter.validation_context())

    application = apply_strength_rebirth(state, hall_adapter=adapter)

    assert state.to_dict(context=adapter.validation_context()) == before
    committed = application.state
    assert application.from_completed_count == 0
    assert application.to_completed_count == 1
    assert application.strength_requirement == SimNumber.parse(1000)
    assert application.strength_before == SimNumber.parse(1500)
    assert application.strength_after == SimNumber.zero()
    assert committed.wallet.strength.to_sim_number() == SimNumber.zero()
    assert committed.rebirth.strength_completed_count == 1
    assert committed.meta.revision == state.meta.revision + 1
    assert application.fish_hall_before.total_income_per_second == (
        SimNumber.parse(10)
    )
    assert application.fish_hall_after.base_total_income_per_second == (
        SimNumber.parse(10)
    )
    assert application.fish_hall_after.total_income_per_second == (
        SimNumber.parse(20)
    )
    after = committed.to_dict(context=adapter.validation_context())
    for field in (
        "fish",
        "trashMan",
        "wallet",
        "torpedo",
        "barbell",
        "fishHall",
        "collection",
        "automation",
        "statistics",
        "production",
    ):
        if field == "wallet":
            assert after[field]["money"] == before[field]["money"]
            assert after[field]["material"] == before[field]["material"]
        else:
            assert after[field] == before[field]
    details = application.event_details()
    assert details["strength_rebirth_table_id"] == "1"
    assert details["strength_rebirth_multiplier_before"] == "1"
    assert details["strength_rebirth_multiplier_after"] == "2"
    assert details["strength_rebirth_reset_fields"] == "wallet.strength"


def test_strength_rebirth_rejects_insufficient_strength_and_max_count_atomically(
    tmp_path: Path,
) -> None:
    adapter = FishHallDataAdapter(_snapshot(tmp_path))
    insufficient = PlayerState.new(
        initial_torpedo_id=1,
        initial_strength=999,
        initial_trash_man_realm_id=1,
    )
    insufficient_before = insufficient.to_dict(
        context=adapter.validation_context()
    )

    with pytest.raises(FishCommandError, match="insufficient strength"):
        apply_strength_rebirth(insufficient, hall_adapter=adapter)
    assert insufficient.to_dict(
        context=adapter.validation_context()
    ) == insufficient_before

    maxed = insufficient.copy()
    maxed.wallet.strength = BigNumberDTO.from_value("1e100")
    maxed.rebirth.strength_completed_count = 2
    maxed_before = maxed.to_dict(context=adapter.validation_context())
    with pytest.raises(FishCommandError, match="already at max"):
        apply_strength_rebirth(maxed, hall_adapter=adapter)
    assert maxed.to_dict(context=adapter.validation_context()) == maxed_before


def test_fish_hall_upgrade_atomically_pays_material_and_expands_layout(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path)
    snapshot.table("tbfishhallupgrade")[0].upgradePrice = _BigNumber(
        1,
        "125",
        -1,
    )
    hall_adapter = FishHallDataAdapter(snapshot)
    state = PlayerState.new(initial_torpedo_id=1)
    state.wallet.material = BigNumberDTO.from_value("12.75")
    state.fish.items = [
        FishInstance(1, 1, 7, 1, 100, 2),
        FishInstance(2, 2, 2, 1, 100, 1),
        FishInstance(3, 1, 7, 1, 100, 0),
    ]
    state.fish.next_instance_id = 4
    original = state.to_dict(context=hall_adapter.validation_context())

    application = apply_fish_hall_upgrade(
        state,
        hall_adapter=hall_adapter,
    )

    assert state.to_dict(context=hall_adapter.validation_context()) == original
    assert application.from_level == 0
    assert application.to_level == 1
    assert application.price == SimNumber.parse("12.5")
    assert application.material_before == SimNumber.parse("12.75")
    assert application.material_after == SimNumber.parse("0.25")
    assert application.state.wallet.material.to_sim_number() == (
        SimNumber.parse("0.25")
    )
    assert application.state.fish_hall.upgrade_level == 1
    assert application.fish_hall_before.capacity == 2
    assert application.fish_hall_after.capacity == 3
    assert application.fish_hall_before.deployed_instance_ids == (2, 1)
    assert application.fish_hall_after.deployed_instance_ids == (2, 1, 3)
    assert [item.hall_slot for item in application.state.fish.items] == [2, 1, 3]
    assert application.state.meta.revision == 1
    details = application.event_details()
    assert details["fish_hall_upgrade_price"] == "12.5"
    assert details["fish_hall_upgrade_price_resource"] == "material"
    assert details["fish_hall_upgrade_price_source"] == (
        "tbfishhallupgrade[current_upgrade_level].upgradePrice"
    )
    assert details["fish_hall_upgrade_max_level"] == "1"
    assert details["fish_hall_upgrade_layout_policy"] == "fixed_max_income"
    assert details["fish_hall_capacity_before_hall_upgrade"] == "2"
    assert details["fish_hall_capacity_after_hall_upgrade"] == "3"
    assert details["fish_hall_deployed_instance_ids_after_hall_upgrade"] == (
        "[2,1,3]"
    )
    assert details["player_state_revision"] == "1"


@pytest.mark.parametrize(
    ("material", "upgrade_level", "message"),
    [
        ("99", 0, "insufficient material"),
        ("1000", 1, "already at max"),
    ],
)
def test_fish_hall_upgrade_failure_does_not_mutate_state(
    tmp_path: Path,
    material: str,
    upgrade_level: int,
    message: str,
) -> None:
    hall_adapter = FishHallDataAdapter(_snapshot(tmp_path))
    state = PlayerState.new(initial_torpedo_id=1)
    state.wallet.material = BigNumberDTO.from_value(material)
    state.fish_hall.upgrade_level = upgrade_level
    state.fish.items = [FishInstance(1, 1, 7, 1, 100, 1)]
    state.fish.next_instance_id = 2
    original = state.to_dict(context=hall_adapter.validation_context())

    with pytest.raises(FishCommandError, match=message):
        apply_fish_hall_upgrade(state, hall_adapter=hall_adapter)

    assert state.to_dict(context=hall_adapter.validation_context()) == original
