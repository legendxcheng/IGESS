"""Validate the formal dense-sampling artifacts against the prior 30-day run."""

import json
from pathlib import Path

HERE = Path(__file__).parent
timing = json.loads((HERE / "latest-month_1_growth-timing.json").read_text(encoding="utf-8"))
assert timing["response"]["ok"], timing["response"]
result = timing["response"]["result"]
new = Path(result["output_dir"])
old = Path("projects/fish_source/runs/20260924T065413912580Z-month_1_growth/output")


def read(folder, name):
    return json.loads((folder / name).read_text(encoding="utf-8"))


manifest = read(new, "run_manifest.json")
previous = read(old, "run_manifest.json")
for name in manifest["artifacts"]:
    assert (new / name).is_file(), name
assert Path(result["report_index"]).is_file()
assert manifest["scenario_id"] == "month_1_growth"
assert manifest["profiles"] == ["default"]
assert manifest["overrides"] == []
runtime = manifest["source_runtime"]
assert Path(runtime["selected_export_root"]) == Path("E:/fish-oasis/igess_export/json")
assert runtime["sampling_time_basis"] == "online"
assert runtime["record_interval_seconds"] == 300
rows, old_rows = read(new, "timeline.json"), read(old, "timeline.json")
times = {row["time_seconds"] for row in rows}
assert all(day * 86400 + offset in times for day in range(30) for offset in range(300, 7201, 300))
assert all(time % 86400 <= 7200 for time in times)
assert rows[-1]["time_seconds"] == 2592000
events, old_events = read(new, "events.json"), read(old, "events.json")
rebirths = [row for row in events if row["kind"] in {"rebirth_strength", "rebirth_trash_man"}]
for event in rebirths:
    count_key = "strength_rebirth_count" if event["kind"] == "rebirth_strength" else "trash_man_rebirth_count"
    receipt = json.loads(event["details"]["receipt"])
    samples = [row for row in rows if row["time_seconds"] == event["time_seconds"]]
    counts = {int(row["resources"][count_key]) for row in samples}
    assert {receipt["oldCompletedCount"], receipt["newCompletedCount"]} <= counts
checkpoint = read(new, "final_checkpoint.json")
assert checkpoint["simulated_time_seconds"] == 2592000
assert checkpoint["behavior_state"]["active_time_seconds"] == 216000
assert checkpoint["root_random_seed"] == read(old, "final_checkpoint.json")["root_random_seed"]
report = read(Path(result["report_index"]).parent, "report_data.json")
assert report["fish_progression"]["available"]
core = report["fish_progression"]["core"]["profiles"]["default"]
assert len(core["rows"]) == len(rows)
assert core["summary"]["active_duration_seconds"]["exact_value"] == "216000"
assert "300 秒采样" in report["fish_progression"]["notes"]["core"]
old_report = read(old.parent / "report", "report_data.json")
summary = {
    "run_id": new.parent.name,
    "model_digest": manifest["model_digest"],
    "source_code_unchanged": runtime["code_sha256"] == previous["source_runtime"]["code_sha256"],
    "production_export_unchanged": runtime["selected_export_sha256"] == previous["source_runtime"]["selected_export_sha256"],
    "old_samples": len(old_rows),
    "new_samples": len(rows),
    "periodic_samples": 720,
    "start_and_boundary_samples": len(rows) - 720,
    "business_events_identical": events == old_events,
    "behavior_counts_identical": read(new, "source_behavior.json") == read(old, "source_behavior.json"),
    "final_observation_identical": rows[-1] == old_rows[-1],
    "old_daily_observations_preserved": all(row in rows for row in old_rows),
    "rejections": sum(row["kind"] == "source_rejected" for row in events),
    "rebirths_with_before_after_samples": len(rebirths),
    "timings": {**timing["timings"], **runtime["timings_seconds"]},
    "old_core_summary": old_report["fish_progression"]["core"]["profiles"]["default"]["summary"],
    "new_core_summary": core["summary"],
    "growth_summary": report["fish_progression"]["persistent"]["profiles"]["default"]["summary"],
    "html_bytes": Path(result["report_index"]).stat().st_size,
    "report_index": result["report_index"],
}
(HERE / "dense-sampling-comparison.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(summary, ensure_ascii=False, indent=2))
