"""Read-only projections of source observations and accepted command receipts.

No prices, rewards, probability formulas or game-state transitions are evaluated here.
"""

from __future__ import annotations

import json
from bisect import bisect_right
from collections import Counter
from decimal import Decimal, InvalidOperation, localcontext
from itertools import pairwise
from typing import Any

from .loader import ReportData, ReportLoadError
from .source_collection import CollectionGrowth, ordered_observations
from ..fish_source_reports import project_source_behavior
from ..fish_source_numbers import source_decimal

_MILESTONES = {
    "treasure_beast_unlocked": ("treasure_beast", "treasure_beast_unlocked"),
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
            return source_decimal(value)
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
    events: list[dict[str, Any]], start: int, end: int, initial_online: bool | None = None,
) -> list[dict[str, Any]]:
    opened = start if (initial_online if initial_online is not None else start == 0) else None
    began_here = start == 0
    sessions = []
    for event in events:
        time = int(event["time_seconds"])
        if event["kind"] == "go_online" and opened is None:
            opened = time
            began_here = True
        elif event["kind"] == "go_offline" and opened is not None:
            sessions.append({"start": opened, "end": time, "complete": began_here})
            opened = None
    if opened is not None:
        sessions.append({"start": opened, "end": end, "complete": False})
    return sessions


def _active_at(time: int, sessions: list[dict[str, Any]], initial: int = 0) -> int:
    return initial + sum(max(0, min(time, row["end"]) - row["start"]) for row in sessions)


def growth_by_session(rows: list[dict[str, Any]], sessions: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Assign shared boundary seconds to the later session, exactly once."""
    groups: list[list[dict[str, Any]]] = [[] for _ in sessions]
    starts = [session["start"] for session in sessions]
    for row in rows:
        index = bisect_right(starts, row["wall_time_seconds"]) - 1
        if index >= 0 and row["wall_time_seconds"] <= sessions[index]["end"]:
            groups[index].append(row)
    return groups


def _core(
    samples: list[dict[str, Any]], sessions: list[dict[str, Any]], initial: int = 0,
) -> dict[str, Any]:
    rows = []
    peaks: dict[str, Decimal] = {}
    for sample in samples:
        wall = int(sample["time_seconds"])
        row = {
            "wall_time_seconds": wall,
            "active_time_seconds": _active_at(wall, sessions, initial),
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
    event: dict[str, Any], active: int, previous: int,
    collection: CollectionGrowth,
) -> dict[str, Any] | None:
    kind, receipt = event["kind"], event["receipt"]
    if kind == "fish_pool_entered":
        return {
            "event_identity": f"fish_pool:{receipt['pool_id']}",
            "item_id": f"fish_pool:{receipt['pool_id']}",
            "pool_id": receipt["pool_id"], "display_name": receipt.get("display_name", ""),
            "strength": receipt["strength"], "previous_upper_bound": receipt["previous_upper_bound"],
            "wall_time_seconds": event["time_seconds"], "active_time_seconds": active,
            "stage_id": f"online_day_{int(event['time_seconds']) // 86400 + 1}",
            "source_event_kind": kind, "progression_category": "fish_pool",
            "metric_id": "fish_pool_entered", "metric_before": "0", "metric_after": "1",
            "metric_delta": "1", "relative_delta": None,
            "gap_from_previous_progression_seconds": active - previous,
        }
    if kind in {"gun_milestone", "codex_fish_unlocked"}:
        fact = collection.project(event)
        if fact is None:
            return None
        return {
            **fact,
            "wall_time_seconds": event["time_seconds"], "active_time_seconds": active,
            "stage_id": f"online_day_{int(event['time_seconds']) // 86400 + 1}",
            "source_event_kind": kind,
            "metric_before": "0", "metric_after": "1", "metric_delta": "1",
            "relative_delta": None, "gap_from_previous_progression_seconds": active - previous,
        }
    if kind not in _MILESTONES:
        return None
    category, metric = _MILESTONES[kind]
    before = after = None
    item = event.get("item_id", "")
    if kind == "treasure_beast_unlocked":
        before, after = int(receipt["unlockedBefore"]), int(receipt["unlockedAfter"])
        active = int(receipt["activeTimeSeconds"])
        item = f"treasure_beast:第{receipt['areaIndex']}水域"
    elif kind == "upgrade_hall":
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
        item = f"breakthrough_funding:{after}"
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
        **({"area_index": receipt.get("areaIndex"), "distance_cm": receipt.get("distanceCm")}
           if kind == "treasure_beast_unlocked" else {}),
        "gap_from_previous_progression_seconds": active - previous,
    }


def _growth(
    events: list[dict[str, Any]], sessions: list[dict[str, Any]], initial: int = 0,
    *, scope: dict[str, Any], start: int,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    collection = CollectionGrowth(scope, full_history=start == 0 and initial == 0,
                                  has_collection_records=any(e["kind"] == "codex_fish_unlocked" for e in events))
    pool_scope = scope.get("pool_growth") or {}
    seen_pools = set(pool_scope.get("initial_seen_pool_ids", []))
    for event in ordered_observations(events):
        if event["kind"] == "fish_pool_entered":
            pool_id = event["receipt"]["pool_id"]
            if pool_id in seen_pools:
                continue
            seen_pools.add(pool_id)
        row = _milestone(
            event,
            _active_at(int(event["time_seconds"]), sessions, initial),
            rows[-1]["active_time_seconds"] if rows else initial,
            collection,
        )
        if row:
            rows.append(row)
    active = sum(session["end"] - session["start"] for session in sessions)
    times = [row["active_time_seconds"] for row in rows]
    complete = [session for session in sessions if session["complete"]]
    empty = sum(not group for session, group in zip(sessions, growth_by_session(rows, sessions))
                if session["complete"])
    maximum = max((b - a for a, b in pairwise(times)), default=0)
    summary = {
        "total_progression_count": len(rows),
        "active_duration_seconds": active,
        "events_per_active_hour": str(Decimal(len(rows) * 3600) / active)
        if active
        else None,
        "first_progression_wait_seconds": times[0] - initial if times else active,
        "max_interval_seconds": maximum,
        "system_progression_max_interval_seconds": maximum,
        "tail_gap_seconds": initial + active - times[-1] if times else active,
        "complete_online_sessions": len(complete),
        "complete_online_sessions_without_progression": empty,
        "complete_online_sessions_without_system_progression": empty,
    }
    return {"rows": rows, "summary": summary, "sessions": sessions,
            "pool_coverage": {"recorded": pool_scope.get("version") == 1,
                              "note": ("新鱼池按力量首次超过上一池上限计点；初始已达池和重生后的重复进入不计。时间为源观察时点。"
                                       if pool_scope.get("version") == 1 else
                                       "本次运行未记录新鱼池成长，需重新模拟；不从力量采样补推首次时点。")},
            "collection_coverage": collection.coverage}


def _investment(
    events: list[dict[str, Any]], sessions: list[dict[str, Any]], initial: int = 0,
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
                "active_time": _active_at(int(row["time_seconds"]), sessions, initial),
                "price": _text(row["receipt"].get("moneySpent")),
            }
            for row in events
            if row["kind"] == "synthesize_barbell"
        ],
    }


def _economy(
    samples: list[dict[str, Any]], events: list[dict[str, Any]],
    sessions: list[dict[str, Any]], initial: int = 0,
) -> dict[str, Any]:
    cumulative, remaining = [], []
    for sample in samples:
        common = {
            "active_time_seconds": _active_at(int(sample["time_seconds"]), sessions, initial),
            "wall_time_seconds": sample["time_seconds"],
        }
        remaining.append({
            **common, "money_remaining": _text(sample.get("spendable_money")),
            "resource_remaining": _text(sample.get("material")),
        })
        money = _text(sample.get("online_money_acquired_cumulative"))
        material = _text(sample.get("online_resource_acquired_cumulative"))
        sale = _text(sample.get("online_fish_sale_material_cumulative"))
        codex_money = _text(sample.get("online_codex_money_cumulative", "0"))
        codex_material = _text(sample.get("online_codex_material_cumulative", "0"))
        if money is not None and material is not None and sale is not None:
            cumulative.append({
                **common, "money_acquired_cumulative": money,
                "resource_acquired_cumulative": material,
                "fish_sale_material_cumulative": sale,
                "codex_money_cumulative": codex_money,
                "codex_material_cumulative": codex_material,
                "hall_money_cumulative": _sum([money, _decimal(codex_money).copy_negate()]),
                "trash_material_cumulative": _sum([material, _decimal(sale).copy_negate(), _decimal(codex_material).copy_negate()]),
            })
    for event in events:
        receipt = event["receipt"]
        if "moneyBalance" in receipt or "materialBalance" in receipt:
            remaining.append({
                "wall_time_seconds": event["time_seconds"],
                "active_time_seconds": _active_at(int(event["time_seconds"]), sessions, initial),
                "money_remaining": _text(receipt.get("moneyBalance")),
                "resource_remaining": _text(receipt.get("materialBalance")),
            })
    # Rebirth and offline boundaries may have several observations at the same active time.
    by_active_time = {row["active_time_seconds"]: row for row in cumulative}
    rates = []
    for before, after in pairwise(by_active_time.values()):
        elapsed = after["active_time_seconds"] - before["active_time_seconds"]
        if elapsed <= 0:
            continue
        row = {"active_time_seconds": after["active_time_seconds"], "sample_window_seconds": elapsed}
        for output, field in (
            ("money_per_second", "money_acquired_cumulative"),
            ("resource_per_second", "resource_acquired_cumulative"),
            ("fish_sale_material_per_second", "fish_sale_material_cumulative"),
            ("trash_material_per_second", "trash_material_cumulative"),
        ):
            delta = _decimal(_sum([after[field], _decimal(before[field]).copy_negate()]))
            with localcontext() as context:
                context.prec = max(80, len(delta.as_tuple().digits) + 40)
                row[output] = str(delta / elapsed)
        rates.append(row)
    return {"rate_rows": rates, "cumulative_rows": cumulative,
            "remaining_rows": sorted(remaining, key=lambda row: row["wall_time_seconds"])}


def build_source_projection(data: ReportData) -> dict[str, Any]:
    sampling = data.manifest.get("source_runtime", {})
    sampling_note = "旧长场景主要按天采样。"
    if sampling.get("sampling_time_basis") == "online":
        interval = sampling.get("record_interval_seconds")
        sampling_note = f"每累计在线 {interval} 秒采样，另保存上下线、离线领取及重生前后状态。"
    core, growth, investment, liquidity, balance = {}, {}, {}, {}, {}
    counts: Counter[str] = Counter()
    actions = {}
    for profile in data.profiles:
        events = _receipts(
            [row for row in data.events if row.get("profile_id") == profile]
        )
        timeline = [row for row in data.timeline if row.get("profile_id") == profile]
        start = min((int(row["time_seconds"]) for row in timeline), default=0)
        end = max((int(row["time_seconds"]) for row in timeline), default=0)
        scope = data.manifest.get("source_profiles", {}).get(profile, {})
        initial = scope.get("initial_active_time_seconds", 0)
        sessions = _sessions(events, start, end, scope.get("initial_online"))
        elapsed = initial
        for session in sessions:
            session["active_start"] = elapsed
            elapsed += session["end"] - session["start"]
        samples = sorted(
            data.source_progression.get("profiles", {}).get(profile, []),
            key=lambda row: row["time_seconds"],
        )
        if samples:
            balance[profile] = _economy(samples, events, sessions, initial)
            core[profile] = _core(samples, sessions, initial)
            liquidity[profile] = [
                {
                    **sample,
                    "active_time_seconds": _active_at(sample["time_seconds"], sessions, initial),
                }
                for sample in samples
            ]
        growth[profile] = _growth(events, sessions, initial, scope=scope, start=start)
        investment[profile] = _investment(events, sessions, initial)
        actions[profile] = project_source_behavior(events, scope)
        counts.update(actions[profile]["accepted_commands"])
        counts["source_rejected"] += sum(actions[profile]["rejected_commands"].values())
    return {
        "execution_window": data.manifest.get("execution_window"),
        "core": {"profiles": core},
        "persistent": {"profiles": growth},
        "investment": investment,
        "liquidity": liquidity,
        "balance": balance,
        "rate_sample_interval_active_seconds": sampling.get("record_interval_seconds") if sampling.get("sampling_time_basis") == "online" else None,
        "actions": actions,
        "purchase_count": counts["purchase_torpedo"] + counts["synthesize_barbell"],
        "rebirth_count": counts["rebirth_strength"] + counts["rebirth_trash_man"],
        "throw_count": counts["complete_throw"],
        "rejection_count": counts["source_rejected"],
        "milestone_count": sum(len(profile["rows"]) for profile in growth.values()),
        "notes": {
            "economy": "资源即材料，金币即金钱。每秒速率按相邻在线采样点的实际在线秒数平均，累计获取包含在线生产、卖鱼与一次性图鉴奖励；图鉴奖励单列，不代表稳定生产能力，排除离线奖励，不扣消费。领取鱼厅收入只转移金额，不重复计入产出。当前剩余为可花费的钱包余额，包含离线入账；待领金币单独展示。旧记录缺少在线累计产出时不补算，产出图显示未记录。",
            "core": "力量与双 Luck 来自已保存的源状态采样；峰值仅为采样点峰值。" + sampling_note + "这些状态不等于完整在线毛收入、真实峰值或精确最长停滞，未记录的指标不填零。",
            "persistent": "按实际上线/下线记录累计在线时间，离线等待不计入间隔。统计原有系统成长、正常图鉴完成、新枪永久获得、新鱼种和新变异组合。首次变异鱼可带两个标签，总次数仅计一次收集事件；分类标签数可重叠。首次依据历史解锁，卖出后再获得不重计，鱼蛋孵化后才计入。时间为源观察时点，同批观察不推断先后。每次成功支付突破材料记一次“突破资助”，包含立即完成的突破，不另计突破完成。单鱼升级不计入。",
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
