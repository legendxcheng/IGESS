"""Audit the explicit formal run IDs produced for the sale migration."""
import json
from decimal import Decimal
from pathlib import Path

from igess.fish_state import BigNumberDTO
from igess.numbers import SimNumber

ROOT = Path(__file__).resolve().parents[2]
RUN_IDS = (
    "20260916T014522691100Z-smoke",
    "20260916T014533931252Z-day_1_growth",
    "20260916T014553162924Z-week_1_growth",
    "20260916T014643708590Z-month_1_growth",
)


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


audits = []
fingerprints = []
for run_id in RUN_IDS:
    folder = ROOT / "projects/fish/runs" / run_id
    out = folder / "output"
    manifest = read(out / "run_manifest.json")
    assert all((out / name).is_file() for name in manifest["artifacts"])
    assert (folder / "report/index.html").is_file()
    assert manifest["production_data"] is True
    fingerprints.append((manifest["model_digest"], manifest["data_files"], manifest["loader_files"]))
    checkpoint = read(out / "final_checkpoint.json")
    state = checkpoint["engine_state"]
    events = read(out / "events.json")
    if isinstance(events, dict):
        events = events["events"]
    sales = [event for event in events if event["kind"] == "fish_sold"]
    sold = sum(int(event["details"]["fish_sale_count"]) for event in sales)
    assert sold == checkpoint["event_counters"].get("fish_sold_count", 0)
    assert sold + len(state["fish"]["items"]) == state["statistics"]["totalFishCaught"]
    assert state["fish"]["nextInstanceId"] == state["statistics"]["totalFishCaught"] + 1
    for event in sales:
        detail = event["details"]
        ids = json.loads(detail["fish_sale_instance_ids"])
        prices = json.loads(detail["fish_sale_prices"])
        assert len(ids) == len(set(ids)) == len(prices) == int(detail["fish_sale_count"])
        expected = BigNumberDTO.from_value(
            SimNumber.parse(detail["material_before_fish_sale"]) + SimNumber.parse(detail["fish_sale_material_added"]),
            allow_negative=False,
        ).to_sim_number()
        assert expected == SimNumber.parse(detail["material_after_fish_sale"])
        assert int(detail["behavior_duration_seconds"]) == 3
        assert (event["time_seconds"] - 3) % 86400 < 7200
        assert event["time_seconds"] % 86400 <= 7200
    sale_total = sum((Decimal(event["details"]["fish_sale_material_added"]) for event in sales), Decimal(0))
    trash_total = sum((Decimal(event["details"].get("trash_material_added", "0")) for event in events), Decimal(0))
    report = read(folder / "report/report_data.json")
    investment = report["fish_progression"]["investment"]["profiles"]["default"]
    assert Decimal(investment["sale_material"]["exact_value"]) == sale_total
    assert Decimal(investment["trash_material"]["exact_value"]) == trash_total
    assert int(investment["fish_sold_count"]["exact_value"]) == sold
    luck = read(out / "luck_progression.json")["profiles"]["default"]["summary"]
    progression = read(out / "behavior_progression.json")["profiles"]["default"]["summary"]
    audits.append({
        "run_id": run_id, "model_digest": manifest["model_digest"],
        "sale_batches": len(sales), "fish_sold": sold, "fish_remaining": len(state["fish"]["items"]),
        "sale_material": str(sale_total), "trash_material": str(trash_total),
        "sale_share_percent": str(sale_total * 100 / (sale_total + trash_total)) if sale_total + trash_total else "0",
        "first_sale_seconds": sales[0]["time_seconds"] if sales else None,
        "wallet": state["wallet"], "fish_hall": state["fishHall"], "torpedo": state["torpedo"],
        "barbell": state["barbell"], "realm": state["trashMan"]["realmId"], "rebirth": state["rebirth"],
        "luck": luck, "progression": progression,
    })
assert all(value == fingerprints[0] for value in fingerprints)
output = ROOT / ".scratch/fish-sale-material/run-audit.json"
output.write_text(json.dumps(audits, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
print(json.dumps(audits, ensure_ascii=False, indent=2))
