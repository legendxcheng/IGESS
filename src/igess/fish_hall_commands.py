from __future__ import annotations

from .fish_command_results import (
    AppliedFishHallSettlement,
    AppliedFishHallUpgrade,
    AppliedFishUpgrade,
    FishCommandError,
)
from .fish_data import FishDataError
from .fish_hall import FishHallDataAdapter
from .fish_state import BigNumberDTO, PlayerState


def settle_fish_hall_income(
    state: PlayerState,
    to_time_seconds: int,
    *,
    hall_adapter: FishHallDataAdapter,
) -> AppliedFishHallSettlement:
    """Settle fixed max-income hall production to one server timestamp."""

    if not isinstance(state, PlayerState):
        raise FishCommandError("state must be a PlayerState")
    if not isinstance(hall_adapter, FishHallDataAdapter):
        raise FishCommandError("hall_adapter must be a FishHallDataAdapter")
    state.validate(hall_adapter.validation_context())
    if type(to_time_seconds) is not int:
        raise FishCommandError("to_time_seconds must be an integer")
    from_time_seconds = state.production.last_settled_at
    if to_time_seconds < from_time_seconds:
        raise FishCommandError("fish hall settlement time cannot move backwards")

    fish_hall = hall_adapter.snapshot(state)
    elapsed_seconds = to_time_seconds - from_time_seconds
    money_added = fish_hall.total_income_per_second * elapsed_seconds
    committed = state.copy()
    if elapsed_seconds > 0:
        next_money = committed.wallet.money.to_sim_number() + money_added
        committed.wallet.money = BigNumberDTO.from_value(
            next_money,
            allow_negative=False,
        )
        committed.production.last_settled_at = to_time_seconds
        committed.meta.revision += 1
    committed.validate(hall_adapter.validation_context())
    return AppliedFishHallSettlement(
        state=committed,
        from_time_seconds=from_time_seconds,
        to_time_seconds=to_time_seconds,
        elapsed_seconds=elapsed_seconds,
        money_added=money_added,
        fish_hall=fish_hall,
    )


def upgrade_fish(
    state: PlayerState,
    instance_id: int,
    *,
    hall_adapter: FishHallDataAdapter,
) -> AppliedFishUpgrade:
    """Atomically pay for one level and recompute the fixed hall layout.

    Callers must settle continuous production to the command timestamp before
    invoking this transaction.
    """

    if not isinstance(state, PlayerState):
        raise FishCommandError("state must be a PlayerState")
    if not isinstance(hall_adapter, FishHallDataAdapter):
        raise FishCommandError("hall_adapter must be a FishHallDataAdapter")
    if type(instance_id) is not int or instance_id <= 0:
        raise FishCommandError("instance_id must be a positive integer")
    state.validate(hall_adapter.validation_context())
    try:
        source_item = next(
            item for item in state.fish.items if item.instance_id == instance_id
        )
    except StopIteration as exc:
        raise FishCommandError(
            f"unknown fish instance id: {instance_id}"
        ) from exc

    try:
        price = hall_adapter.upgrade_price(source_item)
    except FishDataError as exc:
        raise FishCommandError(str(exc)) from exc
    money_before = state.wallet.money.to_sim_number()
    if money_before < price:
        raise FishCommandError(
            "insufficient money for fish upgrade: "
            f"need {price.to_decimal_string()}, "
            f"have {money_before.to_decimal_string()}"
        )

    fish_hall_before = hall_adapter.snapshot(state)
    income_before = hall_adapter.income_trace(source_item)
    committed = state.copy()
    committed_item = next(
        item
        for item in committed.fish.items
        if item.instance_id == instance_id
    )
    committed_item.level += 1
    calculated_money_after = money_before - price
    committed.wallet.money = BigNumberDTO.from_value(
        calculated_money_after,
        allow_negative=False,
    )
    money_after = committed.wallet.money.to_sim_number()
    layout = hall_adapter.expected_layout(committed)
    for item in committed.fish.items:
        item.hall_slot = layout.get(item.instance_id, 0)
    committed.meta.revision += 1
    committed.validate(hall_adapter.validation_context())
    income_after = hall_adapter.income_trace(committed_item)
    fish_hall_after = hall_adapter.snapshot(committed)
    return AppliedFishUpgrade(
        state=committed,
        instance_id=instance_id,
        from_level=source_item.level,
        to_level=committed_item.level,
        price=price,
        money_before=money_before,
        money_after=money_after,
        income_before=income_before,
        income_after=income_after,
        fish_hall_before=fish_hall_before,
        fish_hall_after=fish_hall_after,
    )


def apply_fish_hall_upgrade(
    state: PlayerState,
    *,
    hall_adapter: FishHallDataAdapter,
) -> AppliedFishHallUpgrade:
    """Atomically pay material for one hall level and apply its new capacity.

    Callers must settle all continuous production to the command timestamp
    before invoking this transaction.
    """

    if not isinstance(state, PlayerState):
        raise FishCommandError("state must be a PlayerState")
    if not isinstance(hall_adapter, FishHallDataAdapter):
        raise FishCommandError("hall_adapter must be a FishHallDataAdapter")
    state.validate(hall_adapter.validation_context())

    from_level = state.fish_hall.upgrade_level
    try:
        price = hall_adapter.hall_upgrade_price(from_level)
    except FishDataError as exc:
        raise FishCommandError(str(exc)) from exc
    material_before = state.wallet.material.to_sim_number()
    if material_before < price:
        raise FishCommandError(
            "insufficient material for fish hall upgrade: "
            f"need {price.to_decimal_string()}, "
            f"have {material_before.to_decimal_string()}"
        )

    fish_hall_before = hall_adapter.snapshot(state)
    committed = state.copy()
    committed.fish_hall.upgrade_level = from_level + 1
    calculated_material_after = material_before - price
    committed.wallet.material = BigNumberDTO.from_value(
        calculated_material_after,
        allow_negative=False,
    )
    material_after = committed.wallet.material.to_sim_number()
    layout = hall_adapter.expected_layout(committed)
    for item in committed.fish.items:
        item.hall_slot = layout.get(item.instance_id, 0)
    committed.meta.revision += 1
    committed.validate(hall_adapter.validation_context())
    fish_hall_after = hall_adapter.snapshot(committed)
    return AppliedFishHallUpgrade(
        state=committed,
        from_level=from_level,
        to_level=committed.fish_hall.upgrade_level,
        price=price,
        material_before=material_before,
        material_after=material_after,
        max_level=hall_adapter.max_hall_upgrade_level,
        fish_hall_before=fish_hall_before,
        fish_hall_after=fish_hall_after,
    )
