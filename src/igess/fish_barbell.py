from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from .fish_data import FishDataError, FishDataSnapshot
from .fish_state import PlayerState
from .numbers import SimNumber


@dataclass(frozen=True)
class BarbellRule:
    barbell_id: int
    name: str
    strength_per_exercise: SimNumber
    price: SimNumber
    rarity_id: int
    time_cost_seconds: int

    @property
    def strength_per_second(self) -> SimNumber:
        return self.strength_per_exercise / SimNumber.parse(
            self.time_cost_seconds
        )


@dataclass(frozen=True)
class BarbellProductionSnapshot:
    equipped_id: int
    equipped_count: int
    strength_per_exercise: SimNumber
    time_cost_seconds: int
    strength_per_second: SimNumber

    def event_details(self, *, suffix: str = "") -> dict[str, str]:
        label = f"_{suffix}" if suffix else ""
        return {
            f"barbell_equipped_id{label}": str(self.equipped_id),
            f"barbell_equipped_count{label}": str(self.equipped_count),
            f"barbell_strength_per_exercise{label}": (
                self.strength_per_exercise.to_decimal_string()
            ),
            f"barbell_time_cost_seconds{label}": str(self.time_cost_seconds),
            f"barbell_strength_per_second{label}": (
                self.strength_per_second.to_decimal_string()
            ),
            f"barbell_strength_formula{label}": (
                "strengthPerExercise/timeCost"
            ),
            f"barbell_owned_count_affects_output{label}": "false",
        }


class FishBarbellDataAdapter:
    """Production Barbell rules used by synthesis and strength settlement."""

    def __init__(self, snapshot: FishDataSnapshot) -> None:
        self.data = snapshot
        self._rules = self._load_rules()

    @property
    def rules(self) -> tuple[BarbellRule, ...]:
        return tuple(self._rules[key] for key in sorted(self._rules))

    def rule(self, barbell_id: int) -> BarbellRule:
        if type(barbell_id) is not int or barbell_id <= 0:
            raise FishDataError("barbell id must be a positive integer")
        try:
            return self._rules[barbell_id]
        except KeyError as exc:
            raise FishDataError(
                f"unknown production barbell id: {barbell_id}"
            ) from exc

    def synthesis_price(self, barbell_id: int) -> SimNumber:
        return self.rule(barbell_id).price

    def strength_per_second(self, barbell_id: int) -> SimNumber:
        return self.rule(barbell_id).strength_per_second

    def best_owned_id(self, state: PlayerState) -> int:
        owned_ids = [
            entry.barbell_id
            for entry in state.barbell.owned
            if entry.count > 0
        ]
        if not owned_ids:
            return 0
        for barbell_id in owned_ids:
            self.rule(barbell_id)
        return min(
            owned_ids,
            key=lambda barbell_id: (
                -self.strength_per_second(barbell_id),
                barbell_id,
            ),
        )

    def production_snapshot(
        self,
        state: PlayerState,
    ) -> BarbellProductionSnapshot:
        equipped_id = state.barbell.equipped_id
        if equipped_id == 0:
            return BarbellProductionSnapshot(
                equipped_id=0,
                equipped_count=0,
                strength_per_exercise=SimNumber.zero(),
                time_cost_seconds=0,
                strength_per_second=SimNumber.zero(),
            )
        try:
            owned = next(
                entry
                for entry in state.barbell.owned
                if entry.barbell_id == equipped_id
            )
        except StopIteration as exc:
            raise FishDataError(
                "equipped barbell is not present in PlayerState.barbell.owned"
            ) from exc
        if owned.count <= 0:
            raise FishDataError("equipped barbell count must be positive")
        rule = self.rule(equipped_id)
        return BarbellProductionSnapshot(
            equipped_id=equipped_id,
            equipped_count=owned.count,
            strength_per_exercise=rule.strength_per_exercise,
            time_cost_seconds=rule.time_cost_seconds,
            strength_per_second=rule.strength_per_second,
        )

    def _load_rules(self) -> dict[int, BarbellRule]:
        result: dict[int, BarbellRule] = {}
        for row in self.data.table("tbbarbell"):
            row_id = _positive_int(
                _field(row, "id", "tbbarbell"),
                "tbbarbell.id",
            )
            if row_id in result:
                raise FishDataError(
                    f"tbbarbell contains duplicate id: {row_id}"
                )
            name = _field(row, "name", "tbbarbell")
            if not isinstance(name, str) or not name:
                raise FishDataError(
                    f"tbbarbell.{row_id}.name must be a non-empty string"
                )
            result[row_id] = BarbellRule(
                barbell_id=row_id,
                name=name,
                strength_per_exercise=_positive_sim_number(
                    _field(row, "strengthPerExercise", "tbbarbell"),
                    f"tbbarbell.{row_id}.strengthPerExercise",
                ),
                price=_positive_sim_number(
                    _field(row, "price", "tbbarbell"),
                    f"tbbarbell.{row_id}.price",
                ),
                rarity_id=_positive_int(
                    _field(row, "rarityId", "tbbarbell"),
                    f"tbbarbell.{row_id}.rarityId",
                ),
                time_cost_seconds=_positive_int(
                    _field(row, "timeCost", "tbbarbell"),
                    f"tbbarbell.{row_id}.timeCost",
                ),
            )
        if not result:
            raise FishDataError("tbbarbell must contain at least one row")
        return result


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
    if isinstance(value, bool):
        raise FishDataError(f"{field} must be a positive number")
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
        raise FishDataError(f"{field} must be a positive number") from exc
    if parsed <= SimNumber.zero():
        raise FishDataError(f"{field} must be a positive number")
    return parsed
