"""Compare fixed-input formal runs, including exact checkpoint replay history."""

import base64
import hashlib
import json
import statistics
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
CORE = ("timeline.json", "events.json", "source_progression.json", "source_behavior.json")


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def timing(name):
    result = read(HERE / name)
    assert result["response"]["ok"]
    return result


def compare(before, after):
    old = Path(before["response"]["result"]["output_dir"])
    new = Path(after["response"]["result"]["output_dir"])
    hashes = {}
    for name in CORE:
        first, second = (folder / name for folder in (old, new))
        assert first.read_bytes() == second.read_bytes(), name
        hashes[name] = hashlib.sha256(second.read_bytes()).hexdigest()
    first, second = (read(folder / "final_checkpoint.json") for folder in (old, new))
    for key in first:
        if key not in {"model_digest", "engine_state"}:
            assert first[key] == second[key], key
    sessions = [json.loads(zlib.decompress(base64.b64decode(c["engine_state"]["data"])))
                for c in (first, second)]
    for key in sessions[0]:
        if key != "codeDigest":
            assert sessions[0][key] == sessions[1][key], key
    old_manifest, new_manifest = (read(folder / "run_manifest.json") for folder in (old, new))
    for key in old_manifest["source_runtime"]:
        if key not in {"code_sha256", "integration_code_sha256", "timings_seconds"}:
            assert old_manifest["source_runtime"][key] == new_manifest["source_runtime"][key], key
    events = read(new / "events.json")
    return {
        "baseline_run": old.parent.name,
        "optimized_run": new.parent.name,
        "core_sha256": hashes,
        "core_bytes_identical": True,
        "checkpoint_history_identical": True,
        "checkpoint_history_entries": len(sessions[1]["history"]),
        "samples": len(read(new / "timeline.json")),
        "rejections": sum(e["kind"] == "source_rejected" for e in events),
        "old_seconds": before["timings"]["formal_workflow_seconds"],
        "new_seconds": after["timings"]["formal_workflow_seconds"],
        "timings_seconds": new_manifest["source_runtime"]["timings_seconds"],
        "source_runtime": {k: v for k, v in new_manifest["source_runtime"].items()
                           if k.endswith("sha256")},
    }


baseline = [timing(f"baseline-{n}-day_1_growth-timing.json") for n in (1, 2, 3)]
optimized = [timing(f"optimized-{n}-day_1_growth-timing.json") for n in (1, 2, 3)]
day = [compare(baseline[0], item) for item in optimized]
for item in baseline[1:]:
    compare(baseline[0], item)
result = {"day_runs": day}
for label, items in (("baseline", baseline), ("optimized", optimized)):
    times = [item["timings"]["formal_workflow_seconds"] for item in items]
    result[label] = {"seconds": times, "median": statistics.median(times),
                     "minimum": min(times), "maximum": max(times)}
result["day_reduction_pct"] = 100 * (1 - result["optimized"]["median"] / result["baseline"]["median"])
month = HERE / "optimized-month_1_growth-timing.json"
if month.exists():
    result["month"] = compare(
        read(HERE.parent / "fish-source-report-readability" / "latest-month_1_growth-timing.json"),
        read(month),
    )
output = HERE / "comparison.json"
output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
print(json.dumps(result, ensure_ascii=False, indent=2))
