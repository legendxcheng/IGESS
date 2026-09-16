from __future__ import annotations

from .behavior import BehaviorTarget
from .fish_barbell import FishBarbellDataAdapter
from .fish_state import FISH_MAX_LEVEL, FishInstance, PlayerState
from .fish_torpedo import FishTorpedoDataAdapter
from .fish_hall import FishHallDataAdapter
from .fish_sale import quality_group
from .numbers import SimNumber


RANDOM_AFFORDABLE_POLICY_ID = "random_affordable"
DEPLOYED_QUALITY_LOWEST_LEVEL_POLICY_ID = "deployed_quality_lowest_level"
CHEAPEST_IMPROVEMENT_POLICY_ID = "cheapest_improvement"
HIGHEST_AFFORDABLE_POLICY_ID = "highest_affordable"


def fish_upgrade_targets(
    state: PlayerState,
    policy: str | None,
    *,
    hall_adapter: FishHallDataAdapter,
    barbell_adapter: FishBarbellDataAdapter,
    reward_multiplier: SimNumber,
    duration_seconds: int,
    use_cache: bool = False,
) -> tuple[BehaviorTarget, ...]:
    money = state.wallet.money.to_sim_number()
    if policy == RANDOM_AFFORDABLE_POLICY_ID:
        return tuple(
            BehaviorTarget(str(item.instance_id))
            for item in sorted(state.fish.items, key=lambda fish: fish.instance_id)
            if not hall_adapter.is_beast(item.fish_id)
            and item.level < FISH_MAX_LEVEL
            and hall_adapter.upgrade_price(item) <= money
        )
    if policy != DEPLOYED_QUALITY_LOWEST_LEVEL_POLICY_ID:
        return ()
    ranked = quality_group(state, hall_adapter)
    candidates = [item for item in ranked if item.hall_slot > 0 and item.level < FISH_MAX_LEVEL]
    if not candidates:
        return ()
    target = min(candidates, key=lambda item: (item.level, -hall_adapter.quality(item), item.instance_id))
    if hall_adapter.upgrade_price(target) > money:
        return ()
    if not _shortens_barbell_wait(
        state, target, hall_adapter=hall_adapter, barbell_adapter=barbell_adapter,
        reward_multiplier=reward_multiplier, duration_seconds=duration_seconds,
        use_cache=use_cache,
    ):
        return ()
    return (BehaviorTarget(str(target.instance_id)),)


def _shortens_barbell_wait(
    state: PlayerState,
    item: FishInstance,
    *,
    hall_adapter: FishHallDataAdapter,
    barbell_adapter: FishBarbellDataAdapter,
    reward_multiplier: SimNumber,
    duration_seconds: int,
    use_cache: bool,
) -> bool:
    barbell = barbell_adapter.next_improvement(state)
    if barbell is None:
        return True
    hall = hall_adapter.snapshot(state, use_cache=use_cache)
    rate = hall.total_income_per_second * reward_multiplier
    gain = (hall_adapter.income_trace(item).income_per_second * SimNumber.parse("0.25")
            * hall.trash_man_rebirth_multiplier * reward_multiplier)
    if rate <= SimNumber.zero() or gain <= SimNumber.zero():
        return False
    money = state.wallet.money.to_sim_number()
    if money >= barbell.price:
        return False
    price = hall_adapter.upgrade_price(item)
    duration = SimNumber.parse(duration_seconds)
    wait = (barbell.price - money) / rate
    after = duration + max(
        SimNumber.zero(),
        (barbell.price - (money + rate * duration - price)) / (rate + gain),
    )
    return after < wait


def barbell_synthesis_targets(
    state: PlayerState,
    policy: str | None,
    *,
    barbell_adapter: FishBarbellDataAdapter,
) -> tuple[BehaviorTarget, ...]:
    money = state.wallet.money.to_sim_number()
    if policy == CHEAPEST_IMPROVEMENT_POLICY_ID:
        target = barbell_adapter.next_improvement(state)
        if target is None or target.price > money:
            return ()
        return (BehaviorTarget(str(target.barbell_id)),)
    if policy != RANDOM_AFFORDABLE_POLICY_ID:
        return ()
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
