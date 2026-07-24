from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Sequence

from .fish_data import FishDataError, FishDataSnapshot
from .fish_state import (
    FISH_MAX_LEVEL,
    FishInstance,
    FishStateValidationContext,
    PlayerState,
)
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


class FishHallDataAdapter:
    """Production Fish tables needed by fixed max-income hall simulation."""

    def __init__(self, snapshot: FishDataSnapshot) -> None:
        self.data = snapshot
        self._fish_base_income = self._fish_income_rows()
        self._mutation_income_multiplier = self._mutation_rows()
        hall_rows = tuple(self.data.table("tbfishhallupgrade"))
        self._capacities = self._hall_capacities(hall_rows)
        self._hall_upgrade_prices = self._hall_prices(hall_rows)
        self._strength_rebirth_rules = self._strength_rebirth_rows()

    def capacity(self, upgrade_level: int) -> int:
        if type(upgrade_level) is not int or upgrade_level < 0:
            raise FishDataError("fish hall upgrade level must be non-negative")
        if upgrade_level >= len(self._capacities):
            raise FishDataError(
                f"fish hall upgrade level is out of range: {upgrade_level}"
            )
        return self._capacities[upgrade_level]

    def can_upgrade_hall(self, upgrade_level: int) -> bool:
        """Return whether the current level has a following table row."""

        self.capacity(upgrade_level)
        return upgrade_level + 1 < len(self._capacities)

    @property
    def max_hall_upgrade_level(self) -> int:
        return len(self._capacities) - 1

    def hall_upgrade_price(self, upgrade_level: int) -> SimNumber:
        """Read the price from the current level row, never from the next row."""

        if not self.can_upgrade_hall(upgrade_level):
            raise FishDataError(
                f"fish hall is already at max upgrade level: {upgrade_level}"
            )
        return self._hall_upgrade_prices[upgrade_level]

    @property
    def max_strength_rebirth_count(self) -> int:
        return len(self._strength_rebirth_rules)

    def strength_rebirth_rule(
        self,
        completed_count: int,
    ) -> StrengthRebirthRule:
        """Return the row earned after exactly ``completed_count`` rebirths."""

        self._validate_strength_rebirth_count(completed_count)
        if completed_count == 0:
            raise FishDataError(
                "strength rebirth count 0 has the default 1x multiplier "
                "and no table row"
            )
        return self._strength_rebirth_rules[completed_count - 1]

    def next_strength_rebirth_rule(
        self,
        completed_count: int,
    ) -> StrengthRebirthRule:
        """Return the requirement and reward for the next rebirth."""

        self._validate_strength_rebirth_count(completed_count)
        if completed_count >= self.max_strength_rebirth_count:
            raise FishDataError(
                "strength rebirth is already at max completed count: "
                f"{completed_count}"
            )
        return self.strength_rebirth_rule(completed_count + 1)

    def strength_rebirth_multiplier(
        self,
        completed_count: int,
    ) -> SimNumber:
        """Map 0 to the implicit 1x default and n>=1 to table id n."""

        self._validate_strength_rebirth_count(completed_count)
        if completed_count == 0:
            return SimNumber.one()
        return self.strength_rebirth_rule(
            completed_count
        ).fish_hall_output_multiplier

    def can_strength_rebirth(self, state: PlayerState) -> bool:
        if not isinstance(state, PlayerState):
            raise FishDataError("state must be a PlayerState")
        completed_count = state.rebirth.strength_completed_count
        self._validate_strength_rebirth_count(completed_count)
        if completed_count >= self.max_strength_rebirth_count:
            return False
        return (
            state.wallet.strength.to_sim_number()
            >= self.next_strength_rebirth_rule(
                completed_count
            ).strength_requirement
        )

    def validation_context(self) -> FishStateValidationContext:
        return FishStateValidationContext(fish_hall_capacity=self.capacity)

    def expected_layout(self, state: PlayerState) -> dict[int, int]:
        ranked = self._ranked_traces(state.fish.items)
        selected = ranked[: self.capacity(state.fish_hall.upgrade_level)]
        return {
            trace.instance_id: slot
            for slot, trace in enumerate(selected, start=1)
        }

    def income_trace(self, item: FishInstance) -> FishIncomeTrace:
        return self._income_trace(item)

    def upgrade_price(self, item: FishInstance) -> SimNumber:
        self._validate_fish_level(item.level)
        if item.level >= FISH_MAX_LEVEL:
            raise FishDataError(
                f"fish instance is already at max level: {item.instance_id}"
            )
        base = self._fish_base(item.fish_id)
        return base * (SimNumber.parse("1.5") ** (item.level - 1))

    def snapshot(self, state: PlayerState) -> FishHallIncomeSnapshot:
        expected = self.expected_layout(state)
        actual = {item.instance_id: item.hall_slot for item in state.fish.items}
        expected_all = {
            item.instance_id: expected.get(item.instance_id, 0)
            for item in state.fish.items
        }
        if actual != expected_all:
            raise FishDataError(
                "PlayerState fish hall does not match fixed max_income layout"
            )
        traces_by_id = {
            trace.instance_id: trace
            for trace in self._ranked_traces(state.fish.items)
        }
        deployed_ids = tuple(
            instance_id
            for instance_id, _slot in sorted(
                expected.items(),
                key=lambda item: item[1],
            )
        )
        traces = tuple(traces_by_id[instance_id] for instance_id in deployed_ids)
        base_total = sum(
            (trace.income_per_second for trace in traces),
            SimNumber.zero(),
        )
        strength_rebirth_multiplier = self.strength_rebirth_multiplier(
            state.rebirth.strength_completed_count
        )
        return FishHallIncomeSnapshot(
            capacity=self.capacity(state.fish_hall.upgrade_level),
            deployed_instance_ids=deployed_ids,
            base_total_income_per_second=base_total,
            strength_rebirth_completed_count=(
                state.rebirth.strength_completed_count
            ),
            strength_rebirth_multiplier=strength_rebirth_multiplier,
            total_income_per_second=(
                base_total * strength_rebirth_multiplier
            ),
            traces=traces,
        )

    def _ranked_traces(
        self,
        items: Sequence[FishInstance],
    ) -> list[FishIncomeTrace]:
        traces = [self._income_trace(item) for item in items]
        traces.sort(key=lambda trace: trace.instance_id)
        traces.sort(
            key=lambda trace: trace.income_per_second,
            reverse=True,
        )
        return traces

    def _income_trace(self, item: FishInstance) -> FishIncomeTrace:
        self._validate_fish_level(item.level)
        base = self._fish_base(item.fish_id)
        try:
            mutation_multiplier = self._mutation_income_multiplier[
                item.mutation_id
            ]
        except KeyError as exc:
            raise FishDataError(
                f"unknown production mutation id: {item.mutation_id}"
            ) from exc
        level_multiplier = SimNumber.parse("1.25") ** (item.level - 1)
        level_money_per_second = base * level_multiplier
        return FishIncomeTrace(
            instance_id=item.instance_id,
            fish_id=item.fish_id,
            mutation_id=item.mutation_id,
            level=item.level,
            base_money_per_second=base,
            level_income_multiplier=level_multiplier,
            level_money_per_second=level_money_per_second,
            mutation_income_multiplier=mutation_multiplier,
            income_per_second=(
                level_money_per_second * mutation_multiplier
            ),
        )

    def _fish_base(self, fish_id: int) -> SimNumber:
        try:
            return self._fish_base_income[fish_id]
        except KeyError as exc:
            raise FishDataError(
                f"unknown production fish id: {fish_id}"
            ) from exc

    @staticmethod
    def _validate_fish_level(level: int) -> None:
        if type(level) is not int or not 1 <= level <= FISH_MAX_LEVEL:
            raise FishDataError(
                f"fish level must be within 1..{FISH_MAX_LEVEL}: {level}"
            )

    def _fish_income_rows(self) -> dict[int, SimNumber]:
        result: dict[int, SimNumber] = {}
        for row in self.data.table("tbfish"):
            row_id = _positive_int(_field(row, "id", "tbfish"), "tbfish.id")
            if row_id in result:
                raise FishDataError(f"tbfish contains duplicate id: {row_id}")
            result[row_id] = _positive_sim_number(
                _field(row, "baseMoneyPerSecond", "tbfish"),
                f"tbfish.{row_id}.baseMoneyPerSecond",
            )
        return result

    def _mutation_rows(self) -> dict[int, SimNumber]:
        result: dict[int, SimNumber] = {}
        for row in self.data.table("tbmutation"):
            row_id = _positive_int(
                _field(row, "id", "tbmutation"),
                "tbmutation.id",
            )
            if row_id in result:
                raise FishDataError(f"tbmutation contains duplicate id: {row_id}")
            result[row_id] = _positive_sim_number(
                _field(row, "incomeMultiplier", "tbmutation"),
                f"tbmutation.{row_id}.incomeMultiplier",
            )
        return result

    def _hall_capacities(self, rows: Sequence[Any]) -> tuple[int, ...]:
        result = tuple(
            _positive_int(
                _field(row, "slotQty", "tbfishhallupgrade"),
                f"tbfishhallupgrade.{index}.slotQty",
            )
            for index, row in enumerate(
                rows,
                start=1,
            )
        )
        if not result:
            raise FishDataError("tbfishhallupgrade must contain an initial row")
        if any(
            next_capacity <= current_capacity
            for current_capacity, next_capacity in zip(result, result[1:])
        ):
            raise FishDataError(
                "tbfishhallupgrade.slotQty must be strictly increasing "
                "by upgrade level"
            )
        return result

    @staticmethod
    def _hall_prices(rows: Sequence[Any]) -> tuple[SimNumber, ...]:
        purchasable = tuple(
            _positive_sim_number(
                _field(row, "upgradePrice", "tbfishhallupgrade"),
                f"tbfishhallupgrade.{upgrade_level}.upgradePrice",
            )
            for upgrade_level, row in enumerate(rows[:-1])
        )
        final_price = _nonnegative_sim_number(
            _field(rows[-1], "upgradePrice", "tbfishhallupgrade"),
            f"tbfishhallupgrade.{len(rows) - 1}.upgradePrice",
        )
        if final_price != SimNumber.zero():
            raise FishDataError(
                "tbfishhallupgrade final upgradePrice must be 0 "
                "as the max-level sentinel"
            )
        return purchasable

    def _strength_rebirth_rows(self) -> tuple[StrengthRebirthRule, ...]:
        by_id: dict[int, StrengthRebirthRule] = {}
        for row in self.data.table("tbstrengthrebirth"):
            completed_count = _positive_int(
                _field(row, "id", "tbstrengthrebirth"),
                "tbstrengthrebirth.id",
            )
            if completed_count in by_id:
                raise FishDataError(
                    "tbstrengthrebirth contains duplicate id: "
                    f"{completed_count}"
                )
            by_id[completed_count] = StrengthRebirthRule(
                completed_count=completed_count,
                strength_requirement=_positive_sim_number(
                    _field(
                        row,
                        "strengthRequirement",
                        "tbstrengthrebirth",
                    ),
                    (
                        "tbstrengthrebirth."
                        f"{completed_count}.strengthRequirement"
                    ),
                ),
                fish_hall_output_multiplier=_positive_sim_number(
                    _field(
                        row,
                        "fishHallOutputMultiplier",
                        "tbstrengthrebirth",
                    ),
                    (
                        "tbstrengthrebirth."
                        f"{completed_count}.fishHallOutputMultiplier"
                    ),
                ),
            )
        if not by_id:
            raise FishDataError(
                "tbstrengthrebirth must contain at least one row"
            )
        expected_ids = set(range(1, len(by_id) + 1))
        if set(by_id) != expected_ids:
            raise FishDataError(
                "tbstrengthrebirth ids must be contiguous and start at 1"
            )
        return tuple(by_id[row_id] for row_id in sorted(by_id))

    def _validate_strength_rebirth_count(
        self,
        completed_count: int,
    ) -> None:
        if type(completed_count) is not int or completed_count < 0:
            raise FishDataError(
                "strength rebirth completed count must be non-negative"
            )
        if completed_count > self.max_strength_rebirth_count:
            raise FishDataError(
                "strength rebirth completed count is out of range: "
                f"{completed_count}"
            )


def _field(row: Any, name: str, table_name: str) -> Any:
    try:
        return getattr(row, name)
    except AttributeError as exc:
        raise FishDataError(
            f"generated {table_name} row is missing field: {name}"
        ) from exc


def _positive_int(value: Any, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise FishDataError(f"{field} must be a positive integer")
    return value


def _positive_sim_number(value: Any, field: str) -> SimNumber:
    parsed = _sim_number(value, field)
    if parsed <= SimNumber.zero():
        raise FishDataError(f"{field} must be a positive number")
    return parsed


def _nonnegative_sim_number(value: Any, field: str) -> SimNumber:
    parsed = _sim_number(value, field)
    if parsed < SimNumber.zero():
        raise FishDataError(f"{field} must be a non-negative number")
    return parsed


def _sim_number(value: Any, field: str) -> SimNumber:
    if isinstance(value, bool):
        raise FishDataError(f"{field} must be a number")
    if isinstance(value, (Decimal, int, float, str, SimNumber)):
        raw = value
    else:
        try:
            sign = getattr(value, "sign")
            digits = getattr(value, "digits")
            scale = getattr(value, "scale")
        except AttributeError as exc:
            raise FishDataError(f"{field} must be a generated number") from exc
        if type(sign) is not int or sign not in {-1, 0, 1}:
            raise FishDataError(f"{field}.sign must be -1, 0, or 1")
        if not isinstance(digits, str) or not digits or not digits.isdigit():
            raise FishDataError(f"{field}.digits must contain decimal digits")
        if type(scale) is not int:
            raise FishDataError(f"{field}.scale must be an integer")
        prefix = "-" if sign < 0 else ""
        raw = f"{prefix}{digits}e{scale}" if sign else "0"
    try:
        parsed = SimNumber.parse(raw)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise FishDataError(f"{field} must be a number") from exc
    return parsed
