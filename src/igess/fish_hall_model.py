from __future__ import annotations

import json
from dataclasses import dataclass

from .numbers import SimNumber


@dataclass(frozen=True)
class FishIncomeTrace:
    instance_id: int
    fish_id: int
    mutation_id: int
    level: int
    base_money_per_second: SimNumber
    level_income_multiplier: SimNumber
    level_money_per_second: SimNumber
    mutation_income_multiplier: SimNumber
    income_per_second: SimNumber

    def event_entry(self) -> dict[str, int | str]:
        return {
            "instance_id": self.instance_id,
            "fish_id": self.fish_id,
            "mutation_id": self.mutation_id,
            "level": self.level,
            "base_money_per_second": (
                self.base_money_per_second.to_decimal_string()
            ),
            "level_income_multiplier": (
                self.level_income_multiplier.to_decimal_string()
            ),
            "level_money_per_second": (
                self.level_money_per_second.to_decimal_string()
            ),
            "mutation_income_multiplier": (
                self.mutation_income_multiplier.to_decimal_string()
            ),
            "formula": (
                "base_money_per_second*1.25^(level-1)"
                "*mutation_income_multiplier"
            ),
            "income_per_second": self.income_per_second.to_decimal_string(),
        }


@dataclass(frozen=True)
class StrengthRebirthRule:
    completed_count: int
    strength_requirement: SimNumber
    fish_hall_output_multiplier: SimNumber


@dataclass(frozen=True)
class FishHallIncomeSnapshot:
    capacity: int
    deployed_instance_ids: tuple[int, ...]
    base_total_income_per_second: SimNumber
    strength_rebirth_completed_count: int
    strength_rebirth_multiplier: SimNumber
    total_income_per_second: SimNumber
    traces: tuple[FishIncomeTrace, ...]

    def event_details(self, *, suffix: str = "") -> dict[str, str]:
        label = f"_{suffix}" if suffix else ""
        multiplier_source = (
            "default_1x_not_in_table"
            if self.strength_rebirth_completed_count == 0
            else (
                "tbstrengthrebirth"
                f"[id={self.strength_rebirth_completed_count}]"
                ".fishHallOutputMultiplier"
            )
        )
        return {
            f"fish_hall_policy{label}": "fixed_max_income",
            f"fish_hall_tie_breaker{label}": "instance_id_ascending",
            f"fish_hall_capacity{label}": str(self.capacity),
            f"fish_hall_deployed_instance_ids{label}": json.dumps(
                self.deployed_instance_ids,
                separators=(",", ":"),
            ),
            f"fish_hall_income_per_second{label}": (
                self.total_income_per_second.to_decimal_string()
            ),
            f"fish_hall_base_income_per_second{label}": (
                self.base_total_income_per_second.to_decimal_string()
            ),
            f"strength_rebirth_completed_count{label}": str(
                self.strength_rebirth_completed_count
            ),
            f"strength_rebirth_fish_hall_multiplier{label}": (
                self.strength_rebirth_multiplier.to_decimal_string()
            ),
            f"strength_rebirth_fish_hall_multiplier_source{label}": (
                multiplier_source
            ),
            f"fish_hall_income_formula{label}": (
                "sum(deployed_fish_income_per_second)"
                "*strength_rebirth_fish_hall_multiplier"
            ),
            f"fish_hall_formula_trace{label}": json.dumps(
                [trace.event_entry() for trace in self.traces],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        }
