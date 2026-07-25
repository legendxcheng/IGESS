from __future__ import annotations

from .fish_command_results import AppliedTorpedoPurchase, FishCommandError
from .fish_data import FishDataError
from .fish_hall import FishHallDataAdapter
from .fish_state import BigNumberDTO, PlayerState
from .fish_torpedo import FishTorpedoDataAdapter


def purchase_torpedo(
    state: PlayerState,
    torpedo_id: int,
    *,
    hall_adapter: FishHallDataAdapter,
    torpedo_adapter: FishTorpedoDataAdapter,
    _mutate: bool = False,
) -> AppliedTorpedoPurchase:
    """Pay money, own, and select a stronger production Torpedo."""

    if not isinstance(state, PlayerState):
        raise FishCommandError("state must be a PlayerState")
    if not isinstance(hall_adapter, FishHallDataAdapter):
        raise FishCommandError("hall_adapter must be a FishHallDataAdapter")
    if not isinstance(torpedo_adapter, FishTorpedoDataAdapter):
        raise FishCommandError(
            "torpedo_adapter must be a FishTorpedoDataAdapter"
        )
    if type(torpedo_id) is not int or torpedo_id <= 0:
        raise FishCommandError("torpedo_id must be a positive integer")
    if type(_mutate) is not bool:
        raise FishCommandError("_mutate must be a bool")
    if not _mutate:
        state.validate(hall_adapter.validation_context())
    if torpedo_id in state.torpedo.owned_ids:
        raise FishCommandError(f"torpedo is already owned: {torpedo_id}")
    try:
        current = torpedo_adapter.rule(state.torpedo.selected_id)
        target = torpedo_adapter.rule(torpedo_id)
    except FishDataError as exc:
        raise FishCommandError(str(exc)) from exc
    if target.power <= current.power:
        raise FishCommandError(
            "purchased torpedo must be stronger than the selected torpedo"
        )
    money_before = state.wallet.money.to_sim_number()
    if money_before < target.price:
        raise FishCommandError(
            "insufficient money for torpedo purchase: "
            f"need {target.price.to_decimal_string()}, "
            f"have {money_before.to_decimal_string()}"
        )

    committed = state if _mutate else state.copy()
    committed.torpedo.owned_ids.append(torpedo_id)
    committed.torpedo.owned_ids.sort()
    committed.torpedo.selected_id = torpedo_id
    committed.wallet.money = BigNumberDTO.from_value(
        money_before - target.price,
        allow_negative=False,
    )
    committed.meta.revision += 1
    if not _mutate:
        committed.validate(hall_adapter.validation_context())
    return AppliedTorpedoPurchase(
        state=committed,
        from_torpedo_id=current.torpedo_id,
        to_torpedo_id=target.torpedo_id,
        price=target.price,
        money_before=money_before,
        money_after=committed.wallet.money.to_sim_number(),
        power_before=current.power,
        power_after=target.power,
        trash_luck_before=current.trash_luck,
        trash_luck_after=target.trash_luck,
    )
