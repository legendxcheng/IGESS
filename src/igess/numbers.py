from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, getcontext
from functools import total_ordering
from typing import Any

getcontext().prec = 80

_TEN = Decimal(10)
_LN10 = _TEN.ln()
_EXACT_MAX_ADJUSTED = 900_000
_LOG_NEGLIGIBLE_DELTA = Decimal("-70")
_INTEGRAL_TOLERANCE = Decimal("1e-70")


@total_ordering
@dataclass(frozen=True)
class SimNumber:
    """Deterministic bignum surface for economy values.

    Values always carry sign plus log10(abs(value)) so very large idle-game
    curves can keep comparing and multiplying after Decimal arithmetic would
    overflow. For normal-sized numbers, an exact Decimal cache preserves the
    small-value precision designers expect in reports.
    """

    sign: int
    log10_abs: Decimal | None
    _decimal: Decimal | None = field(default=None, repr=False, compare=False)
    backend: str = "bignum_log"

    @classmethod
    def parse(cls, value: Any) -> "SimNumber":
        if isinstance(value, SimNumber):
            return value
        if isinstance(value, Decimal):
            return cls.from_decimal(value)
        if isinstance(value, int):
            return cls.from_decimal(Decimal(value))
        if isinstance(value, float):
            return cls.from_decimal(Decimal(str(value)))
        return cls.from_decimal(Decimal(str(value)))

    @classmethod
    def zero(cls) -> "SimNumber":
        return cls(0, None, Decimal(0))

    @classmethod
    def one(cls) -> "SimNumber":
        return cls.from_decimal(Decimal(1))

    @classmethod
    def from_decimal(cls, value: Decimal) -> "SimNumber":
        if value == 0:
            return cls.zero()
        sign = -1 if value.is_signed() else 1
        exact = value if _can_keep_exact(value) else None
        return cls(sign, _decimal_log10_abs(value), exact)

    @classmethod
    def _from_log(cls, sign: int, log10_abs: Decimal | None) -> "SimNumber":
        if sign == 0 or log10_abs is None:
            return cls.zero()
        normalized_sign = 1 if sign > 0 else -1
        exact = _decimal_from_log_if_stable(normalized_sign, log10_abs)
        if exact is not None:
            return cls.from_decimal(exact)
        return cls(normalized_sign, log10_abs, None)

    @property
    def decimal(self) -> Decimal:
        if self._decimal is not None:
            return self._decimal
        return _to_decimal_approx(self)

    def is_zero(self) -> bool:
        return self.sign == 0

    def to_decimal_string(self) -> str:
        if self.sign == 0:
            return "0"
        if self._decimal is not None:
            return _format_decimal(self._decimal)
        assert self.log10_abs is not None
        mantissa, exponent = _mantissa_exponent(self.log10_abs)
        sign_text = "-" if self.sign < 0 else ""
        exponent_text = f"E+{exponent}" if exponent >= 0 else f"E{exponent}"
        return f"{sign_text}{_format_decimal(mantissa)}{exponent_text}"

    def to_float(self) -> float:
        if self.sign == 0:
            return 0.0
        assert self.log10_abs is not None
        if self.log10_abs > Decimal("308.25471555991674385"):
            return float("inf") if self.sign > 0 else float("-inf")
        if self.log10_abs < Decimal("-324"):
            return 0.0
        return float(self.decimal)

    def floor(self) -> "SimNumber":
        if self._decimal is None:
            return self
        return SimNumber.from_decimal(self._decimal.to_integral_value(rounding=ROUND_FLOOR))

    def ceil(self) -> "SimNumber":
        if self._decimal is None:
            return self
        return SimNumber.from_decimal(self._decimal.to_integral_value(rounding=ROUND_CEILING))

    def log10(self) -> "SimNumber":
        if self.sign <= 0 or self.log10_abs is None:
            raise ValueError("log10 requires a positive SimNumber")
        return SimNumber.from_decimal(self.log10_abs)

    def __add__(self, other: Any) -> "SimNumber":
        parsed = SimNumber.parse(other)
        exact = _try_exact(lambda: self.decimal + parsed.decimal, self, parsed)
        if exact is not None:
            return exact
        return _add_by_log(self, parsed)

    def __sub__(self, other: Any) -> "SimNumber":
        return self + (-SimNumber.parse(other))

    def __mul__(self, other: Any) -> "SimNumber":
        parsed = SimNumber.parse(other)
        exact = _try_exact(lambda: self.decimal * parsed.decimal, self, parsed)
        if exact is not None:
            return exact
        if self.sign == 0 or parsed.sign == 0:
            return SimNumber.zero()
        assert self.log10_abs is not None and parsed.log10_abs is not None
        return SimNumber._from_log(self.sign * parsed.sign, self.log10_abs + parsed.log10_abs)

    def __truediv__(self, other: Any) -> "SimNumber":
        parsed = SimNumber.parse(other)
        if parsed.sign == 0:
            raise ZeroDivisionError("division by zero SimNumber")
        exact = _try_exact(lambda: self.decimal / parsed.decimal, self, parsed)
        if exact is not None:
            return exact
        if self.sign == 0:
            return SimNumber.zero()
        assert self.log10_abs is not None and parsed.log10_abs is not None
        return SimNumber._from_log(self.sign * parsed.sign, self.log10_abs - parsed.log10_abs)

    def __pow__(self, other: Any) -> "SimNumber":
        exponent = SimNumber.parse(other)
        if self.sign < 0:
            raise ValueError("negative SimNumber powers are not supported")
        if exponent.sign == 0:
            return SimNumber.one()
        exact = _try_exact(lambda: _exact_pow(self.decimal, exponent.decimal), self, exponent)
        if exact is not None:
            return exact
        if self.sign == 0:
            return SimNumber.zero()
        assert self.log10_abs is not None
        return SimNumber._from_log(1, self.log10_abs * exponent.decimal)

    def __neg__(self) -> "SimNumber":
        if self.sign == 0:
            return self
        decimal = -self._decimal if self._decimal is not None else None
        return SimNumber(-self.sign, self.log10_abs, decimal)

    def __bool__(self) -> bool:
        return self.sign != 0

    def __eq__(self, other: object) -> bool:
        try:
            parsed = SimNumber.parse(other)
        except Exception:
            return False
        if self._decimal is not None and parsed._decimal is not None:
            return self._decimal == parsed._decimal
        if self.sign != parsed.sign:
            return False
        if self.sign == 0:
            return True
        assert self.log10_abs is not None and parsed.log10_abs is not None
        if abs(self.log10_abs - parsed.log10_abs) <= _INTEGRAL_TOLERANCE:
            return True
        return self.sign == parsed.sign and self.log10_abs == parsed.log10_abs

    def __hash__(self) -> int:
        if self._decimal is not None:
            return hash(self._decimal.normalize())
        if self.sign == 0:
            return hash(Decimal(0))
        return hash((self.sign, self.to_decimal_string()))

    def __lt__(self, other: Any) -> bool:
        parsed = SimNumber.parse(other)
        if self._decimal is not None and parsed._decimal is not None:
            return self._decimal < parsed._decimal
        if self.sign != parsed.sign:
            return self.sign < parsed.sign
        if self.sign == 0:
            return False
        assert self.log10_abs is not None and parsed.log10_abs is not None
        if abs(self.log10_abs - parsed.log10_abs) <= _INTEGRAL_TOLERANCE:
            return False
        if self.sign > 0:
            return self.log10_abs < parsed.log10_abs
        return self.log10_abs > parsed.log10_abs

    def __str__(self) -> str:
        return self.to_decimal_string()


def _can_keep_exact(value: Decimal) -> bool:
    if value == 0:
        return True
    adjusted = value.copy_abs().adjusted()
    return -_EXACT_MAX_ADJUSTED <= adjusted <= _EXACT_MAX_ADJUSTED


def _decimal_log10_abs(value: Decimal) -> Decimal:
    absolute = value.copy_abs()
    digits = "".join(str(digit) for digit in absolute.as_tuple().digits)
    coefficient = Decimal(int(digits))
    return coefficient.log10() + Decimal(absolute.as_tuple().exponent)


def _format_decimal(value: Decimal) -> str:
    if value == 0:
        return "0"
    normalized = value.normalize()
    adjusted = normalized.adjusted()
    if adjusted >= 30 or adjusted <= -8:
        return str(normalized)
    text = format(normalized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _floor_int(value: Decimal) -> int:
    return int(value.to_integral_value(rounding=ROUND_FLOOR))


def _pow10(exponent: Decimal) -> Decimal:
    if exponent == 0:
        return Decimal(1)
    if exponent == exponent.to_integral_value():
        return _TEN ** int(exponent)
    return (_LN10 * exponent).exp()


def _mantissa_exponent(log10_abs: Decimal) -> tuple[Decimal, int]:
    exponent = _floor_int(log10_abs)
    mantissa = _pow10(log10_abs - Decimal(exponent))
    nearest = mantissa.to_integral_value()
    if abs(mantissa - nearest) <= _INTEGRAL_TOLERANCE:
        mantissa = nearest
    if mantissa >= _TEN:
        mantissa = mantissa / _TEN
        exponent += 1
    return mantissa, exponent


def _decimal_from_log_if_stable(sign: int, log10_abs: Decimal) -> Decimal | None:
    mantissa, exponent = _mantissa_exponent(log10_abs)
    if exponent < -_EXACT_MAX_ADJUSTED or exponent > _EXACT_MAX_ADJUSTED:
        return None
    text = _format_decimal(mantissa)
    exponent_text = f"E+{exponent}" if exponent >= 0 else f"E{exponent}"
    value = Decimal(f"{text}{exponent_text}")
    return value if sign > 0 else -value


def _to_decimal_from_log(sign: int, log10_abs: Decimal) -> Decimal:
    mantissa, exponent = _mantissa_exponent(log10_abs)
    text = _format_decimal(mantissa)
    exponent_text = f"E+{exponent}" if exponent >= 0 else f"E{exponent}"
    value = Decimal(f"{text}{exponent_text}")
    return value if sign > 0 else -value


def _try_exact(fn, left: SimNumber, right: SimNumber) -> SimNumber | None:
    if left._decimal is None or right._decimal is None:
        return None
    try:
        value = fn()
    except Exception:
        return None
    if not _can_keep_exact(value):
        return None
    return SimNumber.from_decimal(value)


def _exact_pow(base: Decimal, exponent: Decimal) -> Decimal:
    if base < 0:
        raise ValueError("negative SimNumber powers are not supported")
    if exponent == exponent.to_integral_value():
        return base ** int(exponent)
    if base == 0:
        return Decimal(0)
    return (base.ln() * exponent).exp()


def _add_by_log(left: SimNumber, right: SimNumber) -> SimNumber:
    if left.sign == 0:
        return right
    if right.sign == 0:
        return left
    assert left.log10_abs is not None and right.log10_abs is not None
    if left.sign == right.sign:
        return SimNumber._from_log(
            left.sign,
            _log_add_same_sign(left.log10_abs, right.log10_abs),
        )
    if left.log10_abs == right.log10_abs:
        return SimNumber.zero()
    if left.log10_abs > right.log10_abs:
        sign = left.sign
        bigger = left.log10_abs
        smaller = right.log10_abs
    else:
        sign = right.sign
        bigger = right.log10_abs
        smaller = left.log10_abs
    return SimNumber._from_log(sign, _log_sub_magnitudes(bigger, smaller))


def _log_add_same_sign(left_log: Decimal, right_log: Decimal) -> Decimal:
    bigger = max(left_log, right_log)
    smaller = min(left_log, right_log)
    delta = smaller - bigger
    if delta < _LOG_NEGLIGIBLE_DELTA:
        return bigger
    return bigger + (Decimal(1) + _pow10(delta)).log10()


def _log_sub_magnitudes(bigger_log: Decimal, smaller_log: Decimal) -> Decimal:
    delta = smaller_log - bigger_log
    if delta < _LOG_NEGLIGIBLE_DELTA:
        return bigger_log
    term = Decimal(1) - _pow10(delta)
    if term <= 0:
        return Decimal(0)
    return bigger_log + term.log10()


def _to_decimal_approx(self: SimNumber) -> Decimal:
    if self.sign == 0:
        return Decimal(0)
    assert self.log10_abs is not None
    return _to_decimal_from_log(self.sign, self.log10_abs)
