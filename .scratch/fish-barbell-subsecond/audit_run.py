"""Verify half-second barbell yields in the named formal production run."""
import hashlib
import json
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUN_ID = "20260921T085635814804Z-day_1_growth"
RUN = ROOT / "projects/fish/runs" / RUN_ID
OUT = RUN / "output"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


manifest = read(OUT / "run_manifest.json")
checkpoint = read(OUT / "final_checkpoint.json")
assert manifest["production_data"] is True
assert manifest["matches_production_data"] is True
assert manifest["overrides"] == []
assert Path(manifest["data_root"]).resolve() == Path("E:/fish-oasis/igess_export/json").resolve()
assert manifest["scenario_id"] == checkpoint["scenario_id"] == "day_1_growth"
assert manifest["profiles"] == [checkpoint["profile_id"]] == ["default"]
assert manifest["model_digest"] == checkpoint["model_digest"]
assert checkpoint["simulated_time_seconds"] == 86400
assert checkpoint["root_random_seed"] == 20260626
assert all((OUT / name).is_file() for name in manifest["artifacts"])
assert (RUN / "report/index.html").is_file()
for item in manifest["data_files"] + manifest["loader_files"]:
    path = Path(manifest["data_root"]) / item["file"]
    assert "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]
rows = {row["id"]: row for row in read(Path(manifest["data_root"]) / "tbbarbell.json")}
assert len(rows) == 15
assert all(Decimal(str(row["timeCost"])) == Decimal("0.5") for row in rows.values())
events = read(OUT / "events.json")
training = [event for event in events if event["kind"] == "barbell_exercise_completed"]
assert len(training) == checkpoint["event_counters"]["exercise_barbell_completed"] > 0
examples = {}
for event in events:
    details = event["details"]
    if event["kind"] != "barbell_exercise_completed":
        assert Decimal(details.get("barbell_strength_added", "0")) == 0
        continue
    row = rows[int(details["barbell_equipped_id_before_command"])]
    elapsed = Decimal(details["barbell_settlement_elapsed_seconds"])
    assert elapsed == Decimal(details["behavior_duration_seconds"]) == 60
    assert Decimal(details["barbell_time_cost_seconds_before_command"]) == Decimal("0.5")
    assert details["barbell_training_active"] == "true"
    assert details["fish_production_mode"] == "online"
    cycles = elapsed / Decimal(str(row["timeCost"]))
    assert cycles == 120
    base = cycles * Decimal(str(row["strengthPerExercise"]))
    assert Decimal(details["barbell_strength_base_added"]) == base
    assert Decimal(details["barbell_strength_added"]) == base * Decimal(details["barbell_strength_reward_multiplier"])
    examples[row["id"]] = {
        "cycles_per_60s": int(cycles),
        "strength_per_exercise": row["strengthPerExercise"],
        "strength_added_per_60s": str(base),
    }
luck = read(OUT / "luck_progression.json")["profiles"]["default"]["summary"]
progression = read(OUT / "behavior_progression.json")["profiles"]["default"]["summary"]
summary = {
    "run_id": RUN_ID, "model_digest": manifest["model_digest"],
    "training_behaviors": len(training), "training_repetitions": len(training) * 120,
    "barbells_exercised": examples,
    "final_wallet": checkpoint["engine_state"]["wallet"],
    "luck": luck, "progression": progression,
}
(Path(__file__).parent / "run-audit.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n",
)
print(json.dumps({key: value for key, value in summary.items() if key not in {"luck", "progression"}}, ensure_ascii=False, indent=2))
