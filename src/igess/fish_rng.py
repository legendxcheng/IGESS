from __future__ import annotations

import json
import math
from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .fish_throw import (
    BonusResult,
    Mutation,
    StrengthLuckMapping,
    StrengthLuckPool,
    ThresholdItem,
    ThrowInput,
    ThrowRules,
    map_strength_to_fish_luck,
    resolve_throw,
    select_bonus,
)


def _positive_float(value: Any, field: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a positive number") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(f"{field} must be a positive number")
    return parsed


def _finite_float(value: Any, field: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a finite number") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{field} must be a finite number")
    return parsed


def _positive_int(value: Any, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


@dataclass(frozen=True)
class FishRngConfig:
    scenario_id: str
    random_seed: int
    throws: int
    cycle_seconds: int
    strength: float
    regular_luck_multiplier: float
    strength_luck_pools: tuple[StrengthLuckPool, ...]
    trash_luck: float
    bonus_base_luck: float
    max_bonus_layers: int
    bonus_results: tuple[BonusResult, ...]
    mutations: tuple[Mutation, ...]
    fish_pool: tuple[ThresholdItem, ...]
    trash_pool: tuple[ThresholdItem, ...]
    sample_throw_count: int

    @property
    def strength_luck_mapping(self) -> StrengthLuckMapping:
        return map_strength_to_fish_luck(
            self.strength,
            self.strength_luck_pools,
            self.regular_luck_multiplier,
        )

    @property
    def fish_luck(self) -> float:
        return self.strength_luck_mapping.fish_luck

    @classmethod
    def load(cls, path: str | Path) -> "FishRngConfig":
        source = Path(path)
        raw = json.loads(source.read_text(encoding="utf-8"))
        if type(raw) is not dict:
            raise ValueError("fish RNG config root must be an object")

        scenario_id = raw.get("scenario_id")
        if not isinstance(scenario_id, str) or not scenario_id:
            raise ValueError("scenario_id must be a non-empty string")
        seed = raw.get("random_seed")
        if type(seed) is not int:
            raise ValueError("random_seed must be an integer")

        bonus_results = tuple(
            BonusResult(
                id=str(row["id"]),
                name=str(row["name"]),
                result_type=str(row["result_type"]),
                roll_power_requirement=_positive_float(
                    row["roll_power_requirement"],
                    "bonus_results.roll_power_requirement",
                ),
                continue_chain=bool(row["continue_chain"]),
                luck_multiplier=_positive_float(
                    row.get("luck_multiplier", 1),
                    "bonus_results.luck_multiplier",
                ),
            )
            for row in _object_rows(raw, "bonus_results")
        )
        allowed_types = {"no_bonus", "mutation", "luck_double"}
        if {item.result_type for item in bonus_results} != allowed_types:
            raise ValueError(
                "bonus_results must contain no_bonus, mutation, and luck_double"
            )
        _validate_unique_ascending(
            bonus_results,
            lambda item: item.roll_power_requirement,
            "bonus_results",
        )
        if bonus_results[0].result_type != "no_bonus":
            raise ValueError("the lowest bonus result must be no_bonus")

        mutations = tuple(
            Mutation(
                id=str(row["id"]),
                name=str(row["name"]),
                weight=_positive_int(row["weight"], "mutations.weight"),
                income_multiplier=_positive_float(
                    row["income_multiplier"], "mutations.income_multiplier"
                ),
            )
            for row in _object_rows(raw, "mutations")
        )
        _validate_unique_ids(mutations, "mutations")

        strength_luck_pools = tuple(
            StrengthLuckPool(
                id=row["id"],
                name=str(row["name"]),
                strength_upper_bound=_positive_float(
                    row["strength_upper_bound"],
                    "strength_luck_pools.strength_upper_bound",
                ),
                start_luck=_positive_float(
                    row["start_luck"], "strength_luck_pools.start_luck"
                ),
                end_luck=_positive_float(
                    row["end_luck"], "strength_luck_pools.end_luck"
                ),
            )
            for row in _object_rows(raw, "strength_luck_pools")
        )
        _validate_strength_luck_pools(strength_luck_pools)

        fish_pool = _load_threshold_pool(raw, "fish_pool")
        trash_pool = _load_threshold_pool(raw, "trash_pool")
        sample_count = raw.get("sample_throw_count", 20)
        if type(sample_count) is not int or sample_count < 0:
            raise ValueError("sample_throw_count must be a non-negative integer")

        return cls(
            scenario_id=scenario_id,
            random_seed=seed,
            throws=_positive_int(raw.get("throws"), "throws"),
            cycle_seconds=_positive_int(raw.get("cycle_seconds"), "cycle_seconds"),
            strength=_finite_float(raw.get("strength"), "strength"),
            regular_luck_multiplier=_positive_float(
                raw.get("regular_luck_multiplier"), "regular_luck_multiplier"
            ),
            strength_luck_pools=strength_luck_pools,
            trash_luck=_positive_float(raw.get("trash_luck"), "trash_luck"),
            bonus_base_luck=_positive_float(
                raw.get("bonus_base_luck"), "bonus_base_luck"
            ),
            max_bonus_layers=_positive_int(
                raw.get("max_bonus_layers"), "max_bonus_layers"
            ),
            bonus_results=bonus_results,
            mutations=mutations,
            fish_pool=fish_pool,
            trash_pool=trash_pool,
            sample_throw_count=sample_count,
        )


def _object_rows(raw: dict[str, Any], field: str) -> list[dict[str, Any]]:
    rows = raw.get(field)
    if type(rows) is not list or not rows or any(type(row) is not dict for row in rows):
        raise ValueError(f"{field} must be a non-empty list of objects")
    return rows


def _load_threshold_pool(
    raw: dict[str, Any], field: str
) -> tuple[ThresholdItem, ...]:
    result = tuple(
        ThresholdItem(
            id=str(row["id"]),
            name=str(row["name"]),
            denominator=_positive_float(row["denominator"], f"{field}.denominator"),
        )
        for row in _object_rows(raw, field)
    )
    _validate_unique_ids(result, field)
    _validate_unique_ascending(result, lambda item: item.denominator, field)
    return result


def _validate_unique_ids(rows: tuple[Any, ...], field: str) -> None:
    ids = [row.id for row in rows]
    if any(not item for item in ids) or len(set(ids)) != len(ids):
        raise ValueError(f"{field} ids must be non-empty and unique")


def _validate_unique_ascending(rows, key, field: str) -> None:
    values = [key(row) for row in rows]
    if values != sorted(values) or len(set(values)) != len(values):
        raise ValueError(f"{field} thresholds must be unique and ascending")


def _validate_strength_luck_pools(
    pools: tuple[StrengthLuckPool, ...],
) -> None:
    expected_ids = list(range(1, len(pools) + 1))
    if [pool.id for pool in pools] != expected_ids:
        raise ValueError("strength_luck_pools ids must be continuous from 1")
    upper_bounds = [pool.strength_upper_bound for pool in pools]
    if any(
        current >= following
        for current, following in zip(upper_bounds, upper_bounds[1:])
    ):
        raise ValueError(
            "strength_luck_pools strength upper bounds must be strictly increasing"
        )
    for index, pool in enumerate(pools):
        if pool.start_luck > pool.end_luck:
            raise ValueError(
                f"strength_luck_pools[{index}] start_luck must not exceed end_luck"
            )
class _ThresholdSelector:
    def __init__(self, rows: tuple[ThresholdItem, ...]):
        self.rows = rows
        self.thresholds = [row.denominator for row in rows]

    def select(self, roll_power: float) -> tuple[ThresholdItem, int]:
        index = bisect_right(self.thresholds, roll_power) - 1
        index = max(index, 0)
        return self.rows[index], index


class _OnlineCorrelation:
    def __init__(self) -> None:
        self.n = 0
        self.sum_x = 0.0
        self.sum_y = 0.0
        self.sum_xx = 0.0
        self.sum_yy = 0.0
        self.sum_xy = 0.0

    def add(self, x: float, y: float) -> None:
        self.n += 1
        self.sum_x += x
        self.sum_y += y
        self.sum_xx += x * x
        self.sum_yy += y * y
        self.sum_xy += x * y

    def value(self) -> float:
        if self.n < 2:
            return 0.0
        numerator = self.n * self.sum_xy - self.sum_x * self.sum_y
        denominator = math.sqrt(
            max(0.0, self.n * self.sum_xx - self.sum_x**2)
            * max(0.0, self.n * self.sum_yy - self.sum_y**2)
        )
        return numerator / denominator if denominator else 0.0


@dataclass(frozen=True)
class FishRngSimulationResult:
    summary: dict[str, Any]
    samples: list[dict[str, Any]]


class FishRngSimulator:
    def __init__(self, config: FishRngConfig):
        self.config = config
        self._fish_selector = _ThresholdSelector(config.fish_pool)
        self._trash_selector = _ThresholdSelector(config.trash_pool)

    def run(self) -> FishRngSimulationResult:
        config = self.config
        rules = ThrowRules(
            strength_luck_pools=config.strength_luck_pools,
            bonus_base_luck=config.bonus_base_luck,
            max_bonus_layers=config.max_bonus_layers,
            bonus_results=config.bonus_results,
            mutations=config.mutations,
            fish_pool=config.fish_pool,
            trash_pool=config.trash_pool,
        )

        first_layer_counts = {row.result_type: 0 for row in config.bonus_results}
        layer_reaches = [0] * config.max_bonus_layers
        mutation_counts = {row.id: 0 for row in config.mutations}
        fish_counts = {row.id: 0 for row in config.fish_pool}
        trash_counts = {row.id: 0 for row in config.trash_pool}
        multiplier_counts: dict[str, int] = {}
        throws_with_mutation = 0
        throws_with_double = 0
        total_multiplier = 0.0
        roll_power_correlation = _OnlineCorrelation()
        reward_rank_correlation = _OnlineCorrelation()
        samples: list[dict[str, Any]] = []
        for throw_index in range(1, config.throws + 1):
            outcome = resolve_throw(
                ThrowInput(
                    root_random_seed=config.random_seed,
                    throw_id=throw_index,
                    strength=config.strength,
                    regular_luck_multiplier=config.regular_luck_multiplier,
                    trash_luck=config.trash_luck,
                ),
                rules,
            )
            bonus_events = []
            for event in outcome.bonus_events:
                layer_reaches[event.layer - 1] += 1
                if event.layer == 1:
                    first_layer_counts[event.result_type] += 1
                event_payload: dict[str, Any] = {
                    "layer": event.layer,
                    "result": event.result_type,
                    "roll_power": _rounded(event.roll_power),
                }
                if event.mutation_id is not None:
                    event_payload["mutation"] = event.mutation_id
                if event.fish_luck_after is not None:
                    event_payload["fish_luck_after"] = _rounded(
                        event.fish_luck_after
                    )
                bonus_events.append(event_payload)

            if outcome.mutation is not None:
                throws_with_mutation += 1
                mutation_counts[outcome.mutation.id] += 1
            if outcome.bonus_double_count:
                throws_with_double += 1
            multiplier = outcome.final_fish_luck / outcome.strength_luck.fish_luck
            total_multiplier += multiplier
            multiplier_key = _number_key(multiplier)
            multiplier_counts[multiplier_key] = multiplier_counts.get(multiplier_key, 0) + 1

            fish_power = outcome.fish_roll_power
            trash_power = outcome.trash_roll_power
            fish = outcome.fish_reward
            trash = outcome.trash_reward
            fish_rank = self._fish_selector.rows.index(fish)
            trash_rank = self._trash_selector.rows.index(trash)
            fish_counts[fish.id] += 1
            trash_counts[trash.id] += 1
            roll_power_correlation.add(math.log10(fish_power), math.log10(trash_power))
            reward_rank_correlation.add(float(fish_rank), float(trash_rank))

            if len(samples) < config.sample_throw_count:
                samples.append(
                    {
                        "throw_index": throw_index,
                        "bonus_events": bonus_events,
                        "mutation": (
                            outcome.mutation.id if outcome.mutation else None
                        ),
                        "final_fish_luck": _rounded(outcome.final_fish_luck),
                        "fish_roll_power": _rounded(fish_power),
                        "fish_reward": fish.id,
                        "trash_roll_power": _rounded(trash_power),
                        "trash_reward": trash.id,
                    }
                )

        theoretical = _theoretical_bonus_summary(config)
        total = config.throws
        summary = {
            "schema_version": 1,
            "scenario_id": config.scenario_id,
            "random_seed": config.random_seed,
            "throws": total,
            "cycle_seconds": config.cycle_seconds,
            "represented_play_seconds": total * config.cycle_seconds,
            "strength_luck_mapping": config.strength_luck_mapping.to_ordered_dict(),
            "fish_luck": _rounded(config.fish_luck),
            "trash_luck": _rounded(config.trash_luck),
            "bonus": {
                "first_layer_observed": _probabilities(first_layer_counts, total),
                "first_layer_theoretical": theoretical["first_layer"],
                "layer_reach_observed": {
                    str(index + 1): _rounded(count / total)
                    for index, count in enumerate(layer_reaches)
                },
                "layer_reach_theoretical": theoretical["layer_reach"],
                "any_mutation_observed": _rounded(throws_with_mutation / total),
                "any_mutation_theoretical": theoretical["any_mutation"],
                "any_luck_double_observed": _rounded(throws_with_double / total),
                "any_luck_double_theoretical": theoretical["any_luck_double"],
                "expected_luck_multiplier_observed": _rounded(
                    total_multiplier / total
                ),
                "expected_luck_multiplier_theoretical": theoretical[
                    "expected_luck_multiplier"
                ],
                "luck_multiplier_distribution": _probabilities(
                    multiplier_counts, total
                ),
            },
            "mutations": {
                "counts": mutation_counts,
                "probabilities_per_throw": _probabilities(mutation_counts, total),
                "conditional_probabilities": _probabilities(
                    mutation_counts, max(throws_with_mutation, 1)
                ),
            },
            "fish": {
                "counts": fish_counts,
                "probabilities": _probabilities(fish_counts, total),
            },
            "trash": {
                "counts": trash_counts,
                "probabilities": _probabilities(trash_counts, total),
            },
            "independence": {
                "log_roll_power_pearson": _rounded(roll_power_correlation.value()),
                "reward_rank_pearson": _rounded(reward_rank_correlation.value()),
            },
        }
        return FishRngSimulationResult(summary=summary, samples=samples)

    def _select_bonus(
        self, roll_power: float, can_select_mutation: bool
    ) -> BonusResult:
        return select_bonus(
            self.config.bonus_results,
            roll_power,
            can_select_mutation,
        )


def _selection_probabilities(
    config: FishRngConfig, can_select_mutation: bool
) -> dict[str, float]:
    available = [
        row
        for row in config.bonus_results
        if can_select_mutation or row.result_type != "mutation"
    ]
    reaches = [
        min(1.0, config.bonus_base_luck / row.roll_power_requirement)
        for row in available
    ]
    result: dict[str, float] = {}
    for index, row in enumerate(available):
        next_reach = reaches[index + 1] if index + 1 < len(reaches) else 0.0
        result[row.result_type] = max(0.0, reaches[index] - next_reach)
    return result


def _theoretical_bonus_summary(config: FishRngConfig) -> dict[str, Any]:
    first = _selection_probabilities(config, True)
    locked = _selection_probabilities(config, False)
    states: dict[tuple[bool, int], float] = {(False, 0): 1.0}
    layer_reach: dict[str, float] = {}
    finished: dict[tuple[bool, int], float] = {}

    for layer in range(1, config.max_bonus_layers + 1):
        layer_reach[str(layer)] = _rounded(sum(states.values()))
        next_states: dict[tuple[bool, int], float] = {}
        for (mutated, doubles), state_probability in states.items():
            choices = locked if mutated else first
            for result_type, result_probability in choices.items():
                probability = state_probability * result_probability
                next_mutated = mutated or result_type == "mutation"
                next_doubles = doubles + (1 if result_type == "luck_double" else 0)
                key = (next_mutated, next_doubles)
                if result_type == "no_bonus" or layer == config.max_bonus_layers:
                    finished[key] = finished.get(key, 0.0) + probability
                else:
                    next_states[key] = next_states.get(key, 0.0) + probability
        states = next_states

    any_mutation = sum(
        probability for (mutated, _), probability in finished.items() if mutated
    )
    any_double = sum(
        probability for (_, doubles), probability in finished.items() if doubles
    )
    expected_multiplier = sum(
        (2**doubles) * probability
        for (_, doubles), probability in finished.items()
    )
    return {
        "first_layer": {key: _rounded(value) for key, value in first.items()},
        "layer_reach": layer_reach,
        "any_mutation": _rounded(any_mutation),
        "any_luck_double": _rounded(any_double),
        "expected_luck_multiplier": _rounded(expected_multiplier),
    }


def _probabilities(counts: dict[str, int], total: int) -> dict[str, float]:
    return {key: _rounded(value / total) for key, value in counts.items()}


def _rounded(value: float) -> float:
    return round(value, 8)


def _number_key(value: float) -> str:
    return str(int(value)) if value.is_integer() else str(value)
