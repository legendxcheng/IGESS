from __future__ import annotations

import hashlib
import math
from bisect import bisect_right
from dataclasses import dataclass
from functools import lru_cache
from typing import Any


def _finite_float(value: Any, field: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a finite number") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{field} must be a finite number")
    return parsed


def _positive_float(value: Any, field: str) -> float:
    parsed = _finite_float(value, field)
    if parsed <= 0:
        raise ValueError(f"{field} must be a positive number")
    return parsed


@dataclass(frozen=True)
class ThresholdItem:
    id: str
    name: str
    denominator: float
    rarity_id: int = 0


@dataclass(frozen=True)
class BonusResult:
    id: str
    name: str
    result_type: str
    roll_power_requirement: float
    continue_chain: bool
    luck_multiplier: float


@dataclass(frozen=True)
class Mutation:
    id: str
    name: str
    weight: int
    income_multiplier: float


@dataclass(frozen=True)
class StrengthLuckPool:
    """One strength interval from ``tbfishrandompool``.

    ``strength_upper_bound`` is the inclusive strength endpoint of this row,
    not its starting requirement.  Consequently row 0 covers
    ``[1, strength_upper_bound]`` and every later row covers
    ``(previous.strength_upper_bound, strength_upper_bound]``.
    """

    id: int
    name: str
    strength_upper_bound: float
    start_luck: float
    end_luck: float


@dataclass(frozen=True)
class StrengthLuckMapping:
    input_strength: float
    clamped_strength: float
    pool_id: int
    pool_name: str
    pool_index: int
    interval_min_strength: float
    interval_max_strength: float
    log_progress: float
    smooth_progress: float
    base_fish_luck: float
    regular_luck_multiplier: float
    fish_luck: float

    def to_ordered_dict(self) -> dict[str, Any]:
        return {
            "input_strength": round(self.input_strength, 8),
            "clamped_strength": round(self.clamped_strength, 8),
            "pool_id": self.pool_id,
            "pool_name": self.pool_name,
            "interval_min_strength": round(self.interval_min_strength, 8),
            "interval_max_strength": round(self.interval_max_strength, 8),
            "strength_upper_bound_semantics": "inclusive_region_endpoint",
            "log_progress": round(self.log_progress, 8),
            "smooth_progress": round(self.smooth_progress, 8),
            "base_fish_luck": round(self.base_fish_luck, 8),
            "regular_luck_multiplier": round(self.regular_luck_multiplier, 8),
            "fish_luck": round(self.fish_luck, 8),
        }


@dataclass(frozen=True)
class TrashLuckPool:
    """One torpedo-power interval from ``tbtrashrandompool``."""

    id: int
    name: str
    power_upper_bound: float
    start_luck: float
    end_luck: float


@dataclass(frozen=True)
class TrashLuckMapping:
    input_power: float
    clamped_power: float
    pool_id: int
    pool_name: str
    pool_index: int
    interval_min_power: float
    interval_max_power: float
    log_progress: float
    smooth_progress: float
    base_trash_luck: float
    regular_luck_multiplier: float
    trash_luck: float

    def to_ordered_dict(self) -> dict[str, Any]:
        return {
            "input_power": round(self.input_power, 8),
            "clamped_power": round(self.clamped_power, 8),
            "pool_id": self.pool_id,
            "pool_name": self.pool_name,
            "interval_min_power": round(self.interval_min_power, 8),
            "interval_max_power": round(self.interval_max_power, 8),
            "power_upper_bound_semantics": "inclusive_region_endpoint",
            "log_progress": round(self.log_progress, 8),
            "smooth_progress": round(self.smooth_progress, 8),
            "base_trash_luck": round(self.base_trash_luck, 8),
            "regular_luck_multiplier": round(
                self.regular_luck_multiplier, 8
            ),
            "trash_luck": round(self.trash_luck, 8),
        }


@dataclass(frozen=True)
class BonusEvent:
    layer: int
    result_type: str
    roll_power: float
    mutation_id: str | None = None
    fish_luck_after: float | None = None


@dataclass(frozen=True)
class ThrowInput:
    """Runtime facts for one throw; no PlayerState reference is permitted."""

    root_random_seed: int
    throw_id: int
    strength: float
    regular_luck_multiplier: float = 1.0
    trash_luck: float = 1.0


@dataclass(frozen=True)
class ThrowRules:
    strength_luck_pools: tuple[StrengthLuckPool, ...]
    bonus_base_luck: float
    max_bonus_layers: int
    bonus_results: tuple[BonusResult, ...]
    mutations: tuple[Mutation, ...]
    fish_pool: tuple[ThresholdItem, ...]
    trash_pool: tuple[ThresholdItem, ...]


@dataclass(frozen=True)
class ThrowOutcome:
    throw_id: int
    strength_luck: StrengthLuckMapping
    bonus_events: tuple[BonusEvent, ...]
    mutation: Mutation | None
    bonus_double_count: int
    final_fish_luck: float
    fish_roll_power: float
    fish_reward: ThresholdItem
    trash_roll_power: float
    trash_reward: ThresholdItem


def map_strength_to_fish_luck(
    strength: float,
    pools: tuple[StrengthLuckPool, ...],
    regular_luck_multiplier: float = 1.0,
) -> StrengthLuckMapping:
    """Interpolate FishLuck directly from a locked strength snapshot.

    A row's ``strength_upper_bound`` is its inclusive right endpoint.  Exact
    endpoints therefore use that row's ``end_luck``; the following row starts
    immediately above the endpoint and may deliberately have a different
    ``start_luck``.  Production table gaps are preserved rather than smoothed.
    """

    _validate_strength_pools(pools)
    input_strength = _finite_float(strength, "strength")
    multiplier = _positive_float(
        regular_luck_multiplier, "regular_luck_multiplier"
    )
    min_strength = 1.0
    max_strength = float(pools[-1].strength_upper_bound)
    clamped = min(max(input_strength, min_strength), max_strength)
    pool_index = next(
        (
            index
            for index, pool in enumerate(pools)
            if clamped <= pool.strength_upper_bound
        ),
        len(pools) - 1,
    )
    pool = pools[pool_index]
    interval_min = (
        min_strength
        if pool_index == 0
        else float(pools[pool_index - 1].strength_upper_bound)
    )
    interval_max = float(pool.strength_upper_bound)
    if math.isclose(interval_min, interval_max, rel_tol=0.0, abs_tol=0.0):
        log_progress = 1.0
    else:
        log_progress = (
            (math.log(clamped) - math.log(interval_min))
            / (math.log(interval_max) - math.log(interval_min))
        )
        log_progress = min(max(log_progress, 0.0), 1.0)
    smooth_progress = log_progress**2 * (3.0 - 2.0 * log_progress)
    base_luck = float(pool.start_luck) + (
        float(pool.end_luck) - float(pool.start_luck)
    ) * smooth_progress
    fish_luck = max(1.0, base_luck * multiplier)
    return StrengthLuckMapping(
        input_strength=input_strength,
        clamped_strength=clamped,
        pool_id=pool.id,
        pool_name=pool.name,
        pool_index=pool_index,
        interval_min_strength=interval_min,
        interval_max_strength=interval_max,
        log_progress=log_progress,
        smooth_progress=smooth_progress,
        base_fish_luck=base_luck,
        regular_luck_multiplier=multiplier,
        fish_luck=fish_luck,
    )


def map_torpedo_power_to_trash_luck(
    power: float,
    pools: tuple[TrashLuckPool, ...],
    regular_luck_multiplier: float = 1.0,
) -> TrashLuckMapping:
    """Interpolate TrashLuck from a locked torpedo-power snapshot."""

    _validate_trash_luck_pools(pools)
    input_power = _finite_float(power, "torpedo_power")
    multiplier = _positive_float(
        regular_luck_multiplier, "regular_luck_multiplier"
    )
    min_power = 1.0
    max_power = float(pools[-1].power_upper_bound)
    clamped = min(max(input_power, min_power), max_power)
    pool_index = next(
        (
            index
            for index, pool in enumerate(pools)
            if clamped <= pool.power_upper_bound
        ),
        len(pools) - 1,
    )
    pool = pools[pool_index]
    interval_min = (
        min_power
        if pool_index == 0
        else float(pools[pool_index - 1].power_upper_bound)
    )
    interval_max = float(pool.power_upper_bound)
    if math.isclose(interval_min, interval_max, rel_tol=0.0, abs_tol=0.0):
        log_progress = 1.0
    else:
        log_progress = (
            (math.log(clamped) - math.log(interval_min))
            / (math.log(interval_max) - math.log(interval_min))
        )
        log_progress = min(max(log_progress, 0.0), 1.0)
    smooth_progress = log_progress**2 * (3.0 - 2.0 * log_progress)
    base_luck = float(pool.start_luck) + (
        float(pool.end_luck) - float(pool.start_luck)
    ) * smooth_progress
    trash_luck = max(1.0, base_luck * multiplier)
    return TrashLuckMapping(
        input_power=input_power,
        clamped_power=clamped,
        pool_id=pool.id,
        pool_name=pool.name,
        pool_index=pool_index,
        interval_min_power=interval_min,
        interval_max_power=interval_max,
        log_progress=log_progress,
        smooth_progress=smooth_progress,
        base_trash_luck=base_luck,
        regular_luck_multiplier=multiplier,
        trash_luck=trash_luck,
    )


def resolve_throw(throw: ThrowInput, rules: ThrowRules) -> ThrowOutcome:
    """Resolve one throw without reading or mutating player state."""

    _validate_throw_input(throw)
    _validate_rules(rules)
    strength_luck = map_strength_to_fish_luck(
        throw.strength,
        rules.strength_luck_pools,
        throw.regular_luck_multiplier,
    )

    current_luck = strength_luck.fish_luck
    mutation: Mutation | None = None
    bonus_events: list[BonusEvent] = []
    double_count = 0
    for layer in range(1, rules.max_bonus_layers + 1):
        bonus_power = rules.bonus_base_luck / _domain_random(
            throw.root_random_seed,
            throw.throw_id,
            "bonus",
            layer,
        )
        bonus = select_bonus(rules.bonus_results, bonus_power, mutation is None)
        mutation_id: str | None = None
        fish_luck_after: float | None = None
        if bonus.result_type == "mutation":
            mutation = _weighted_mutation(
                rules.mutations,
                throw.root_random_seed,
                throw.throw_id,
            )
            mutation_id = mutation.id
        elif bonus.result_type == "luck_double":
            current_luck *= bonus.luck_multiplier
            double_count += 1
            fish_luck_after = current_luck
        bonus_events.append(
            BonusEvent(
                layer=layer,
                result_type=bonus.result_type,
                roll_power=bonus_power,
                mutation_id=mutation_id,
                fish_luck_after=fish_luck_after,
            )
        )
        if not bonus.continue_chain or bonus.result_type == "no_bonus":
            break

    fish_roll_power = current_luck / _domain_random(
        throw.root_random_seed,
        throw.throw_id,
        "fish",
        0,
    )
    trash_roll_power = throw.trash_luck / _domain_random(
        throw.root_random_seed,
        throw.throw_id,
        "trash_rarity",
        0,
    )
    fish_reward = _select_threshold_item(rules.fish_pool, fish_roll_power)
    trash_reward = _select_threshold_item(rules.trash_pool, trash_roll_power)
    return ThrowOutcome(
        throw_id=throw.throw_id,
        strength_luck=strength_luck,
        bonus_events=tuple(bonus_events),
        mutation=mutation,
        bonus_double_count=double_count,
        final_fish_luck=current_luck,
        fish_roll_power=fish_roll_power,
        fish_reward=fish_reward,
        trash_roll_power=trash_roll_power,
        trash_reward=trash_reward,
    )


def select_bonus(
    bonus_results: tuple[BonusResult, ...],
    roll_power: float,
    can_select_mutation: bool,
) -> BonusResult:
    selected = bonus_results[0]
    for row in bonus_results:
        if row.result_type == "mutation" and not can_select_mutation:
            continue
        if row.roll_power_requirement <= roll_power:
            selected = row
    return selected


def _select_threshold_item(
    rows: tuple[ThresholdItem, ...], roll_power: float
) -> ThresholdItem:
    thresholds = _threshold_values(rows)
    index = max(bisect_right(thresholds, roll_power) - 1, 0)
    return rows[index]


@lru_cache(maxsize=32)
def _threshold_values(rows: tuple[ThresholdItem, ...]) -> tuple[float, ...]:
    return tuple(float(row.denominator) for row in rows)


def _weighted_mutation(
    mutations: tuple[Mutation, ...], root_seed: int, throw_id: int
) -> Mutation:
    total = sum(item.weight for item in mutations)
    target = _domain_integer(root_seed, throw_id, "mutation", 0, total)
    cumulative = 0
    for item in mutations:
        cumulative += item.weight
        if target < cumulative:
            return item
    return mutations[-1]


def _domain_random(root_seed: int, throw_id: int, stream: str, index: int) -> float:
    # Use the leading 53 digest bits so the result is stable across Python RNG
    # implementations while retaining the exact Random(0, 1] contract.
    value = _domain_digest(root_seed, throw_id, stream, index, 0) >> (256 - 53)
    return (value + 1) / float(1 << 53)


def _domain_integer(
    root_seed: int,
    throw_id: int,
    stream: str,
    index: int,
    upper_bound: int,
) -> int:
    # Rejection sampling avoids modulo bias for weighted mutation selection.
    modulus = 1 << 256
    limit = modulus - (modulus % upper_bound)
    nonce = 0
    while True:
        value = _domain_digest(root_seed, throw_id, stream, index, nonce)
        if value < limit:
            return value % upper_bound
        nonce += 1


def _domain_digest(
    root_seed: int,
    throw_id: int,
    stream: str,
    index: int,
    nonce: int,
) -> int:
    payload = f"{root_seed}|{throw_id}|{stream}|{index}|{nonce}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest(), "big")


def _validate_throw_input(throw: ThrowInput) -> None:
    if type(throw.root_random_seed) is not int:
        raise ValueError("root_random_seed must be an integer")
    if type(throw.throw_id) is not int or throw.throw_id < 0:
        raise ValueError("throw_id must be a non-negative integer")
    _finite_float(throw.strength, "strength")
    _positive_float(throw.regular_luck_multiplier, "regular_luck_multiplier")
    _positive_float(throw.trash_luck, "trash_luck")


@lru_cache(maxsize=32)
def _validate_rules(rules: ThrowRules) -> None:
    _validate_strength_pools(rules.strength_luck_pools)
    _positive_float(rules.bonus_base_luck, "bonus_base_luck")
    if type(rules.max_bonus_layers) is not int or rules.max_bonus_layers <= 0:
        raise ValueError("max_bonus_layers must be a positive integer")
    _validate_thresholds(rules.fish_pool, "fish_pool")
    _validate_thresholds(rules.trash_pool, "trash_pool")
    if not rules.bonus_results:
        raise ValueError("bonus_results must not be empty")
    expected_types = {"no_bonus", "mutation", "luck_double"}
    if {item.result_type for item in rules.bonus_results} != expected_types:
        raise ValueError(
            "bonus_results must contain no_bonus, mutation, and luck_double"
        )
    bonus_thresholds = [
        _positive_float(row.roll_power_requirement, "bonus roll requirement")
        for row in rules.bonus_results
    ]
    if bonus_thresholds != sorted(bonus_thresholds) or len(
        set(bonus_thresholds)
    ) != len(bonus_thresholds):
        raise ValueError("bonus_results thresholds must be unique and ascending")
    if rules.bonus_results[0].result_type != "no_bonus":
        raise ValueError("the lowest bonus result must be no_bonus")
    if not rules.mutations or any(
        type(item.weight) is not int or item.weight <= 0
        for item in rules.mutations
    ):
        raise ValueError("mutations must contain positive integer weights")


@lru_cache(maxsize=32)
def _validate_strength_pools(pools: tuple[StrengthLuckPool, ...]) -> None:
    if not pools:
        raise ValueError("strength_luck_pools must not be empty")
    upper_bounds = [
        _positive_float(pool.strength_upper_bound, "strength_upper_bound")
        for pool in pools
    ]
    if upper_bounds != sorted(upper_bounds) or len(set(upper_bounds)) != len(
        upper_bounds
    ):
        raise ValueError(
            "strength upper bounds must be unique and ascending"
        )
    for pool in pools:
        start = _positive_float(pool.start_luck, "start_luck")
        end = _positive_float(pool.end_luck, "end_luck")
        if start > end:
            raise ValueError("start_luck must not exceed end_luck")


@lru_cache(maxsize=32)
def _validate_trash_luck_pools(pools: tuple[TrashLuckPool, ...]) -> None:
    if not pools:
        raise ValueError("trash_luck_pools must not be empty")
    upper_bounds = [
        _positive_float(pool.power_upper_bound, "power_upper_bound")
        for pool in pools
    ]
    if upper_bounds != sorted(upper_bounds) or len(set(upper_bounds)) != len(
        upper_bounds
    ):
        raise ValueError("power upper bounds must be unique and ascending")
    for pool in pools:
        start = _positive_float(pool.start_luck, "start_luck")
        end = _positive_float(pool.end_luck, "end_luck")
        if start > end:
            raise ValueError("start_luck must not exceed end_luck")


def _validate_thresholds(
    rows: tuple[ThresholdItem, ...], field: str
) -> None:
    if not rows:
        raise ValueError(f"{field} must not be empty")
    thresholds = [
        _positive_float(row.denominator, f"{field}.denominator") for row in rows
    ]
    if thresholds != sorted(thresholds) or len(set(thresholds)) != len(thresholds):
        raise ValueError(f"{field} thresholds must be unique and ascending")
