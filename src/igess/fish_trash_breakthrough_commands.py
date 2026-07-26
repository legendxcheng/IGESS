from __future__ import annotations

from .fish_command_results import (
    AppliedTrashManBreakthroughFunding,
    FishCommandError,
)
from .fish_data import FishDataError
from .fish_state import BigNumberDTO, PlayerState
from .fish_trash import FishTrashDataAdapter


def fund_trash_man_realm_breakthrough(
    state: PlayerState,
    *,
    trash_adapter: FishTrashDataAdapter,
    _mutate: bool = False,
) -> AppliedTrashManBreakthroughFunding:
    """Pay the current realm row's price and start an online breakthrough."""

    if not isinstance(state, PlayerState):
        raise FishCommandError("state must be a PlayerState")
    if not isinstance(trash_adapter, FishTrashDataAdapter):
        raise FishCommandError(
            "trash_adapter must be a FishTrashDataAdapter"
        )
    if type(_mutate) is not bool:
        raise FishCommandError("_mutate must be a bool")
    if not _mutate:
        state.validate()

    realm_id = state.trash_man.realm_id
    if state.trash_man.breakthrough.active:
        raise FishCommandError("trash-man breakthrough is already active")
    if realm_id != state.trash_man.highest_realm_id:
        raise FishCommandError(
            "trash-man must finish historical realm catch-up before funding "
            "a new breakthrough"
        )
    try:
        target_realm_id = trash_adapter.next_realm_id(realm_id)
        price = trash_adapter.money_required_to_next_realm(realm_id)
        required_seconds = (
            trash_adapter.cultivation_seconds_to_next_realm(realm_id)
        )
    except FishDataError as exc:
        raise FishCommandError(str(exc)) from exc
    if target_realm_id is None:
        raise FishCommandError("trash-man realm is already at max")

    money_before = state.wallet.money.to_sim_number()
    if money_before < price:
        raise FishCommandError(
            "insufficient money for trash-man breakthrough: "
            f"need {price.to_decimal_string()}, "
            f"have {money_before.to_decimal_string()}"
        )

    committed = state if _mutate else state.copy()
    committed.wallet.money = BigNumberDTO.from_value(
        money_before - price,
        allow_negative=False,
    )
    committed.trash_man.breakthrough.active = True
    committed.trash_man.breakthrough.target_realm_id = target_realm_id
    committed.trash_man.breakthrough.progress_seconds = 0
    committed.meta.revision += 1
    if not _mutate:
        committed.validate()
    return AppliedTrashManBreakthroughFunding(
        state=committed,
        from_realm_id=realm_id,
        target_realm_id=target_realm_id,
        price=price,
        required_online_seconds=required_seconds,
        money_before=money_before,
        money_after=committed.wallet.money.to_sim_number(),
    )
