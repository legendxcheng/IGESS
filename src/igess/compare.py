from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from .metrics import extract_metrics, numeric_delta


def compare_runs(base_run: str | Path, candidate_run: str | Path, output_dir: str | Path) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    base = extract_metrics(base_run)
    candidate = extract_metrics(candidate_run)
    comparison = {
        "schema_version": 1,
        "base": base,
        "candidate": candidate,
        "deltas": _deltas(base, candidate),
    }
    (output_dir / "comparison.json").write_text(
        json.dumps(comparison, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    index = output_dir / "index.html"
    index.write_text(_html(comparison), encoding="utf-8", newline="\n")
    return index


def _deltas(base: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "final_resource_delta": _nested_value_delta(
            base["final_resources"], candidate["final_resources"]
        ),
        "unlock_time_delta_seconds": _nested_value_delta(
            base["unlock_times"], candidate["unlock_times"]
        ),
        "purchase_count_delta": _nested_value_delta(
            base["purchase_counts"], candidate["purchase_counts"]
        ),
        "prestige_count_delta": _value_delta(
            base["prestige_counts"], candidate["prestige_counts"]
        ),
        "payback_delta_seconds": _nested_value_delta(
            base["payback_seconds"], candidate["payback_seconds"]
        ),
    }


def _nested_value_delta(base: dict[str, dict], candidate: dict[str, dict]) -> dict[str, dict[str, str]]:
    profiles = sorted(set(base) | set(candidate))
    return {
        profile: _value_delta(base.get(profile, {}), candidate.get(profile, {}))
        for profile in profiles
    }


def _value_delta(base: dict, candidate: dict) -> dict[str, str]:
    keys = sorted(set(base) | set(candidate))
    return {
        str(key): numeric_delta(candidate.get(key, 0), base.get(key, 0))
        for key in keys
    }


def _html(comparison: dict[str, Any]) -> str:
    delta_rows = []
    for group, profiles in comparison["deltas"].items():
        if isinstance(profiles, dict):
            for profile, values in profiles.items():
                if isinstance(values, dict):
                    for key, value in values.items():
                        delta_rows.append((group, profile, key, value))
                else:
                    delta_rows.append((group, "", profile, values))
    rows = "\n".join(
        "        <tr>"
        f"<td>{_e(group)}</td><td>{_e(profile)}</td><td>{_e(key)}</td><td>{_e(value)}</td>"
        "</tr>"
        for group, profile, key, value in delta_rows
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>IGESS Comparison</title>
  <style>
    body {{ margin: 0; font-family: Segoe UI, Arial, sans-serif; background: #f5f7fa; color: #17202a; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 24px; }}
    section {{ background: white; border: 1px solid #d9e1ea; border-radius: 6px; padding: 18px; margin: 14px 0; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ border-bottom: 1px solid #e3e8ef; padding: 8px; text-align: left; }}
  </style>
</head>
<body>
  <main>
    <h1>IGESS Comparison</h1>
    <section>
      <h2>Scenario</h2>
      <p>Base: <code>{_e(comparison['base']['scenario_id'])}</code></p>
      <p>Candidate: <code>{_e(comparison['candidate']['scenario_id'])}</code></p>
    </section>
    <section>
      <h2>Deltas</h2>
      <table>
        <thead><tr><th>Metric</th><th>Profile</th><th>Key</th><th>Candidate - Base</th></tr></thead>
        <tbody>
{rows}
        </tbody>
      </table>
    </section>
  </main>
</body>
</html>
"""


def _e(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)
