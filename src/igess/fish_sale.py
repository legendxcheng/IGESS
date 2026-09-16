"""Fish sale transactions and the player's periodic inventory cleanup policy."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .behavior import BehaviorCandidate, BehaviorTarget, FixedDuration
from .fish_command_results import FishCommandError
from .fish_hall import FishHallDataAdapter
from .fish_state import BigNumberDTO, FishInstance, PlayerState
from .numbers import SimNumber

SELL_FISH_BEHAVIOR_ID = "sell_fish"
SALE_POLICY_ID = "keep_deployed_and_top_quality"
SALE_PERIOD_COUNTER = "fish_sale_checked_period"
SALE_COUNT_COUNTER = "fish_sold_count"
# FishGameplayConfig.fishSellIncomeSeconds; a game rule, not a yield bonus.
FISH_SELL_INCOME_SECONDS = 10


def quality_group(state: PlayerState, hall_adapter: FishHallDataAdapter) -> list[FishInstance]:
    capacity = hall_adapter.capacity(state.fish_hall.upgrade_level)
    capacity -= sum(
        item.hall_slot > 0 and hall_adapter.is_beast(item.fish_id)
        for item in state.fish.items
    )
    return sorted(
        (item for item in state.fish.items if not hall_adapter.is_beast(item.fish_id)),
        key=lambda item: (-hall_adapter.quality(item), -item.level, item.instance_id),
    )[:max(0, capacity)]


def sale_targets(state: PlayerState, hall_adapter: FishHallDataAdapter) -> tuple[int, ...]:
    protected = {item.instance_id for item in quality_group(state, hall_adapter)}
    return tuple(sorted(
        item.instance_id for item in state.fish.items
        if item.hall_slot == 0 and item.instance_id not in protected
        and not hall_adapter.is_beast(item.fish_id)
    ))


def decode_sale_target(target_id: str | None) -> tuple[int, ...]:
    try:
        value = json.loads(target_id or "")
    except (TypeError, ValueError) as exc:
        raise FishCommandError("sell_fish has an invalid batch") from exc
    return _validate_ids(value)


def _validate_ids(instance_ids: Sequence[int]) -> tuple[int, ...]:
    if not isinstance(instance_ids, (list, tuple)) or not instance_ids:
        raise FishCommandError("fish sale requires a nonempty batch")
    if any(type(value) is not int or value <= 0 for value in instance_ids):
        raise FishCommandError("fish sale instance IDs must be positive integers")
    if len(set(instance_ids)) != len(instance_ids):
        raise FishCommandError("fish sale contains duplicate instance IDs")
    return tuple(sorted(instance_ids))


def validate_sale(
    state: PlayerState, instance_ids: Sequence[int], hall_adapter: FishHallDataAdapter,
) -> tuple[FishInstance, ...]:
    ids = _validate_ids(instance_ids)
    by_id = {item.instance_id: item for item in state.fish.items}
    for instance_id in ids:
        item = by_id.get(instance_id)
        if item is None:
            raise FishCommandError(f"unknown fish instance id: {instance_id}")
        if item.hall_slot != 0:
            raise FishCommandError("deployed fish cannot be sold")
        if hall_adapter.is_beast(item.fish_id):
            raise FishCommandError("beast fish cannot be sold")
    return tuple(by_id[instance_id] for instance_id in ids)


@dataclass(frozen=True)
class AppliedFishSale:
    state: PlayerState
    instance_ids: tuple[int, ...]
    material_added: SimNumber
    material_before: SimNumber
    material_after: SimNumber
    prices: tuple[str, ...]

    def event_details(self) -> dict[str, str]:
        return {
            "fish_sale_instance_ids": json.dumps(self.instance_ids, separators=(",", ":")),
            "fish_sale_count": str(len(self.instance_ids)),
            "fish_sale_prices": json.dumps(self.prices, separators=(",", ":")),
            "fish_sale_material_added": self.material_added.to_decimal_string(),
            "material_before_fish_sale": self.material_before.to_decimal_string(),
            "material_after_fish_sale": self.material_after.to_decimal_string(),
            "fish_sale_resource": "material",
            "fish_sale_income_seconds": str(FISH_SELL_INCOME_SECONDS),
            "fish_sale_formula": "baseMoneyPerSecond * incomeMultiplier * fishSellIncomeSeconds",
            "player_state_revision": str(self.state.meta.revision),
        }


def sell_fish(
    state: PlayerState,
    instance_ids: Sequence[int],
    *,
    hall_adapter: FishHallDataAdapter,
) -> AppliedFishSale:
    """Sell a whole batch atomically after the caller settles production.

    Uses a copy even in the trusted loop: sales are infrequent and rejecting
    any member of a batch must leave the original wallet/inventory untouched.
    A new inventory list also invalidates all identity-based ranking caches.
    """
    items = validate_sale(state, instance_ids, hall_adapter)
    state.validate(hall_adapter.validation_context())
    prices = tuple(hall_adapter.quality(item) * FISH_SELL_INCOME_SECONDS for item in items)
    added = sum(prices, SimNumber.zero())
    before = state.wallet.material.to_sim_number()
    committed = state.copy()
    ids = tuple(item.instance_id for item in items)
    selected = set(ids)
    committed.fish.items = [item for item in committed.fish.items if item.instance_id not in selected]
    committed.wallet.material = BigNumberDTO.from_value(before + added, allow_negative=False)
    committed.meta.revision += 1
    layout = hall_adapter.expected_layout(committed)
    for item in committed.fish.items:
        item.hall_slot = layout.get(item.instance_id, 0)
    committed.validate(hall_adapter.validation_context())
    return AppliedFishSale(
        committed, ids, added, before, committed.wallet.material.to_sim_number(),
        tuple(price.to_decimal_string() for price in prices),
    )


@dataclass(frozen=True)
class FishSalePolicy:
    interval_online_seconds: int

    @classmethod
    def from_engine_settings(cls, settings: Mapping[str, Any]) -> FishSalePolicy:
        scheduler = settings.get("behavior_scheduler", {})
        payload = scheduler.get("fish_sale") if isinstance(scheduler, Mapping) else None
        if not isinstance(payload, Mapping) or set(payload) != {"interval_online_seconds"}:
            raise ValueError("sell_fish requires behavior_scheduler.fish_sale.interval_online_seconds")
        interval = payload["interval_online_seconds"]
        if type(interval) is not int or interval <= 0:
            raise ValueError("fish sale interval_online_seconds must be a positive integer")
        return cls(interval)

    def due_candidate(
        self, state: PlayerState, *, hall_adapter: FishHallDataAdapter,
        active_seconds: int, remaining_online_seconds: int, duration_seconds: int,
        counters: dict[str, int],
    ) -> BehaviorCandidate | None:
        period = active_seconds // self.interval_online_seconds
        if period <= counters.get(SALE_PERIOD_COUNTER, 0):
            return None
        ids = sale_targets(state, hall_adapter)
        if not ids:
            counters[SALE_PERIOD_COUNTER] = period
            return None
        if remaining_online_seconds < duration_seconds:
            return None
        return BehaviorCandidate(
            behavior_id=SELL_FISH_BEHAVIOR_ID,
            duration=FixedDuration(duration_seconds),
            targets=(BehaviorTarget(json.dumps(ids, separators=(",", ":"))),),
        )
