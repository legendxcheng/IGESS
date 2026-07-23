from __future__ import annotations

from dataclasses import dataclass

from .fish_data import FishDataError
from .fish_state import FishInstance, PlayerState, TrashStock
from .fish_throw_data import (
    FishThrowDataAdapter,
    ProductionThrowResolution,
    ProductionThrowRequest,
)
from .numbers import SimNumber


class FishCommandError(ValueError):
    """Raised when a Fish domain command cannot be committed."""


@dataclass(frozen=True)
class AppliedThrowResolution:
    """Committed state and stable facts produced by one throw transaction."""

    state: PlayerState
    fish_instance_id: int
    trash_stock_count: int

    def event_details(self) -> dict[str, str]:
        return {
            "reward_application": "applied_to_player_state",
            "fish_instance_id": str(self.fish_instance_id),
            "trash_stock_count": str(self.trash_stock_count),
            "player_state_revision": str(self.state.meta.revision),
        }


def lock_throw_request(
    state: PlayerState,
    *,
    adapter: FishThrowDataAdapter,
    root_random_seed: int,
    throw_id: int,
    regular_luck_multiplier: float = 1.0,
) -> ProductionThrowRequest:
    """Lock strength and selected torpedo from PlayerState for one throw."""

    if not isinstance(state, PlayerState):
        raise FishCommandError("state must be a PlayerState")
    if not isinstance(adapter, FishThrowDataAdapter):
        raise FishCommandError("adapter must be a FishThrowDataAdapter")
    state.validate()
    if throw_id != state.statistics.total_throws:
        raise FishCommandError(
            "throw_id does not match PlayerState.statistics.totalThrows"
        )
    if state.torpedo.selected_id <= 0:
        raise FishCommandError("PlayerState has no selected torpedo")

    stored_strength = state.wallet.strength.to_sim_number()
    if stored_strength <= SimNumber.zero():
        raise FishCommandError("PlayerState strength must be positive")
    max_strength = adapter.rules.strength_luck_pools[-1].strength_upper_bound
    max_strength_value = SimNumber.parse(str(max_strength))
    locked_strength = min(stored_strength, max_strength_value).to_float()
    return ProductionThrowRequest(
        root_random_seed=root_random_seed,
        throw_id=throw_id,
        strength=locked_strength,
        torpedo_id=state.torpedo.selected_id,
        regular_luck_multiplier=regular_luck_multiplier,
    )


def apply_throw_resolution(
    state: PlayerState,
    resolution: ProductionThrowResolution,
    *,
    adapter: FishThrowDataAdapter,
) -> AppliedThrowResolution:
    """Atomically add one resolved fish and trash reward to PlayerState.

    The input state is never mutated. A validated copy is returned only after
    every reward fact and counter has been updated successfully.
    """

    if not isinstance(state, PlayerState):
        raise FishCommandError("state must be a PlayerState")
    if not isinstance(resolution, ProductionThrowResolution):
        raise FishCommandError(
            "resolution must be a ProductionThrowResolution"
        )
    if not isinstance(adapter, FishThrowDataAdapter):
        raise FishCommandError("adapter must be a FishThrowDataAdapter")
    state.validate()
    try:
        adapter.verify_resolution(resolution)
    except FishDataError as exc:
        raise FishCommandError(
            "resolution does not match the authoritative Fish data replay"
        ) from exc
    if state.torpedo.selected_id != resolution.request.torpedo_id:
        raise FishCommandError(
            "resolved torpedo does not match PlayerState.torpedo.selectedId"
        )
    if resolution.request.throw_id != state.statistics.total_throws:
        raise FishCommandError(
            "resolved throw_id does not match PlayerState.statistics.totalThrows"
        )

    fish_id = _positive_config_id(
        resolution.outcome.fish_reward.id,
        "fish_reward.id",
    )
    trash_id = _positive_config_id(
        resolution.outcome.trash_reward.id,
        "trash_reward.id",
    )
    if (
        type(resolution.fish_weight_gram) is not int
        or resolution.fish_weight_gram <= 0
    ):
        raise FishCommandError("fish_weight_gram must be a positive integer")
    if (
        type(resolution.fish_mutation_id) is not int
        or resolution.fish_mutation_id <= 0
    ):
        raise FishCommandError("fish_mutation_id must be a positive integer")

    committed = state.copy()
    instance_id = committed.fish.next_instance_id
    committed.fish.items.append(
        FishInstance(
            instance_id=instance_id,
            fish_id=fish_id,
            mutation_id=resolution.fish_mutation_id,
            level=1,
            weight_gram=resolution.fish_weight_gram,
            hall_slot=0,
        )
    )
    committed.fish.next_instance_id += 1

    trash_stock_count = 1
    for stock in committed.trash_man.processing.stocks:
        if stock.trash_id == trash_id:
            stock.count += 1
            trash_stock_count = stock.count
            break
    else:
        committed.trash_man.processing.stocks.append(
            TrashStock(trash_id=trash_id, count=1)
        )

    committed.statistics.total_throws += 1
    committed.statistics.total_fish_caught += 1
    committed.meta.revision += 1
    committed.validate()
    return AppliedThrowResolution(
        state=committed,
        fish_instance_id=instance_id,
        trash_stock_count=trash_stock_count,
    )


def _positive_config_id(value: object, field: str) -> int:
    if not isinstance(value, str) or not value.isdigit():
        raise FishCommandError(f"{field} must be a positive integer id")
    parsed = int(value)
    if parsed <= 0:
        raise FishCommandError(f"{field} must be a positive integer id")
    return parsed
