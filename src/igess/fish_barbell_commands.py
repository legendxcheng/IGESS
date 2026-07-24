from __future__ import annotations

from .fish_barbell import FishBarbellDataAdapter
from .fish_command_results import (
    AppliedBarbellEquip,
    AppliedBarbellSynthesis,
    FishCommandError,
)
from .fish_data import FishDataError
from .fish_hall import FishHallDataAdapter
from .fish_state import BigNumberDTO, OwnedBarbell, PlayerState


def synthesize_barbell(
    state: PlayerState,
    barbell_id: int,
    *,
    hall_adapter: FishHallDataAdapter,
    barbell_adapter: FishBarbellDataAdapter,
) -> AppliedBarbellSynthesis:
    """Atomically pay material, add one barbell, and equip the best owned.

    Callers must settle continuous production to the command timestamp before
    invoking this transaction.
    """

    if not isinstance(state, PlayerState):
        raise FishCommandError("state must be a PlayerState")
    if not isinstance(hall_adapter, FishHallDataAdapter):
        raise FishCommandError("hall_adapter must be a FishHallDataAdapter")
    if not isinstance(barbell_adapter, FishBarbellDataAdapter):
        raise FishCommandError(
            "barbell_adapter must be a FishBarbellDataAdapter"
        )
    if type(barbell_id) is not int or barbell_id <= 0:
        raise FishCommandError("barbell_id must be a positive integer")
    state.validate(hall_adapter.validation_context())
    production_before = barbell_adapter.production_snapshot(state)
    try:
        price = barbell_adapter.synthesis_price(barbell_id)
    except FishDataError as exc:
        raise FishCommandError(str(exc)) from exc
    material_before = state.wallet.material.to_sim_number()
    if material_before < price:
        raise FishCommandError(
            "insufficient material for barbell synthesis: "
            f"need {price.to_decimal_string()}, "
            f"have {material_before.to_decimal_string()}"
        )

    source_owned = next(
        (
            entry
            for entry in state.barbell.owned
            if entry.barbell_id == barbell_id
        ),
        None,
    )
    count_before = 0 if source_owned is None else source_owned.count
    committed = state.copy()
    committed_owned = next(
        (
            entry
            for entry in committed.barbell.owned
            if entry.barbell_id == barbell_id
        ),
        None,
    )
    if committed_owned is None:
        committed_owned = OwnedBarbell(barbell_id=barbell_id, count=1)
        committed.barbell.owned.append(committed_owned)
    else:
        committed_owned.count += 1
    committed.barbell.equipped_id = barbell_adapter.best_owned_id(committed)
    committed.wallet.material = BigNumberDTO.from_value(
        material_before - price,
        allow_negative=False,
    )
    committed.meta.revision += 1
    committed.validate(hall_adapter.validation_context())
    production_after = barbell_adapter.production_snapshot(committed)
    return AppliedBarbellSynthesis(
        state=committed,
        barbell_id=barbell_id,
        price=price,
        material_before=material_before,
        material_after=committed.wallet.material.to_sim_number(),
        count_before=count_before,
        count_after=committed_owned.count,
        production_before=production_before,
        production_after=production_after,
    )


def equip_barbell(
    state: PlayerState,
    barbell_id: int,
    *,
    hall_adapter: FishHallDataAdapter,
    barbell_adapter: FishBarbellDataAdapter,
) -> AppliedBarbellEquip:
    """Atomically equip one already-owned barbell.

    Callers must settle continuous production to the command timestamp before
    invoking this transaction.
    """

    if not isinstance(state, PlayerState):
        raise FishCommandError("state must be a PlayerState")
    if not isinstance(hall_adapter, FishHallDataAdapter):
        raise FishCommandError("hall_adapter must be a FishHallDataAdapter")
    if not isinstance(barbell_adapter, FishBarbellDataAdapter):
        raise FishCommandError(
            "barbell_adapter must be a FishBarbellDataAdapter"
        )
    if type(barbell_id) is not int or barbell_id <= 0:
        raise FishCommandError("barbell_id must be a positive integer")
    state.validate(hall_adapter.validation_context())
    try:
        barbell_adapter.rule(barbell_id)
    except FishDataError as exc:
        raise FishCommandError(str(exc)) from exc
    if not any(
        entry.barbell_id == barbell_id and entry.count > 0
        for entry in state.barbell.owned
    ):
        raise FishCommandError(
            f"barbell is not owned: {barbell_id}"
        )
    if state.barbell.equipped_id == barbell_id:
        raise FishCommandError(f"barbell is already equipped: {barbell_id}")

    production_before = barbell_adapter.production_snapshot(state)
    committed = state.copy()
    committed.barbell.equipped_id = barbell_id
    committed.meta.revision += 1
    committed.validate(hall_adapter.validation_context())
    production_after = barbell_adapter.production_snapshot(committed)
    return AppliedBarbellEquip(
        state=committed,
        barbell_id=barbell_id,
        production_before=production_before,
        production_after=production_after,
    )
