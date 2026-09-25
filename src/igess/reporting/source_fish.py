"""Read-only projections of source observations and accepted command receipts.

No prices, rewards, probability formulas or game-state transitions are evaluated here.
"""

from __future__ import annotations

import json
from collections import Counter
from decimal import Decimal, InvalidOperation, localcontext
from itertools import pairwise
from typing import Any

from .loader import ReportData, ReportLoadError

_MILESTONES = {
    "purchase_torpedo": ("torpedo", "owned_torpedo_count"),
    "synthesize_barbell": ("barbell", "owned_barbell_count"),
    "upgrade_hall": ("fish_hall", "fish_hall_level"),
    "rebirth_strength": ("strength_rebirth", "strength_rebirth_count"),
    "rebirth_trash_man": ("trash_man_rebirth", "trash_man_rebirth_count"),
    "start_breakthrough": ("breakthrough_funding", "target_realm_id"),
}


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        if isinstance(value, dict):
            # Construct the DTO exactly; Decimal.scaleb would round to context precision.
            coefficient = Decimal(str(value["coeff"]))
            parts = coefficient.as_tuple()
            if not isinstance(parts.exponent, int):
                return None
            result = Decimal(
                (
                    int(value["sign"] < 0),
                    parts.digits,
                    parts.exponent + int(value["exp"]),
                )
            )
            return Decimal(0) if value["sign"] == 0 else result
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (KeyError, TypeError, ValueError, InvalidOperation):
        return None


def _text(value: Any) -> str | None:
    number = _decimal(value)
    return str(number) if number is not None else None


def _sum(values: list[Any]) -> str | None:
    numbers = [_decimal(value) for value in values]
    if any(value is None for value in numbers):
        return None
    finite = [value for value in numbers if value is not None]
    with localcontext() as context:
        context.prec = max(
            80,
            max((value.adjusted() for value in finite), default=0)
            - min((int(value.as_tuple().exponent) for value in finite), default=0)
            + len(str(len(finite)))
            + 2,
        )
        return str(sum(finite, Decimal(0)))


def _receipts(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for event in sorted(events, key=lambda row: row["time_seconds"]):
        value = event.get("details", {}).get("receipt")
        try:
            receipt = json.loads(value) if isinstance(value, str) else {}
        except json.JSONDecodeError as error:
            raise ReportLoadError(
                "Invalid source command receipt in events.json"
            ) from error
        if not isinstance(receipt, dict):
            raise ReportLoadError("Source command receipt must be an object")
        rows.append({**event, "receipt": receipt})
    return rows


def _sessions(
    events: list[dict[str, Any]], start: int, end: int
) -> list[dict[str, Any]]:
    # Fresh source sessions start online. A resumed run needs its own online evidence.
    opened = 0 if start == 0 else None
    sessions = []
    for event in events:
        time = int(event["time_seconds"])
        if event["kind"] == "go_online" and opened is None:
            opened = time
        elif event["kind"] == "go_offline" and opened is not None:
            sessions.append({"start": opened, "end": time, "complete": True})
            opened = None
    if opened is not None:
        sessions.append({"start": opened, "end": end, "complete": False})
    return sessions


def _active_at(time: int, sessions: list[dict[str, Any]]) -> int:
    return sum(max(0, min(time, row["end"]) - row["start"]) for row in sessions)


def _core(
    samples: list[dict[str, Any]], sessions: list[dict[str, Any]]
) -> dict[str, Any]:
    rows = []
    peaks: dict[str, Decimal] = {}
    for sample in samples:
        wall = int(sample["time_seconds"])
        row = {
            "wall_time_seconds": wall,
            "active_time_seconds": _active_at(wall, sessions),
            "sample_kind": "source_observation",
        }
        for field in ("strength", "fish_luck", "trash_luck"):
            value = _decimal(sample.get(field))
            if value is not None:
                peaks[field] = max(value, peaks.get(field, value))
            row[field + "_current"] = str(value) if value is not None else None
            row[field + "_peak"] = str(peaks[field]) if field in peaks else None
        for field in ("strength_rebirth_count", "trash_man_rebirth_count"):
            row[field] = sample.get(field)
        rows.append(row)
    summary = {
        "active_duration_seconds": sum(row["end"] - row["start"] for row in sessions),
        "observation_count": len(rows),
        "longest_fish_luck_stagnation_seconds": None,
        "longest_trash_luck_stagnation_seconds": None,
    }
    for field in ("strength", "fish_luck", "trash_luck"):
        summary[field + "_final"] = rows[-1][field + "_current"] if rows else None
        summary[field + "_peak"] = str(peaks[field]) if field in peaks else None
    return {"rows": rows, "summary": summary}


def _milestone(
    event: dict[str, Any], active: int, previous: int
) -> dict[str, Any] | None:
    kind, receipt = event["kind"], event["receipt"]
    if kind not in _MILESTONES:
        return None
    category, metric = _MILESTONES[kind]
    before = after = None
    item = event.get("item_id", "")
    if kind == "upgrade_hall":
        before, after = (
            receipt.get("previousUpgradeLevel"),
            receipt.get("currentUpgradeLevel"),
        )
        item = f"fish_hall:{after}"
    elif kind in ("rebirth_strength", "rebirth_trash_man"):
        before, after = (
            receipt.get("oldCompletedCount"),
            receipt.get("newCompletedCount"),
        )
    elif kind == "purchase_torpedo":
        owned = receipt.get("ownedIds")
        if isinstance(owned, list):
            before, after = len(owned) - 1, len(owned)
        item = f"torpedo:{receipt.get('torpedoId', '')}"
    elif kind == "synthesize_barbell":
        before, after = receipt.get("previousCount"), receipt.get("currentCount")
        item = f"barbell:{receipt.get('barbellId', '')}"
    else:
        before, after = receipt.get("fromRealmId"), receipt.get("toRealmId")
        item = f"trash_man_realm:{after}"
        if receipt.get("instant") is True:
            category, metric = "trash_man_realm", "trash_man_realm_id"
    left, right = _decimal(before), _decimal(after)
    return {
        "wall_time_seconds": event["time_seconds"],
        "active_time_seconds": active,
        "stage_id": f"online_day_{int(event['time_seconds']) // 86400 + 1}",
        "source_event_kind": kind,
        "progression_category": category,
        "item_id": item,
        "metric_id": metric,
        "metric_before": _text(before),
        "metric_after": _text(after),
        "metric_delta": str(right - left)
        if left is not None and right is not None
        else None,
        "relative_delta": None,
        "gap_from_previous_progression_seconds": active - previous,
    }


def _growth(
    events: list[dict[str, Any]], sessions: list[dict[str, Any]]
) -> dict[str, Any]:
    rows = []
    for event in events:
        row = _milestone(
            event,
            _active_at(int(event["time_seconds"]), sessions),
            rows[-1]["active_time_seconds"] if rows else 0,
        )
        if row:
            rows.append(row)
    active = sum(session["end"] - session["start"] for session in sessions)
    times = [row["active_time_seconds"] for row in rows]
    complete = [session for session in sessions if session["complete"]]
    empty = sum(
        not any(
            session["start"] <= row["wall_time_seconds"] <= session["end"]
            for row in rows
        )
        for session in complete
    )
    maximum = max((b - a for a, b in pairwise(times)), default=0)
    summary = {
        "total_progression_count": len(rows),
        "active_duration_seconds": active,
        "events_per_active_hour": str(Decimal(len(rows) * 3600) / active)
        if active
        else None,
        "first_progression_wait_seconds": times[0] if times else active,
        "max_interval_seconds": maximum,
        "system_progression_max_interval_seconds": maximum,
        "tail_gap_seconds": active - times[-1] if times else active,
        "complete_online_sessions": len(complete),
        "complete_online_sessions_without_progression": empty,
        "complete_online_sessions_without_system_progression": empty,
    }
    return {"rows": rows, "summary": summary, "sessions": sessions}


def _investment(
    events: list[dict[str, Any]], sessions: list[dict[str, Any]]
) -> dict[str, Any]:
    upgrades = [event["receipt"] for event in events if event["kind"] == "upgrade_fish"]
    sales = [event["receipt"] for event in events if event["kind"] == "sell_fish"]
    return {
        "upgrade_count": len(upgrades),
        "fish_sold_count": len(sales),
        "coin_spent": _sum([row.get("moneySpent") for row in upgrades]),
        "sale_material": _sum([row.get("materialAdded") for row in sales]),
        "trash_material": None,
        "hall_income_gain": None,
        "effective_upgrade_percent": None,
        "barbell_purchases": [
            {
                "barbell_id": row["receipt"].get("barbellId"),
                "wall_time": row["time_seconds"],
                "active_time": _active_at(int(row["time_seconds"]), sessions),
                "price": _text(row["receipt"].get("moneySpent")),
            }
            for row in events
            if row["kind"] == "synthesize_barbell"
        ],
    }


def build_source_projection(data: ReportData) -> dict[str, Any]:
    sampling = data.manifest.get("source_runtime", {})
    sampling_note = "旧长场景主要按天采样。"
    if sampling.get("sampling_time_basis") == "online":
        interval = sampling.get("record_interval_seconds")
        sampling_note = f"每累计在线 {interval} 秒采样，另保存上下线、离线领取及重生前后状态。"
    core, growth, investment, liquidity = {}, {}, {}, {}
    counts: Counter[str] = Counter()
    actions = {}
    for profile in data.profiles:
        events = _receipts(
            [row for row in data.events if row.get("profile_id") == profile]
        )
        timeline = [row for row in data.timeline if row.get("profile_id") == profile]
        start = min((int(row["time_seconds"]) for row in timeline), default=0)
        end = max((int(row["time_seconds"]) for row in timeline), default=0)
        sessions = _sessions(events, start, end)
        samples = sorted(
            data.source_progression.get("profiles", {}).get(profile, []),
            key=lambda row: row["time_seconds"],
        )
        if samples:
            core[profile] = _core(samples, sessions)
            liquidity[profile] = [
                {
                    **sample,
                    "active_time_seconds": _active_at(sample["time_seconds"], sessions),
                }
                for sample in samples
            ]
        growth[profile] = _growth(events, sessions)
        investment[profile] = _investment(events, sessions)
        accepted = Counter(
            row["kind"] for row in events if row["kind"] != "source_rejected"
        )
        rejected = Counter(
            row.get("details", {}).get("code", "unknown")
            for row in events
            if row["kind"] == "source_rejected"
        )
        counts.update(accepted)
        counts["source_rejected"] += sum(rejected.values())
        actions[profile] = {
            "accepted_commands": dict(accepted),
            "rejected_commands": dict(rejected),
        }
    return {
        "core": {"profiles": core},
        "persistent": {"profiles": growth},
        "investment": investment,
        "liquidity": liquidity,
        "actions": actions,
        "purchase_count": counts["purchase_torpedo"] + counts["synthesize_barbell"],
        "rebirth_count": counts["rebirth_strength"] + counts["rebirth_trash_man"],
        "throw_count": counts["complete_throw"],
        "rejection_count": counts["source_rejected"],
        "milestone_count": sum(len(profile["rows"]) for profile in growth.values()),
        "notes": {
            "core": "力量与双 Luck 来自已保存的源状态采样；峰值仅为采样点峰值。" + sampling_note + "这些状态不等于完整在线毛收入、真实峰值或精确最长停滞，未记录的指标不填零。",
            "persistent": "按实际上线/下线记录累计在线时间，离线等待不计入间隔。图中统计鱼雷、杠铃、鱼厅、两类重生及突破资助操作；“突破资助”仅表示支付材料，不代表训练已完成。单鱼升级不计入。",
            "investment": "支出与卖鱼收入直接汇总成功命令回执。原记录没有单次升级带来的产出变化、完整加工材料收入，因此对应指标显示为未记录；选鱼采用本次同源策略。",
            "liquidity": "钱包可花费与鱼厅待领取分开展示；累计已领取来自领取回执。累计已领取＋当前待领为本次可核算金额，不等于完整在线毛产出。",
        },
    }


def display_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the useful overview small; all receipts remain in events.json."""
    return [
        {**event, "details": {"code": event.get("details", {}).get("code")}}
        for event in events
        if event["kind"] in _MILESTONES or event["kind"] == "source_rejected"
    ]
