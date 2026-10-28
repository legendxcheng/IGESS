"""Serial matched pairs. Run alone: no tests or simulations alongside this job."""
from __future__ import annotations
import argparse
import json
import statistics
import subprocess
import sys
from pathlib import Path
from compare import compare

HERE = Path(__file__).resolve().parent


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenarios", nargs="+", default=["day_1_growth", "week_1_growth"])
    parser.add_argument("--pairs", type=int, default=3)
    parser.add_argument("--prefix", default="final")
    args = parser.parse_args()
    rows = []
    for scenario in args.scenarios:
        for number in range(1, args.pairs + 1):
            tag = f"{args.prefix}-{number}"
            for variant in ("baseline", "candidate"):
                print(f"START {tag} {variant} {scenario}", flush=True)
                subprocess.run([sys.executable, str(HERE/"benchmark.py"), variant, scenario, tag], check=True)
            paths = [HERE/"results"/f"{tag}-{v}-{scenario}.json" for v in ("baseline", "candidate")]
            result = compare(*paths)
            result.update(scenario=scenario, pair=number)
            rows.append(result)
            print(json.dumps(result), flush=True)
            (HERE/"results"/f"{args.prefix}-comparisons.json").write_text(
                json.dumps(rows, indent=2), encoding="utf-8")
    summary = {}
    for scenario in args.scenarios:
        subset = [r for r in rows if r["scenario"] == scenario]
        summary[scenario] = {key: {
            "values": [r[key] for r in subset],
            "median": statistics.median(r[key] for r in subset),
            "min": min(r[key] for r in subset), "max": max(r[key] for r in subset),
        } for key in ("baseline_seconds", "candidate_seconds")}
    (HERE/"results"/f"{args.prefix}-summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
