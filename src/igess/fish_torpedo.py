from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from .fish_data import FishDataError, FishDataSnapshot
from .fish_throw import TrashLuckPool, map_torpedo_power_to_trash_luck
from .numbers import SimNumber


@dataclass(frozen=True)
class TorpedoRule:
    torpedo_id: int
    name: str
    power: SimNumber
    price: SimNumber
    rarity_id: int
    trash_luck: float


class FishTorpedoDataAdapter:
    """Production Torpedo rules used by purchase behavior."""

    def __init__(
        self,
        snapshot: FishDataSnapshot,
        *,
        trash_luck_pools: tuple[TrashLuckPool, ...],
        regular_luck_multiplier: float,
    ) -> None:
        self.data = snapshot
        self._trash_luck_pools = trash_luck_pools
        self._regular_luck_multiplier = regular_luck_multiplier
        self._rules = self._load_rules()

    @property
    def rules(self) -> tuple[TorpedoRule, ...]:
        return tuple(self._rules[key] for key in sorted(self._rules))

    def rule(self, torpedo_id: int) -> TorpedoRule:
        if type(torpedo_id) is not int or torpedo_id <= 0:
            raise FishDataError("torpedo id must be a positive integer")
        try:
            return self._rules[torpedo_id]
        except KeyError as exc:
            raise FishDataError(
                f"unknown production torpedo id: {torpedo_id}"
            ) from exc

    def _load_rules(self) -> dict[int, TorpedoRule]:
        result: dict[int, TorpedoRule] = {}
        previous_power = SimNumber.zero()
        for row in self.data.table("tbtorpedo"):
            row_id = _positive_int(
                _field(row, "id", "tbtorpedo"),
                "tbtorpedo.id",
            )
            if row_id in result:
                raise FishDataError(
                    f"tbtorpedo contains duplicate id: {row_id}"
                )
            name = _field(row, "name", "tbtorpedo")
            if not isinstance(name, str) or not name:
                raise FishDataError(
                    f"tbtorpedo.{row_id}.name must be a non-empty string"
                )
            power = _sim_number(
                _field(row, "power", "tbtorpedo"),
                f"tbtorpedo.{row_id}.power",
                allow_zero=False,
            )
            if power <= previous_power:
                raise FishDataError(
                    "tbtorpedo power must increase in id order"
                )
            previous_power = power
            mapping = map_torpedo_power_to_trash_luck(
                power.to_float(),
                self._trash_luck_pools,
                self._regular_luck_multiplier,
            )
            result[row_id] = TorpedoRule(
                torpedo_id=row_id,
                name=name,
                power=power,
                price=_sim_number(
                    _field(row, "price", "tbtorpedo"),
                    f"tbtorpedo.{row_id}.price",
                    allow_zero=(not result),
                ),
                rarity_id=_positive_int(
                    _field(row, "rarityId", "tbtorpedo"),
                    f"tbtorpedo.{row_id}.rarityId",
                ),
                trash_luck=mapping.trash_luck,
            )
        if not result:
            raise FishDataError("tbtorpedo must contain at least one row")
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


def _sim_number(
    value: Any,
    field: str,
    *,
    allow_zero: bool,
) -> SimNumber:
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
    if parsed < SimNumber.zero() or (not allow_zero and parsed.is_zero()):
        qualifier = "non-negative" if allow_zero else "positive"
        raise FishDataError(f"{field} must be a {qualifier} number")
    return parsed
