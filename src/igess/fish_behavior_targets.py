from __future__ import annotations

from collections.abc import Callable

from .behavior import BehaviorTarget
from .fish_barbell import FishBarbellDataAdapter
from .fish_state import FISH_MAX_LEVEL, FishInstance, PlayerState
from .fish_torpedo import FishTorpedoDataAdapter
from .fish_upgrade_ranking import FishUpgradeRankingCache
from .numbers import SimNumber


RANDOM_AFFORDABLE_POLICY_ID = "random_affordable"
CHEAPEST_BELOW_MATERIAL_TENTH_POLICY_ID = (
    "cheapest_below_material_tenth"
)
HIGHEST_AFFORDABLE_POLICY_ID = "highest_affordable"


def fish_upgrade_targets(
    state: PlayerState,
    policy: str | None,
    *,
    upgrade_price: Callable[[FishInstance], SimNumber],
    upgrade_ranking: FishUpgradeRankingCache,
    validate_state: bool,
) -> tuple[BehaviorTarget, ...]:
    if policy not in {
        RANDOM_AFFORDABLE_POLICY_ID,
        CHEAPEST_BELOW_MATERIAL_TENTH_POLICY_ID,
    }:
        return ()
    material = state.wallet.material.to_sim_number()
    if (
        policy == CHEAPEST_BELOW_MATERIAL_TENTH_POLICY_ID
        and not validate_state
    ):
        cheapest = upgrade_ranking.cheapest(state.fish.items)
        if cheapest is None:
            return ()
        item, price = cheapest
        if price * SimNumber.parse(10) >= material:
            return ()
        return (BehaviorTarget(str(item.instance_id)),)
    priced_items = []
    for item in sorted(
        state.fish.items,
        key=lambda value: value.instance_id,
    ):
        if item.level >= FISH_MAX_LEVEL:
            continue
        priced_items.append((item, upgrade_price(item)))
    if policy == CHEAPEST_BELOW_MATERIAL_TENTH_POLICY_ID:
        if not priced_items:
            return ()
        item, price = min(
            priced_items,
            key=lambda value: (value[1], value[0].instance_id),
        )
        if price * SimNumber.parse(10) >= material:
            return ()
        return (BehaviorTarget(str(item.instance_id)),)
    return tuple(
        BehaviorTarget(str(item.instance_id))
        for item, price in priced_items
        if price <= material
    )


def barbell_synthesis_targets(
    state: PlayerState,
    policy: str | None,
    *,
    barbell_adapter: FishBarbellDataAdapter,
) -> tuple[BehaviorTarget, ...]:
    if policy != RANDOM_AFFORDABLE_POLICY_ID:
        return ()
    money = state.wallet.money.to_sim_number()
    owned_ids = {
        item.barbell_id
        for item in state.barbell.owned
        if item.count > 0
    }
    return tuple(
        BehaviorTarget(str(rule.barbell_id))
        for rule in barbell_adapter.rules
        if rule.barbell_id not in owned_ids and rule.price <= money
    )


def torpedo_purchase_targets(
    state: PlayerState,
    policy: str | None,
    *,
    torpedo_adapter: FishTorpedoDataAdapter,
) -> tuple[BehaviorTarget, ...]:
    if policy != HIGHEST_AFFORDABLE_POLICY_ID:
        return ()
    current = torpedo_adapter.rule(state.torpedo.selected_id)
    material = state.wallet.material.to_sim_number()
    owned_ids = set(state.torpedo.owned_ids)
    affordable = tuple(
        rule
        for rule in torpedo_adapter.rules
        if (
            rule.torpedo_id not in owned_ids
            and rule.power > current.power
            and rule.price <= material
        )
    )
    if not affordable:
        return ()
    target = max(
        affordable,
        key=lambda rule: (rule.power, rule.torpedo_id),
    )
    return (BehaviorTarget(str(target.torpedo_id)),)
