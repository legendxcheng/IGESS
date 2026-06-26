from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .reporting.loader import load_report_data


def extract_metrics(run_dir: str | Path) -> dict[str, Any]:
    data = load_report_data(run_dir)
    final_resources: dict[str, dict[str, str]] = {}
    final_rows = {}
    for row in data.timeline:
        profile = str(row["profile_id"])
        if profile not in final_rows or int(row["time_seconds"]) > int(final_rows[profile]["time_seconds"]):
            final_rows[profile] = row
    for profile, row in sorted(final_rows.items()):
        final_resources[profile] = dict(row.get("resources", {}))

    unlock_times: dict[str, dict[str, int]] = {}
    purchase_counts: dict[str, dict[str, int]] = {}
    prestige_counts: dict[str, int] = {}
    for event in data.events:
        profile = str(event["profile_id"])
        kind = str(event["kind"])
        item_id = str(event["item_id"])
        if kind.startswith("unlock_"):
            item_key = f"{kind.removeprefix('unlock_')}:{item_id}"
            current = unlock_times.setdefault(profile, {}).get(item_key)
            time_seconds = int(event["time_seconds"])
            if current is None or time_seconds < current:
                unlock_times[profile][item_key] = time_seconds
        if kind.startswith("buy_"):
            item_key = f"{kind.removeprefix('buy_')}:{item_id}"
            counts = purchase_counts.setdefault(profile, {})
            counts[item_key] = counts.get(item_key, 0) + 1
        if kind == "prestige_reset":
            prestige_counts[profile] = prestige_counts.get(profile, 0) + 1

    payback_seconds: dict[str, dict[str, str]] = {}
    for row in data.payback_rows:
        profile = str(row.get("profile_id") or "")
        item_key = f"{row.get('kind')}:{row.get('item_id')}"
        payback_seconds.setdefault(profile, {})[item_key] = str(row.get("payback_seconds") or "")

    return {
        "schema_version": 1,
        "scenario_id": data.scenario_id,
        "profiles": data.profiles,
        "final_resources": final_resources,
        "unlock_times": {profile: dict(sorted(values.items())) for profile, values in sorted(unlock_times.items())},
        "purchase_counts": {
            profile: dict(sorted(values.items())) for profile, values in sorted(purchase_counts.items())
        },
        "prestige_counts": dict(sorted(prestige_counts.items())),
        "payback_seconds": {
            profile: dict(sorted(values.items())) for profile, values in sorted(payback_seconds.items())
        },
    }


def numeric_delta(candidate: str | int | float, base: str | int | float) -> str:
    left = _decimal(candidate)
    right = _decimal(base)
    if left is None or right is None:
        return "NaN"
    return _format_decimal(left - right)


def _decimal(value: str | int | float) -> Decimal | None:
    try:
        text = str(value)
        if text == "Infinity":
            return None
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def _format_decimal(value: Decimal) -> str:
    if value == value.to_integral_value():
        return str(value.quantize(Decimal("1")))
    return format(value.normalize(), "f")
