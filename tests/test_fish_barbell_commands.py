from __future__ import annotations

from pathlib import Path

import pytest

from fish_test_support import _snapshot
from igess.fish_barbell import FishBarbellDataAdapter
from igess.fish_commands import (
    FishCommandError,
    equip_barbell,
    settle_fish_hall_income,
    synthesize_barbell,
)
from igess.fish_data import FishDataError
from igess.fish_hall import FishHallDataAdapter
from igess.fish_production import settle_fish_production
from igess.fish_state import (
    BigNumberDTO,
    FishInstance,
    OwnedBarbell,
    PlayerState,
)
from igess.fish_trash import FishTrashDataAdapter
from igess.numbers import SimNumber


def test_barbell_adapter_uses_strength_per_exercise_and_time_cost(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path)
    snapshot.table("tbbarbell")[1].timeCost = 5
    adapter = FishBarbellDataAdapter(snapshot)

    assert adapter.synthesis_price(1) == SimNumber.parse(20)
    assert adapter.strength_per_second(1) == SimNumber.parse(2)
    assert adapter.strength_per_second(2) == SimNumber.parse(1)

    snapshot.table("tbbarbell")[0].timeCost = 0
    with pytest.raises(FishDataError, match="timeCost"):
        FishBarbellDataAdapter(snapshot)


def test_barbell_synthesis_atomically_pays_material_and_equips_best(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path)
    hall_adapter = FishHallDataAdapter(snapshot)
    barbell_adapter = FishBarbellDataAdapter(snapshot)
    state = PlayerState.new(initial_torpedo_id=1)
    state.wallet.material = BigNumberDTO.from_value(200)
    original = state.to_dict(context=hall_adapter.validation_context())

    first = synthesize_barbell(
        state,
        1,
        hall_adapter=hall_adapter,
        barbell_adapter=barbell_adapter,
    )

    assert state.to_dict(context=hall_adapter.validation_context()) == original
    assert first.state.wallet.material.to_sim_number() == SimNumber.parse(180)
    assert first.state.barbell.owned == [OwnedBarbell(1, 1)]
    assert first.state.barbell.equipped_id == 1
    assert first.state.meta.revision == 1
    assert first.production_after.strength_per_second == SimNumber.parse(2)

    second = synthesize_barbell(
        first.state,
        2,
        hall_adapter=hall_adapter,
        barbell_adapter=barbell_adapter,
    )

    assert second.state.wallet.material.to_sim_number() == SimNumber.parse(105)
    assert second.state.barbell.owned == [
        OwnedBarbell(1, 1),
        OwnedBarbell(2, 1),
    ]
    assert second.state.barbell.equipped_id == 2
    assert second.production_after.strength_per_second == SimNumber.parse(5)
    details = second.event_details()
    assert details["barbell_synthesis_price_resource"] == "material"
    assert details["barbell_auto_equip_policy"] == (
        "highest_strength_per_second"
    )
    assert details["barbell_equipped_id_after_synthesis"] == "2"
    assert details["barbell_owned_count_affects_output_after_synthesis"] == (
        "false"
    )


def test_barbell_synthesis_and_equip_failures_do_not_mutate_state(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path)
    hall_adapter = FishHallDataAdapter(snapshot)
    barbell_adapter = FishBarbellDataAdapter(snapshot)
    state = PlayerState.new(initial_torpedo_id=1)
    state.wallet.material = BigNumberDTO.from_value(19)
    original = state.to_dict(context=hall_adapter.validation_context())

    with pytest.raises(FishCommandError, match="insufficient material"):
        synthesize_barbell(
            state,
            1,
            hall_adapter=hall_adapter,
            barbell_adapter=barbell_adapter,
        )
    with pytest.raises(FishCommandError, match="not owned"):
        equip_barbell(
            state,
            1,
            hall_adapter=hall_adapter,
            barbell_adapter=barbell_adapter,
        )

    assert state.to_dict(context=hall_adapter.validation_context()) == original


def test_explicit_barbell_equip_changes_only_the_equipped_item(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path)
    hall_adapter = FishHallDataAdapter(snapshot)
    barbell_adapter = FishBarbellDataAdapter(snapshot)
    state = PlayerState.new(initial_torpedo_id=1)
    state.barbell.owned = [OwnedBarbell(1, 2), OwnedBarbell(2, 1)]
    state.barbell.equipped_id = 2
    original_owned = state.copy().barbell.owned

    application = equip_barbell(
        state,
        1,
        hall_adapter=hall_adapter,
        barbell_adapter=barbell_adapter,
    )

    assert application.state.barbell.equipped_id == 1
    assert application.state.barbell.owned == original_owned
    assert application.state.meta.revision == 1
    assert application.production_before.strength_per_second == (
        SimNumber.parse(5)
    )
    assert application.production_after.strength_per_second == (
        SimNumber.parse(2)
    )


def test_barbell_online_strength_is_part_of_unified_production_settlement(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path)
    hall_adapter = FishHallDataAdapter(snapshot)
    barbell_adapter = FishBarbellDataAdapter(snapshot)
    state = PlayerState.new(
        initial_torpedo_id=1,
        initial_strength=10,
        initial_trash_man_realm_id=1,
    )
    state.barbell.owned = [OwnedBarbell(1, 3)]
    state.barbell.equipped_id = 1

    settlement = settle_fish_production(
        state,
        5,
        hall_adapter=hall_adapter,
        trash_adapter=FishTrashDataAdapter(snapshot),
        barbell_adapter=barbell_adapter,
    )

    assert settlement.strength_added == SimNumber.parse(10)
    assert settlement.state.wallet.strength.to_sim_number() == (
        SimNumber.parse(20)
    )
    assert settlement.state.meta.revision == 1
    assert settlement.barbell.equipped_count == 3
    assert settlement.barbell.strength_per_second == SimNumber.parse(2)
    assert settlement.event_details()["barbell_strength_added"] == "10"
    assert (
        settlement.event_details()[
            "barbell_owned_count_affects_output_before_command"
        ]
        == "false"
    )


def test_fish_hall_income_settlement_is_atomic_and_traced(
    tmp_path: Path,
) -> None:
    hall_adapter = FishHallDataAdapter(_snapshot(tmp_path))
    state = PlayerState.new(initial_torpedo_id=1)
    state.wallet.money = state.wallet.money.from_value("5")
    state.fish.items = [
        FishInstance(1, 1, 7, 1, 100, 2),
        FishInstance(2, 2, 2, 1, 100, 1),
        FishInstance(3, 1, 7, 1, 100, 0),
    ]
    state.fish.next_instance_id = 4
    original = state.to_dict(context=hall_adapter.validation_context())

    settlement = settle_fish_hall_income(
        state,
        5,
        hall_adapter=hall_adapter,
    )

    assert state.to_dict(context=hall_adapter.validation_context()) == original
    assert settlement.money_added.to_decimal_string() == "110"
    assert settlement.state.wallet.money.to_sim_number().to_decimal_string() == "115"
    assert settlement.state.production.last_settled_at == 5
    assert settlement.state.meta.revision == 1
    details = settlement.event_details()
    assert details["fish_hall_settlement_elapsed_seconds"] == "5"
    assert details["fish_hall_income_per_second_before_throw"] == "22"
    assert (
        "base_money_per_second*1.25^(level-1)"
        in details["fish_hall_formula_trace_before_throw"]
    )
