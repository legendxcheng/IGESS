from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, getcontext
from typing import Any

getcontext().prec = 80


@dataclass(frozen=True, order=True)
class SimNumber:
    """Deterministic numeric wrapper for economy values.

    v0.1 keeps exact decimal values while exposing one numeric surface to the
    simulation. This avoids Float64 precision traps and leaves room to swap in
    a stricter sign/log backend behind the same API.
    """

    _value: Decimal
    backend: str = "bignum_log"

    @classmethod
    def parse(cls, value: Any) -> "SimNumber":
        if isinstance(value, SimNumber):
            return value
        if isinstance(value, Decimal):
            return cls(value)
        if isinstance(value, int):
            return cls(Decimal(value))
        if isinstance(value, float):
            return cls(Decimal(str(value)))
        return cls(Decimal(str(value)))

    @classmethod
    def zero(cls) -> "SimNumber":
        return cls(Decimal(0))

    @classmethod
    def one(cls) -> "SimNumber":
        return cls(Decimal(1))

    @classmethod
    def from_decimal(cls, value: Decimal) -> "SimNumber":
        return cls(value)

    @property
    def decimal(self) -> Decimal:
        return self._value

    def is_zero(self) -> bool:
        return self._value == 0

    def to_decimal_string(self) -> str:
        if self._value == 0:
            return "0"
        normalized = self._value.normalize()
        adjusted = normalized.adjusted()
        if adjusted >= 30 or adjusted <= -8:
            return str(normalized)
        text = format(normalized, "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return text or "0"

    def to_float(self) -> float:
        return float(self._value)

    def floor(self) -> "SimNumber":
        return SimNumber(self._value.to_integral_value(rounding=ROUND_FLOOR))

    def ceil(self) -> "SimNumber":
        return SimNumber(self._value.to_integral_value(rounding=ROUND_CEILING))

    def log10(self) -> "SimNumber":
        if self._value <= 0:
            raise ValueError("log10 requires a positive SimNumber")
        return SimNumber(self._value.log10())

    def __add__(self, other: Any) -> "SimNumber":
        return SimNumber(self._value + SimNumber.parse(other)._value)

    def __sub__(self, other: Any) -> "SimNumber":
        return SimNumber(self._value - SimNumber.parse(other)._value)

    def __mul__(self, other: Any) -> "SimNumber":
        return SimNumber(self._value * SimNumber.parse(other)._value)

    def __truediv__(self, other: Any) -> "SimNumber":
        parsed = SimNumber.parse(other)
        if parsed._value == 0:
            raise ZeroDivisionError("division by zero SimNumber")
        return SimNumber(self._value / parsed._value)

    def __pow__(self, other: Any) -> "SimNumber":
        exponent = SimNumber.parse(other)._value
        if self._value < 0:
            raise ValueError("negative SimNumber powers are not supported")
        if exponent == exponent.to_integral_value():
            return SimNumber(self._value ** int(exponent))
        if self._value == 0:
            return SimNumber.zero()
        return SimNumber((self._value.ln() * exponent).exp())

    def __neg__(self) -> "SimNumber":
        return SimNumber(-self._value)

    def __bool__(self) -> bool:
        return self._value != 0

    def __str__(self) -> str:
        return self.to_decimal_string()
