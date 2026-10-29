"""Serial final-byte acceptance; run only after regression processes finish."""
from pathlib import Path
import json
import statistics
import subprocess
import sys
from datetime import datetime, timezone

from compare import compare

HERE = Path(__file__).resolve().parent
rows = []
order = []


def pair(scenario: str, tag: str, *, trace: bool = False) -> None:
    for variant in ("baseline", "combined"):
        command = [sys.executable, str(HERE / "benchmark.py"), variant, scenario, tag]
        if trace:
            command.append("--trace")
        order.append({"tag": tag, "variant": variant, "scenario": scenario,
                      "started_utc": datetime.now(timezone.utc).isoformat()})
        (HERE / "results/final-order.json").write_text(json.dumps(order, indent=2), encoding="utf-8")
        subprocess.run(command, check=True)
    first, second = (HERE / "results" / f"{tag}-{v}-{scenario}.json" for v in ("baseline", "combined"))
    result = dict(scenario=scenario, tag=tag, diagnostic_only=trace, **compare(first, second))
    rows.append(result)
    (HERE / "results/final-comparisons.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(json.dumps(result), flush=True)
    if trace:
        # Negative control must fail before consulting persisted final artifacts.
        altered = json.loads(second.read_text(encoding="utf-8"))
        altered["observation_trace"][0]["state_sha256"] = "0" * 64
        negative = HERE / "results/negative-control.json"
        negative.write_text(json.dumps(altered), encoding="utf-8")
        try:
            compare(first, negative)
        except AssertionError as exc:
            assert str(exc) == "logical observations"
            negative.write_text(json.dumps({"detected": True, "failure": str(exc),
                                           "changed": "first logical state hash"}), encoding="utf-8")
        else:
            raise AssertionError("negative control accepted corruption")


pair("week_1_growth", "final-trace", trace=True)
for i in range(1, 4):
    pair("week_1_growth", f"final-{i}")
for i in range(1, 3):
    pair("day_1_growth", f"final-{i}")

summary = {}
for scenario in ("week_1_growth", "day_1_growth"):
    selected = [r for r in rows if r["scenario"] == scenario and not r["diagnostic_only"]]
    baseline = [r["baseline_seconds"] for r in selected]
    candidate = [r["candidate_seconds"] for r in selected]
    summary[scenario] = {
        "baseline_seconds": baseline, "candidate_seconds": candidate,
        "baseline_median": statistics.median(baseline), "candidate_median": statistics.median(candidate),
        "baseline_range": [min(baseline), max(baseline)], "candidate_range": [min(candidate), max(candidate)],
        "median_reduction_percent": 100 * (1 - statistics.median(candidate) / statistics.median(baseline)),
        "all_pairs_faster": all(c < b for b, c in zip(baseline, candidate)),
    }
(HERE / "results/final-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
print(json.dumps(summary, indent=2), flush=True)
