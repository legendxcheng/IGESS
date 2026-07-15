"""Exact decimal formatting for human-facing reports."""

from __future__ import annotations

from decimal import (
    MAX_EMAX,
    MIN_EMIN,
    ROUND_HALF_EVEN,
    Decimal,
    InvalidOperation,
    localcontext,
)


_FIXED_MIN = Decimal("1e-4")
_FIXED_MAX = Decimal("1e6")


def format_human_number(value: object) -> str | None:
    """Format a finite number with six significant digits without using floats."""

    if value is None:
        return None

    source = str(value)
    try:
        number = Decimal(source)
    except InvalidOperation:
        return source

    if not number.is_finite():
        return source
    if number.is_zero():
        return "0"

    digits = len(number.as_tuple().digits)
    use_fixed = _FIXED_MIN <= number.copy_abs() < _FIXED_MAX

    try:
        with localcontext() as context:
            context.prec = max(80, digits + 10)
            context.Emax = MAX_EMAX
            context.Emin = MIN_EMIN
            adjusted = number.copy_abs().adjusted()
            quantum = Decimal(1).scaleb(adjusted - 5)
            rounded = number.quantize(quantum, rounding=ROUND_HALF_EVEN)
    except InvalidOperation:
        return source

    if use_fixed:
        text = format(rounded, "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return text

    mantissa, exponent = format(rounded, ".5E").split("E")
    mantissa = mantissa.rstrip("0").rstrip(".")
    return f"{mantissa}e{int(exponent)}"


def human_number(value: object) -> dict[str, str | None]:
    """Return exact and display representations for a report value."""

    source = None if value is None else str(value)
    return {
        "exact_value": source,
        "display_value": format_human_number(value),
    }
