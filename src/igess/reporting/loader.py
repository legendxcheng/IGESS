from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ReportLoadError(ValueError):
    pass


@dataclass(frozen=True)
class ReportData:
    run_dir: Path
    manifest: dict[str, Any]
    timeline: list[dict[str, Any]]
    events: list[dict[str, Any]]
    analysis: dict[str, Any]
    payback_rows: list[dict[str, str]]
    missing_artifacts: list[str]

    @property
    def scenario_id(self) -> str:
        value = self.manifest.get("scenario_id") or self.analysis.get("scenario_id")
        return str(value or "")

    @property
    def profiles(self) -> list[str]:
        manifest_profiles = self.manifest.get("profiles")
        if isinstance(manifest_profiles, list):
            return [str(profile) for profile in manifest_profiles]
        return sorted({str(row.get("profile_id")) for row in self.timeline if row.get("profile_id")})


def load_report_data(run_dir: str | Path) -> ReportData:
    run_dir = Path(run_dir)
    missing: list[str] = []
    manifest = _read_optional_json(run_dir / "run_manifest.json", missing, default={})
    timeline = _read_required_json_list(run_dir / "timeline.json")
    events = _read_required_json_list(run_dir / "events.json")
    analysis = _read_required_json_dict(run_dir / "analysis.json")
    payback_rows = _read_optional_csv(run_dir / "payback.csv", missing)
    return ReportData(
        run_dir=run_dir,
        manifest=manifest,
        timeline=timeline,
        events=events,
        analysis=analysis,
        payback_rows=payback_rows,
        missing_artifacts=missing,
    )


def _read_required_json_list(path: Path) -> list[dict[str, Any]]:
    data = _read_json(path)
    if not isinstance(data, list):
        raise ReportLoadError(f"{path.name} must contain a JSON array")
    return [dict(item) for item in data]


def _read_required_json_dict(path: Path) -> dict[str, Any]:
    data = _read_json(path)
    if not isinstance(data, dict):
        raise ReportLoadError(f"{path.name} must contain a JSON object")
    return data


def _read_optional_json(path: Path, missing: list[str], default):
    if not path.exists():
        missing.append(path.name)
        return default
    data = _read_json(path)
    if not isinstance(data, dict):
        raise ReportLoadError(f"{path.name} must contain a JSON object")
    return data


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ReportLoadError(f"Missing required report artifact: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise ReportLoadError(f"Could not parse {path.name}: {exc.msg}") from exc


def _read_optional_csv(path: Path, missing: list[str]) -> list[dict[str, str]]:
    if not path.exists():
        missing.append(path.name)
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]
