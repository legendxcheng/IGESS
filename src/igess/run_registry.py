from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    status: str
    scenario_id: str
    message: str
    run_dir: Path
    output_dir: Path
    report_dir: Path
    report_index: Path
    status_path: Path


class RunRegistry:
    def __init__(self, runs_root: str | Path):
        self.runs_root = Path(runs_root)

    def new_run_dir(self, scenario_id: str) -> Path:
        from datetime import datetime, timezone

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        safe_scenario = "".join(char if char.isalnum() or char in "-_" else "_" for char in scenario_id)
        return self.runs_root / f"{stamp}-{safe_scenario}"

    def write_status(
        self,
        run_dir: Path,
        *,
        status: str,
        scenario_id: str,
        message: str,
        output_dir: Path,
        report_dir: Path,
        report_index: Path,
    ) -> RunRecord:
        run_dir.mkdir(parents=True, exist_ok=True)
        status_path = run_dir / "run_status.json"
        payload = {
            "run_id": run_dir.name,
            "status": status,
            "scenario_id": scenario_id,
            "message": message,
            "output_dir": str(output_dir),
            "report_dir": str(report_dir),
            "report_index": str(report_index),
        }
        status_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return self._record_from_payload(status_path, payload)

    def list_runs(self) -> list[RunRecord]:
        if not self.runs_root.exists():
            return []
        records = []
        for status_path in sorted(self.runs_root.glob("*/run_status.json")):
            payload = json.loads(status_path.read_text(encoding="utf-8"))
            records.append(self._record_from_payload(status_path, payload))
        return sorted(records, key=lambda record: record.run_id)

    def _record_from_payload(self, status_path: Path, payload: dict[str, Any]) -> RunRecord:
        return RunRecord(
            run_id=str(payload["run_id"]),
            status=str(payload["status"]),
            scenario_id=str(payload.get("scenario_id") or ""),
            message=str(payload.get("message") or ""),
            run_dir=status_path.parent,
            output_dir=Path(str(payload.get("output_dir") or status_path.parent / "output")),
            report_dir=Path(str(payload.get("report_dir") or status_path.parent / "report")),
            report_index=Path(str(payload.get("report_index") or status_path.parent / "report" / "index.html")),
            status_path=status_path,
        )
