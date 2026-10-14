"""Exact conversion at the source BigNumber DTO boundary."""

from collections.abc import Mapping
from decimal import Decimal
from typing import Any


def source_decimal(dto: Mapping[str, Any]) -> Decimal:
    if dto["sign"] == 0:
        return Decimal(0)
    parts = Decimal(str(dto["coeff"])).as_tuple()
    # Tuple construction does not round to the ambient Decimal precision.
    return Decimal((int(dto["sign"] < 0), parts.digits, parts.exponent + int(dto["exp"])))
