from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

from .loader import ReportData


_KEY_UNLOCK_KINDS = frozenset({"unlock_generator", "unlock_upgrade", "unlock_activity"})


def build_overview(data: ReportData) -> dict[str, Any]:
    """Derive stable, exact KPI values from report artifacts."""
    profiles = data.profiles
    invalid_content = _mapping(data.analysis.get("invalid_content_report"))
    never_purchased = _sequence(invalid_content.get("never_purchased"))
    never_unlocked = _sequence(invalid_content.get("never_unlocked"))

    return {
        "duration_seconds": _duration_seconds(data.timeline),
        "profiles": profiles,
        "final_resources": _final_resources(data.timeline, profiles),
        "purchase_count": sum(
            1 for event in data.events if str(event.get("kind", "")).startswith("buy_")
        ),
        "first_key_unlock": _first_key_unlock(data.events),
        "prestige_reset_count": sum(
            1 for event in data.events if event.get("kind") == "prestige_reset"
        ),
        "worst_payback": _worst_payback(data.payback_rows),
        "never_purchased_count": len(never_purchased),
        "never_unlocked_count": len(never_unlocked),
        "warning_category_count": _warning_category_count(data),
    }


def _duration_seconds(timeline: list[dict[str, Any]]) -> str:
    timed_rows = _rows_with_decimal_time(timeline)
    if not timed_rows:
        return "0"
    _, row = max(timed_rows, key=lambda pair: pair[0])
    return str(row.get("time_seconds", 0))


def _final_resources(
    timeline: list[dict[str, Any]], profiles: list[str]
) -> dict[str, dict[str, str]]:
    latest: dict[str, tuple[Decimal, dict[str, Any]]] = {}
    profile_set = set(profiles)
    for time_seconds, row in _rows_with_decimal_time(timeline):
        profile_id = str(row.get("profile_id", ""))
        if profile_id not in profile_set:
            continue
        current = latest.get(profile_id)
        if current is None or time_seconds >= current[0]:
            latest[profile_id] = (time_seconds, row)

    result: dict[str, dict[str, str]] = {}
    for profile_id in profiles:
        row = latest.get(profile_id, (Decimal(0), {}))[1]
        resources = _mapping(row.get("resources"))
        result[profile_id] = {str(key): str(value) for key, value in resources.items()}
    return result


def _first_key_unlock(events: list[dict[str, Any]]) -> dict[str, str] | None:
    candidates: list[tuple[Decimal, tuple[str, str, str], dict[str, Any]]] = []
    for event in events:
        kind = str(event.get("kind", ""))
        time_seconds = _decimal(event.get("time_seconds"))
        if kind not in _KEY_UNLOCK_KINDS or time_seconds is None or time_seconds <= 0:
            continue
        identity = (
            str(event.get("profile_id", "")),
            kind,
            str(event.get("item_id", "")),
        )
        candidates.append((time_seconds, identity, event))

    if not candidates:
        return None
    _, _, event = min(candidates, key=lambda candidate: (candidate[0], candidate[1]))
    return {
        "time_seconds": str(event.get("time_seconds", 0)),
        "profile_id": str(event.get("profile_id", "")),
        "kind": str(event.get("kind", "")),
        "item_id": str(event.get("item_id", "")),
    }


def _worst_payback(payback_rows: list[dict[str, str]]) -> dict[str, str] | None:
    candidates: list[tuple[Decimal, tuple[str, str, str], dict[str, str]]] = []
    for row in payback_rows:
        payback = _decimal(row.get("payback_seconds"))
        if payback is None:
            continue
        identity = (
            str(row.get("profile_id", "")),
            str(row.get("kind", "")),
            str(row.get("item_id", "")),
        )
        candidates.append((payback, identity, row))

    if not candidates:
        return None
    worst_value = max(candidate[0] for candidate in candidates)
    _, _, row = min(
        (candidate for candidate in candidates if candidate[0] == worst_value),
        key=lambda candidate: candidate[1],
    )
    return dict(row)


def _warning_category_count(data: ReportData) -> int:
    invalid_content = _mapping(data.analysis.get("invalid_content_report"))
    bottlenecks = _mapping(data.analysis.get("bottleneck_report"))
    categories = (
        bool(_sequence(invalid_content.get("never_purchased"))),
        bool(_sequence(invalid_content.get("never_unlocked"))),
        bool(_sequence(data.analysis.get("overpowered_content_report"))),
        any(
            _decimal(row.get("payback_seconds")) == Decimal("Infinity")
            for row in data.payback_rows
        ),
        any(bool(_sequence(gaps)) for gaps in bottlenecks.values()),
    )
    return sum(categories)


def _rows_with_decimal_time(
    rows: list[dict[str, Any]],
) -> list[tuple[Decimal, dict[str, Any]]]:
    result: list[tuple[Decimal, dict[str, Any]]] = []
    for row in rows:
        time_seconds = _decimal(row.get("time_seconds"))
        if time_seconds is not None:
            result.append((time_seconds, row))
    return result


def _decimal(value: Any) -> Decimal | None:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return None if result.is_nan() else result


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> Sequence[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    return ()
