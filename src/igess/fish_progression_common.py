from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation
from typing import Any

from .fish_session import FishDailySessionSchedule
from .schema import EconomyModel, Event


def profile_schedule(
    model: EconomyModel,
    profile_id: str,
) -> FishDailySessionSchedule:
    profile = model.player_profiles[profile_id]
    return FishDailySessionSchedule.from_mapping(
        model.session_patterns[profile.session_pattern]
    )


def profile_events(
    events: list[Event],
    profile_id: str,
) -> list[Event]:
    return sorted(
        (
            event
            for event in events
            if event.profile_id == profile_id
        ),
        key=lambda event: event.time_seconds,
    )


def duration_seconds(duration_hours: float) -> int:
    return int(round(duration_hours * 3600))


def percentile(values: list[int], quantile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    rank = max(1, math.ceil(quantile * len(ordered)))
    return ordered[rank - 1]


def decimal_value(value: Any) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(
            f"invalid progression numeric value: {value!r}"
        ) from exc
    if not result.is_finite():
        raise ValueError(
            f"progression numeric value must be finite: {value!r}"
        )
    return result


def optional_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return decimal_value(value)
    except ValueError:
        return None


def decimal_text(value: Any) -> str:
    decimal = (
        value
        if isinstance(value, Decimal)
        else decimal_value(value)
    )
    if decimal.is_zero():
        return "0"
    return format(decimal.normalize(), "f")
