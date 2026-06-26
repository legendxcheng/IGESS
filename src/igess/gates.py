from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml

from .metrics import extract_metrics


@dataclass(frozen=True)
class GateResult:
    ok: bool
    failures: list[dict[str, str]]
    output_dir: Path


def evaluate_gates(
    base_run: str | Path,
    candidate_run: str | Path,
    config_path: str | Path,
    output_dir: str | Path,
) -> GateResult:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    base = extract_metrics(base_run)
    candidate = extract_metrics(candidate_run)
    gates = _load_gates(config_path, candidate["scenario_id"])
    failures: list[dict[str, str]] = []
    failures.extend(_check_max_payback(candidate, gates.get("max_payback_seconds", {})))
    failures.extend(_check_min_prestige(candidate, gates.get("min_prestige_gain", {})))
    failures.extend(
        _check_max_unlock_delay_pct(
            base,
            candidate,
            gates.get("max_unlock_delay_pct", {}),
        )
    )
    result = GateResult(ok=not failures, failures=failures, output_dir=output_dir)
    _write_results(result, base, candidate)
    return result


def _load_gates(config_path: str | Path, scenario_id: str) -> dict[str, Any]:
    data = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    return dict(data.get("regression_gates", {}).get(scenario_id, {}))


def _check_max_payback(metrics: dict[str, Any], thresholds: dict[str, Any]) -> list[dict[str, str]]:
    failures = []
    for key, limit in sorted(thresholds.items()):
        limit_value = _decimal(limit)
        for profile, rows in sorted(metrics["payback_seconds"].items()):
            actual = _decimal(rows.get(key, "Infinity"))
            if actual is None or actual > limit_value:
                failures.append(
                    {
                        "rule": "max_payback_seconds",
                        "profile": profile,
                        "key": key,
                        "actual": rows.get(key, "Infinity"),
                        "limit": str(limit),
                    }
                )
    return failures


def _check_min_prestige(metrics: dict[str, Any], thresholds: dict[str, Any]) -> list[dict[str, str]]:
    failures = []
    for profile, minimum in sorted(thresholds.items()):
        actual = int(metrics["prestige_counts"].get(profile, 0))
        if actual < int(minimum):
            failures.append(
                {
                    "rule": "min_prestige_gain",
                    "profile": profile,
                    "key": "prestige_resets",
                    "actual": str(actual),
                    "limit": str(minimum),
                }
            )
    return failures


def _check_max_unlock_delay_pct(
    base: dict[str, Any], candidate: dict[str, Any], thresholds: dict[str, Any]
) -> list[dict[str, str]]:
    failures = []
    for key, limit in sorted(thresholds.items()):
        limit_value = _decimal(limit)
        for profile, candidate_rows in sorted(candidate["unlock_times"].items()):
            if key not in candidate_rows:
                continue
            base_time = _decimal(base["unlock_times"].get(profile, {}).get(key, 0))
            candidate_time = _decimal(candidate_rows[key])
            if base_time == 0:
                actual_pct = Decimal("0") if candidate_time == 0 else Decimal("Infinity")
            else:
                actual_pct = ((candidate_time - base_time) / base_time) * Decimal("100")
            if actual_pct > limit_value:
                failures.append(
                    {
                        "rule": "max_unlock_delay_pct",
                        "profile": profile,
                        "key": key,
                        "actual": str(actual_pct),
                        "limit": str(limit),
                    }
                )
    return failures


def _write_results(result: GateResult, base: dict[str, Any], candidate: dict[str, Any]) -> None:
    payload = {
        "schema_version": 1,
        "status": "passed" if result.ok else "failed",
        "failures": result.failures,
        "base_scenario_id": base["scenario_id"],
        "candidate_scenario_id": candidate["scenario_id"],
    }
    (result.output_dir / "gate_results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    lines = ["# Regression Gates", "", "PASSED" if result.ok else "FAILED", ""]
    for failure in result.failures:
        lines.append(
            f"- {failure['rule']} `{failure['key']}` for `{failure['profile']}`: "
            f"{failure['actual']} > {failure['limit']}"
        )
    (result.output_dir / "gate_results.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8", newline="\n"
    )


def _decimal(value) -> Decimal:
    try:
        text = str(value)
        if text == "Infinity":
            return Decimal("Infinity")
        return Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid gate number: {value}") from exc
