from __future__ import annotations

from pathlib import Path

import pytest

from fish_test_support import _snapshot
from igess.fish_command_results import FishCommandError
from igess.fish_commands import apply_trash_man_rebirth
from igess.fish_data import FishDataError
from igess.fish_hall import FishHallDataAdapter
from igess.fish_production import settle_fish_production
from igess.fish_state import BigNumberDTO, PlayerState, TrashStock
from igess.fish_trash import FishTrashDataAdapter
from igess.numbers import SimNumber


def test_trash_man_rebirth_uses_one_based_rows_and_implicit_one_x(
    tmp_path: Path,
) -> None:
    adapter = FishTrashDataAdapter(_snapshot(tmp_path))

    assert adapter.max_trash_man_rebirth_count == 2
    assert adapter.material_output_multiplier(0) == SimNumber.one()
    first = adapter.next_trash_man_rebirth_rule(0)
    assert first.completed_count == 1
    assert first.realm_requirement == 0
    assert first.material_output_multiplier == SimNumber.parse(2)
    assert adapter.material_output_multiplier(1) == SimNumber.parse(2)
    second = adapter.next_trash_man_rebirth_rule(1)
    assert second.completed_count == 2
    assert second.realm_requirement == 4
    assert second.material_output_multiplier == SimNumber.parse(3)
    assert adapter.material_output_multiplier(2) == SimNumber.parse(3)

    with pytest.raises(FishDataError, match="default 1x"):
        adapter.trash_man_rebirth_rule(0)
    with pytest.raises(FishDataError, match="already at max"):
        adapter.next_trash_man_rebirth_rule(2)

    zero_based = _snapshot(tmp_path)
    zero_based.table("tbtrashmanrebirth")[0].id = 0
    with pytest.raises(FishDataError, match="positive integer"):
        FishTrashDataAdapter(zero_based)

    noncontiguous = _snapshot(tmp_path)
    noncontiguous.table("tbtrashmanrebirth")[1].id = 3
    with pytest.raises(FishDataError, match="contiguous and start at 1"):
        FishTrashDataAdapter(noncontiguous)


def test_trash_man_rebirth_resets_realm_and_keeps_permanent_state(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path, trash_duration=10)
    trash_adapter = FishTrashDataAdapter(snapshot)
    hall_adapter = FishHallDataAdapter(snapshot)
    state = PlayerState.new(
        initial_torpedo_id=1,
        initial_strength=50,
        initial_trash_man_realm_id=3,
    )
    state.wallet.money = BigNumberDTO.from_value(123)
    state.wallet.material = BigNumberDTO.from_value(456)
    state.trash_man.training_progress_seconds = 7
    state.trash_man.processing.active_trash_id = 1
    state.trash_man.processing.stocks = [TrashStock(1, 2)]
    before = state.to_dict(context=hall_adapter.validation_context())

    application = apply_trash_man_rebirth(
        state,
        trash_adapter=trash_adapter,
    )

    assert state.to_dict(context=hall_adapter.validation_context()) == before
    committed = application.state
    assert application.from_completed_count == 0
    assert application.to_completed_count == 1
    assert application.realm_requirement == 0
    assert application.realm_before == 3
    assert application.realm_after == 1
    assert application.highest_realm_id == 3
    assert application.material_multiplier_before == SimNumber.one()
    assert application.material_multiplier_after == SimNumber.parse(2)
    assert committed.trash_man.realm_id == 1
    assert committed.trash_man.highest_realm_id == 3
    assert committed.trash_man.training_progress_seconds == 0
    assert committed.trash_man.processing == state.trash_man.processing
    assert committed.rebirth.trash_man_completed_count == 1
    assert committed.rebirth.strength_completed_count == 0
    assert committed.wallet == state.wallet
    assert committed.meta.revision == state.meta.revision + 1

    details = application.event_details()
    assert details["trash_man_rebirth_table_id"] == "1"
    assert details["trash_man_rebirth_realm_requirement"] == "0"
    assert details["trash_man_rebirth_realm_before"] == "3"
    assert details["trash_man_rebirth_realm_after"] == "1"
    assert details["trash_man_rebirth_highest_realm_preserved"] == "3"
    assert details["trash_man_rebirth_material_multiplier_before"] == "1"
    assert details["trash_man_rebirth_material_multiplier_after"] == "2"

    chased = settle_fish_production(
        committed,
        1,
        hall_adapter=hall_adapter,
        trash_adapter=trash_adapter,
    )
    assert chased.state.trash_man.realm_id == 3
    assert chased.state.trash_man.highest_realm_id == 3
    assert chased.material_added == SimNumber.parse(5)
    assert chased.trash_processing.transitions[0].from_realm_id == 1
    assert chased.trash_processing.transitions[-1].to_realm_id == 3


def test_trash_man_rebirth_rejects_requirement_breakthrough_and_max_atomically(
    tmp_path: Path,
) -> None:
    adapter = FishTrashDataAdapter(_snapshot(tmp_path))
    insufficient = PlayerState.new(initial_trash_man_realm_id=3)
    insufficient.rebirth.trash_man_completed_count = 1
    insufficient_before = insufficient.to_dict()

    with pytest.raises(FishCommandError, match="insufficient realm"):
        apply_trash_man_rebirth(
            insufficient,
            trash_adapter=adapter,
        )
    assert insufficient.to_dict() == insufficient_before

    breakthrough = PlayerState.new(initial_trash_man_realm_id=1)
    breakthrough.trash_man.breakthrough.active = True
    breakthrough.trash_man.breakthrough.target_realm_id = 2
    breakthrough_before = breakthrough.to_dict()
    with pytest.raises(FishCommandError, match="active breakthrough"):
        apply_trash_man_rebirth(
            breakthrough,
            trash_adapter=adapter,
        )
    assert breakthrough.to_dict() == breakthrough_before

    maxed = PlayerState.new(initial_trash_man_realm_id=3)
    maxed.rebirth.trash_man_completed_count = 2
    maxed_before = maxed.to_dict()
    with pytest.raises(FishCommandError, match="already at max"):
        apply_trash_man_rebirth(maxed, trash_adapter=adapter)
    assert maxed.to_dict() == maxed_before
