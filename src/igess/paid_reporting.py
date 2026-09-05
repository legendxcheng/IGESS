"""Evidence-based paid/free comparisons from completed run artifacts."""

from __future__ import annotations

import csv
from decimal import Decimal, localcontext
import html
import json
import math
import os
from pathlib import Path
import shutil

from .fish_session import FishDailySessionSchedule
from .human_numbers import format_human_number
from .reporting.loader import load_report_data


def summarize_paid_run(run_dir, model, scenario_id, profile_id):
    run_dir = Path(run_dir)
    data = load_report_data(run_dir)
    rows = sorted(data.timeline, key=lambda row: row["time_seconds"])
    final = rows[-1]
    ledger = [event for event in data.events if event["kind"] == "paid_purchase"]
    with localcontext() as context:
        context.prec = 256
        spent = sum((Decimal(event["details"]["cost"]) for event in ledger), Decimal(0))
    quantity = sum(int(event["details"]["quantity"]) for event in ledger)
    plan = model.payment_plan
    end_time = final["time_seconds"]
    if spent != plan.spent_at(end_time) or quantity != plan.count_at(end_time):
        raise ValueError("Purchase ledger does not match the declared plan")
    summary = {
        "spent": str(spent), "purchase_quantity": quantity,
        "duration_seconds": end_time,
        "final_resources": final["resources"], "final_total_cps": final["total_cps"],
        "purchase_ledger": ledger,
        "milestones": milestone_times(data.events),
        "curves": [
            {"time_seconds": row["time_seconds"], **row["resources"], "total_cps": row["total_cps"]}
            for index, row in enumerate(rows)
            if index % max(1, math.ceil(len(rows) / 3000)) == 0 or index == len(rows) - 1
        ],
        "session": None, "progression": {},
    }
    if model.config.engine_id == "fish":
        pattern = model.session_patterns[model.player_profiles[profile_id].session_pattern]
        schedule = FishDailySessionSchedule.from_mapping(pattern)
        summary["session"] = {"daily_online_seconds": schedule.daily_online_seconds}
        checkpoint = json.loads((run_dir / "final_checkpoint.json").read_text(encoding="utf-8"))
        state = checkpoint["engine_state"]
        summary["fish_state"] = {
            "realm": state["trashMan"]["realmId"],
            "highest_realm": state["trashMan"]["highestRealmId"],
            "torpedo_id": state["torpedo"]["selectedId"],
            "barbell_id": state["barbell"]["equippedId"],
            "hall_upgrade_level": state["fishHall"]["upgradeLevel"],
            "strength_rebirths": state["rebirth"]["strengthCompletedCount"],
            "trash_man_rebirths": state["rebirth"]["trashManCompletedCount"],
        }
        summary["progression"] = data.behavior_progression.get("profiles", {}).get(profile_id, {}).get("summary", {})
    return summary


def milestone_times(events):
    times = {}
    fields = {
        "torpedo_purchased": ("torpedo", "torpedo_id_after"),
        "barbell_synthesized": ("barbell", "barbell_equipped_id_after_synthesis"),
        "fish_hall_upgraded": ("fish_hall", "fish_hall_upgrade_level_after"),
        "trash_man_realm_broken_through": ("realm", "trash_man_realm_after"),
        "strength_reborn": ("strength_rebirth", "strength_rebirth_completed_count_after"),
        "trash_man_reborn": ("trash_man_rebirth", "trash_man_rebirth_completed_count_after"),
    }
    for event in events:
        kind = event["kind"]
        key = None
        if kind.startswith(("unlock_", "buy_")) or kind == "milestone_claimed":
            key = f"{kind}:{event['item_id']}"
        elif kind in fields:
            prefix, field = fields[kind]
            value = event["details"].get(field)
            if value is not None:
                key = f"{prefix}:{value}"
        if key is not None:
            times[key] = min(times.get(key, event["time_seconds"]), event["time_seconds"])
    return dict(sorted(times.items()))


def compare_milestones(base, candidate, session=None):
    schedule = FishDailySessionSchedule.from_mapping(session) if session is not None else None
    rows = []
    for key in sorted(set(base) | set(candidate)):
        left, right = _milestone_time(base, key), _milestone_time(candidate, key)
        reached = left is not None and right is not None
        rows.append({
            "milestone": key,
            "status": "both_reached" if reached else "paid_only" if right is not None else "free_only",
            "free_seconds": left, "paid_seconds": right,
            "saved_wall_seconds": left - right if reached else None,
            "saved_active_seconds": schedule.active_seconds_at(left) - schedule.active_seconds_at(right) if reached and schedule else None,
        })
    return rows


def _milestone_time(values, key):
    # These Fish levels/counts are ordered by the engine's validated contracts.
    # Buying a higher torpedo directly reaches lower target tiers as well.
    prefix, _, target = key.partition(":")
    if prefix in {"torpedo", "fish_hall", "realm", "strength_rebirth", "trash_man_rebirth"} and target.isdigit():
        times = [time for item, time in values.items() if item.startswith(prefix + ":") and item.partition(":")[2].isdigit() and int(item.partition(":")[2]) >= int(target)]
        return min(times) if times else None
    return values.get(key)


def write_paid_report(payload, output_dir):
    output_dir = Path(output_dir)
    for row in payload["runs"]:
        if row.get("report_index") and row["status"] == "success":
            try:
                row["report_href"] = Path(os.path.relpath(row["report_index"], output_dir)).as_posix()
            except ValueError:
                row["report_href"] = Path(row["report_index"]).as_uri()
    baselines = {row["scenario_id"]: row for row in payload["runs"] if row["plan_id"] == "free" and "spent" in row}
    milestone_rows = []
    for row in payload["runs"]:
        baseline = baselines.get(row["scenario_id"])
        if "spent" not in row or baseline is None:
            continue
        with localcontext() as context:
            context.prec = 256
            row["resource_delta"] = {
                key: str(Decimal(value) - Decimal(baseline["final_resources"][key]))
                for key, value in row["final_resources"].items()
            }
        if row["plan_id"] != "free":
            row["milestone_comparison"] = compare_milestones(baseline["milestones"], row["milestones"], row["session"])
            milestone_rows.extend({"scenario_id": row["scenario_id"], "plan_id": row["plan_id"], **item} for item in row["milestone_comparison"])
    _json(output_dir / "paid_comparison.json", payload)
    with (output_dir / "paid_summary.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        fields = ["scenario_id", "plan_id", "status", "spent", "purchase_quantity", "final_resources", "resource_delta", "fish_state", "progression"]
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in payload["runs"]:
            writer.writerow({key: json.dumps(row[key], ensure_ascii=False) if isinstance(row.get(key), dict) else row.get(key, "") for key in fields})
    with (output_dir / "paid_milestones.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        fields = ["scenario_id", "plan_id", "milestone", "status", "free_seconds", "paid_seconds", "saved_wall_seconds", "saved_active_seconds"]
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(milestone_rows)
    asset = output_dir / "echarts.min.js"
    if not asset.exists():
        shutil.copyfile(Path(__file__).parent / "reporting" / "assets" / "echarts.min.js", asset)
    shutil.copyfile(Path(__file__).parent / "reporting" / "assets" / "paid-report.js", output_dir / "paid-report.js")
    (output_dir / "index.html").write_text(_html(payload, milestone_rows), encoding="utf-8", newline="\n")


def _json(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def _e(value):
    return html.escape(str(value), quote=True)


def _html(payload, milestones):
    example = payload["data_status"] == "example"
    banner = "示例商品 · 仅验证模拟机制，不代表实际商品平衡" if example else "生产商品配置 · 结果基于所声明的购买计划"
    summaries, ledger, progression = [], [], []
    labels = {"realm": "当前境界", "highest_realm": "最高境界", "torpedo_id": "鱼雷 ID", "barbell_id": "杠铃 ID", "hall_upgrade_level": "鱼厅等级", "strength_rebirths": "力量重生", "trash_man_rebirths": "垃圾佬转世"}
    for row in payload["runs"]:
        resources = "<br>".join(f"{_e(key)}: <span title='{_e(value)}'>{_e(format_human_number(value))}</span> <small>（差 {_e(format_human_number(row.get('resource_delta', {}).get(key, '—')))}）</small>" for key, value in row.get("final_resources", {}).items())
        report_link = f'<a href="{_e(row["report_href"])}">完整报告</a>' if row.get("report_href") else "—"
        summaries.append(f"<tr><td>{_e(row['scenario_id'])}</td><td>{_e(row['plan_id'])}</td><td>{_e(row['status'])}</td><td>{_e(row.get('spent', '—'))}</td><td>{_e(row.get('purchase_quantity', '—'))}</td><td>{resources or _e(row.get('message', ''))}</td><td>{report_link}</td></tr>")
        if "fish_state" in row:
            values = " · ".join(f"{labels[key]} {_e(value)}" for key, value in row["fish_state"].items())
            stats = row["progression"]
            progression.append(f"<tr><td>{_e(row['scenario_id'])} / {_e(row['plan_id'])}</td><td>{values}</td><td>{_e(stats.get('system_progression_count', '—'))}</td><td>{_e(stats.get('system_progression_max_interval_seconds', '—'))}</td><td>{_e(stats.get('system_progression_tail_gap_seconds', '—'))}</td></tr>")
        for event in row.get("purchase_ledger", []):
            details = event["details"]
            ledger.append(f"<tr><td>{_e(row['scenario_id'])} / {_e(row['plan_id'])}</td><td>{event['time_seconds']}</td><td>{_e(details['product_id'])}</td><td>{_e(details['quantity'])}</td><td>{_e(details['cost'])}</td><td>{_e(details['cumulative_spend'])}</td></tr>")
    status_labels = {"both_reached": "双方达成", "paid_only": "仅付费达成", "free_only": "仅免费达成"}
    milestone_html = []
    for row in milestones:
        values = [row["scenario_id"], row["plan_id"], row["milestone"], status_labels[row["status"]], row["free_seconds"], row["paid_seconds"], row["saved_wall_seconds"], row["saved_active_seconds"]]
        milestone_html.append("<tr>" + "".join(f"<td>{_e(value) if value is not None else '—'}</td>" for value in values) + "</tr>")
    chart_rows = []
    for row in payload["runs"]:
        curves = []
        for point in row.get("curves", []):
            values = {}
            for key, value in point.items():
                if key == "time_seconds":
                    continue
                number = Decimal(value)
                values[key] = {"raw": value, "y": float((max(Decimal(0), number) + 1).log10())}
            curves.append({"x": point["time_seconds"] / 3600, "values": values})
        chart_rows.append({"scenario": row["scenario_id"], "plan": row["plan_id"], "curves": curves})
    keys = list(dict.fromkeys([key for row in payload["runs"] for key in row.get("final_resources", {})] + ["total_cps"]))
    metric_labels = {"money": "金钱", "material": "材料", "strength": "力量", "total_cps": "每秒产出"}
    chart_json = json.dumps({"lanes": chart_rows, "titles": {key: metric_labels.get(key, key) for key in keys}}, ensure_ascii=False).replace("<", "\\u003c")
    chart_elements = "".join(f'<div id="paid-chart-{index}" class="chart"></div>' for index, _key in enumerate(keys))
    options = "".join(f'<option>{_e(value)}</option>' for value in dict.fromkeys(row["scenario_id"] for row in payload["runs"]))
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>付费玩家成长对照</title>
<style>body{{margin:0;background:#f3f6fa;color:#1c2b42;font:15px/1.6 "Segoe UI","Microsoft YaHei",sans-serif}}main{{max-width:1400px;margin:auto;padding:30px}}h1{{margin:4px 0}}h2{{font-size:19px}}section{{background:white;padding:22px;margin:20px 0;border:1px solid #dce4ee;border-radius:12px;overflow:auto}}.banner{{background:#fff1d4;padding:12px 18px;border-radius:8px}}small,.muted{{color:#61748d}}table{{width:100%;border-collapse:collapse;font-size:13px}}td,th{{padding:10px;text-align:left;border-bottom:1px solid #e4eaf1;white-space:nowrap}}th{{background:#f4f7fb}}.charts{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}.chart{{height:300px}}select{{padding:8px;min-width:200px}}@media(max-width:800px){{.charts{{grid-template-columns:1fr}}main{{padding:14px}}}}a{{color:#2563eb}}</style></head>
<body><main><div class="muted">IGESS / PAID PLAYER SIMULATION</div><h1>付费玩家成长对照</h1><p>画像 {_e(payload['profile_id'])} · 随机种子 {_e(payload['random_seed'])} · 花费单位 {_e(payload['currency'])} · 状态 {_e(payload['status'])}</p>
<div class="banner">{banner}</div><p class="muted">配置来源：{_e(payload['source'])}</p>
<section><h2>方案结果</h2><p class="muted">free 为基础画像的零新增购买方案，保留其原有倍率。花费只累计本场景已发生的购买。资源是期末余额，差值为付费方案减基线。</p><table><thead><tr><th>场景</th><th>方案</th><th>状态</th><th>累计花费</th><th>购买件数</th><th>期末资源与差值</th><th>详情</th></tr></thead><tbody>{''.join(summaries)}</tbody></table></section>
<section><h2>成长曲线</h2><select id="scenario">{options}</select><p class="muted">横轴为模拟小时，纵轴为 log10(1 + 数值)，悬停查看原始值。方案使用同画像和种子；购买后行为可能因资源变化而分化。</p><div class="charts">{chart_elements}</div></section>
<section><h2>Fish 成长与停滞</h2><table><thead><tr><th>场景 / 方案</th><th>期末状态</th><th>系统进展次数</th><th>最大相邻在线空窗（秒）</th><th>尾部在线空窗（秒）</th></tr></thead><tbody>{''.join(progression)}</tbody></table></section>
<section><h2>达到相同节点节省的时间</h2><p class="muted">正值表示付费更早达成。鱼雷、鱼厅、境界及重生按达到至少该档位／次数比较；杠铃按实际装备 ID 比较。未达成不记零、不外推；Generic 暂不换算在线时间。</p><table><thead><tr><th>场景</th><th>方案</th><th>节点</th><th>达成状态</th><th>免费秒数</th><th>付费秒数</th><th>节省墙钟秒数</th><th>节省在线秒数</th></tr></thead><tbody>{''.join(milestone_html)}</tbody></table></section>
<section><h2>购买明细</h2><table><thead><tr><th>场景 / 方案</th><th>发生秒数</th><th>商品</th><th>数量</th><th>本次花费</th><th>累计花费</th></tr></thead><tbody>{''.join(ledger)}</tbody></table></section>
<p><a href="paid_summary.csv">下载方案 CSV</a> · <a href="paid_milestones.csv">下载节点 CSV</a> · <a href="paid_comparison.json">完整结果与运行路径</a></p><p class="muted">输入摘要：{_e(payload['base_model_digest'])}</p></main>
<script id="paid-data" type="application/json">{chart_json}</script><script src="echarts.min.js"></script><script src="paid-report.js"></script></body></html>'''
