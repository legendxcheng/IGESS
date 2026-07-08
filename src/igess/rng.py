from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass
from typing import Any

from .numbers import SimNumber
from .schema import EconomyModel, RngRarity

_MIN_RANDOM_FLOAT = 1e-16


@dataclass(frozen=True)
class RngProfileSummary:
    scenario_id: str
    profile_id: str
    rolls: int
    trials: int
    total_rolls: int
    rarity_counts: dict[str, int]
    theoretical_probabilities: dict[str, str]
    theoretical_pick_probabilities: dict[str, str]
    observed_probabilities: dict[str, str]

    def to_ordered_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "profile_id": self.profile_id,
            "rolls": self.rolls,
            "trials": self.trials,
            "total_rolls": self.total_rolls,
            "rarity_counts": dict(sorted(self.rarity_counts.items())),
            "theoretical_probabilities": dict(sorted(self.theoretical_probabilities.items())),
            "theoretical_pick_probabilities": dict(
                sorted(self.theoretical_pick_probabilities.items())
            ),
            "observed_probabilities": dict(sorted(self.observed_probabilities.items())),
        }


@dataclass(frozen=True)
class RngTrialRow:
    scenario_id: str
    profile_id: str
    trial_index: int
    best_rarity: str
    first_hits: dict[str, int]

    def to_ordered_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "profile_id": self.profile_id,
            "trial_index": self.trial_index,
            "best_rarity": self.best_rarity,
            "first_hits": dict(sorted(self.first_hits.items())),
        }


@dataclass(frozen=True)
class RngRollEvent:
    scenario_id: str
    profile_id: str
    trial_index: int
    roll_index: int
    rarity_id: str
    denominator: str

    def to_ordered_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "profile_id": self.profile_id,
            "trial_index": self.trial_index,
            "roll_index": self.roll_index,
            "rarity_id": self.rarity_id,
            "denominator": self.denominator,
        }


@dataclass(frozen=True)
class RngSimulationResult:
    scenario_id: str
    summaries: list[RngProfileSummary]
    distribution: list[RngTrialRow]
    events: list[RngRollEvent]


def rarity_probability(luck: SimNumber, denominator: SimNumber) -> SimNumber:
    if denominator <= SimNumber.zero():
        raise ValueError("rarity denominator must be positive")
    if luck >= denominator:
        return SimNumber.one()
    return luck / denominator


def select_rarity_by_log_power(
    rarities: list[RngRarity], luck: SimNumber, u: float
) -> RngRarity:
    if not rarities:
        raise ValueError("rarities must not be empty")
    if luck <= SimNumber.zero():
        raise ValueError("luck must be positive")
    log_power = _log10_float(luck) - math.log10(max(u, _MIN_RANDOM_FLOAT))
    selected = rarities[0]
    for rarity in sorted(rarities, key=lambda item: item.denominator):
        if log_power >= _log10_float(rarity.denominator):
            selected = rarity
    return selected


class RarityScoreSelector:
    def __init__(self, rarities: list[RngRarity], luck: SimNumber):
        if not rarities:
            raise ValueError("rarities must not be empty")
        if luck <= SimNumber.zero():
            raise ValueError("luck must be positive")
        self.luck_log10 = _log10_float(luck)
        self.thresholds = [
            (_log10_float(rarity.denominator), rarity)
            for rarity in sorted(rarities, key=lambda item: item.denominator)
        ]

    def select(self, u: float) -> RngRarity:
        log_power = self.luck_log10 - math.log10(max(u, _MIN_RANDOM_FLOAT))
        selected = self.thresholds[0][1]
        for threshold, rarity in self.thresholds:
            if log_power >= threshold:
                selected = rarity
        return selected


class RngSimulator:
    def __init__(self, model: EconomyModel):
        self.model = model

    def run_scenario(self, scenario_id: str) -> RngSimulationResult:
        scenario = self.model.rng_scenarios[scenario_id]
        table = self.model.rng_tables[scenario.table]
        summaries: list[RngProfileSummary] = []
        distribution: list[RngTrialRow] = []
        events: list[RngRollEvent] = []
        threshold = self._event_threshold(table.rarities, scenario.event_threshold)

        for profile_id in scenario.profiles:
            profile = self.model.player_profiles[profile_id]
            selector = RarityScoreSelector(table.rarities, profile.luck)
            rarity_rank = {rarity.id: index for index, rarity in enumerate(table.rarities)}
            counts = {rarity.id: 0 for rarity in table.rarities}
            for trial_index in range(1, scenario.trials + 1):
                rng = random.Random(
                    _stable_seed(
                        self.model.config.random_seed,
                        scenario_id,
                        profile_id,
                        trial_index,
                    )
                )
                first_hits: dict[str, int] = {}
                best = table.rarities[0]
                best_rank = 0
                for roll_index in range(1, scenario.rolls + 1):
                    rarity = selector.select(rng.random())
                    counts[rarity.id] += 1
                    first_hits.setdefault(rarity.id, roll_index)
                    rank = rarity_rank[rarity.id]
                    if rank > best_rank:
                        best = rarity
                        best_rank = rank
                    if threshold is not None and rarity.denominator >= threshold.denominator:
                        events.append(
                            RngRollEvent(
                                scenario_id=scenario_id,
                                profile_id=profile_id,
                                trial_index=trial_index,
                                roll_index=roll_index,
                                rarity_id=rarity.id,
                                denominator=rarity.denominator.to_decimal_string(),
                            )
                        )
                distribution.append(
                    RngTrialRow(
                        scenario_id=scenario_id,
                        profile_id=profile_id,
                        trial_index=trial_index,
                        best_rarity=best.id,
                        first_hits=first_hits,
                    )
                )
            total_rolls = scenario.rolls * scenario.trials
            theoretical_reach = {
                rarity.id: rarity_probability(profile.luck, rarity.denominator)
                for rarity in table.rarities
            }
            summaries.append(
                RngProfileSummary(
                    scenario_id=scenario_id,
                    profile_id=profile_id,
                    rolls=scenario.rolls,
                    trials=scenario.trials,
                    total_rolls=total_rolls,
                    rarity_counts=counts,
                    theoretical_probabilities={
                        rarity.id: theoretical_reach[rarity.id].to_decimal_string()
                        for rarity in table.rarities
                    },
                    theoretical_pick_probabilities=_rarity_pick_probabilities(
                        table.rarities, theoretical_reach
                    ),
                    observed_probabilities={
                        rarity.id: (
                            SimNumber.parse(counts[rarity.id]) / SimNumber.parse(total_rolls)
                        ).to_decimal_string()
                        for rarity in table.rarities
                    },
                )
            )
        return RngSimulationResult(
            scenario_id=scenario_id,
            summaries=summaries,
            distribution=distribution,
            events=events,
        )

    def _event_threshold(
        self, rarities: list[RngRarity], threshold_id: str | None
    ) -> RngRarity | None:
        if threshold_id is None:
            return None
        return next(rarity for rarity in rarities if rarity.id == threshold_id)


def _stable_seed(*parts: object) -> int:
    payload = "|".join(str(part) for part in parts).encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def _log10_float(value: SimNumber) -> float:
    if value.sign <= 0 or value.log10_abs is None:
        raise ValueError("log10 requires a positive SimNumber")
    return float(value.log10_abs)


def _rarity_pick_probabilities(
    rarities: list[RngRarity], reach_probabilities: dict[str, SimNumber]
) -> dict[str, str]:
    probabilities: dict[str, str] = {}
    for index, rarity in enumerate(rarities):
        reach = reach_probabilities[rarity.id]
        if index + 1 < len(rarities):
            next_reach = reach_probabilities[rarities[index + 1].id]
            probability = reach - next_reach
        else:
            probability = reach
        if probability < SimNumber.zero():
            probability = SimNumber.zero()
        probabilities[rarity.id] = probability.to_decimal_string()
    return probabilities
