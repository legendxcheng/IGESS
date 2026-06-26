from __future__ import annotations

import csv
import json
from pathlib import Path

from .analyzer import Analyzer
from .schema import SimulationResult


class OutputWriter:
    @classmethod
    def write_all(cls, result: SimulationResult, output_dir: str | Path) -> None:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        cls.write_json(result, output_dir / "timeline.json")
        cls.write_csv(result, output_dir / "timeline.csv")
        cls.write_events_json(result, output_dir / "events.json")
        cls.write_events_csv(result, output_dir / "events.csv")
        (output_dir / "analysis.md").write_text(
            Analyzer.markdown(result), encoding="utf-8", newline="\n"
        )

    @classmethod
    def write_json(cls, result: SimulationResult, path: Path) -> None:
        payload = [row.to_ordered_dict() for row in result.timeline]
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )

    @classmethod
    def write_csv(cls, result: SimulationResult, path: Path) -> None:
        fieldnames = [
            "scenario_id",
            "profile_id",
            "time_seconds",
            "resources",
            "generators_owned",
            "upgrades_purchased",
            "total_cps",
        ]
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
            writer.writeheader()
            for row in result.timeline:
                data = row.to_ordered_dict()
                data["resources"] = json.dumps(data["resources"], ensure_ascii=False, sort_keys=True)
                data["generators_owned"] = json.dumps(
                    data["generators_owned"], ensure_ascii=False, sort_keys=True
                )
                data["upgrades_purchased"] = json.dumps(data["upgrades_purchased"], ensure_ascii=False)
                writer.writerow(data)

    @classmethod
    def write_events_json(cls, result: SimulationResult, path: Path) -> None:
        payload = [event.to_ordered_dict() for event in result.events]
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )

    @classmethod
    def write_events_csv(cls, result: SimulationResult, path: Path) -> None:
        fieldnames = [
            "scenario_id",
            "profile_id",
            "time_seconds",
            "kind",
            "item_id",
            "details",
        ]
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
            writer.writeheader()
            for event in result.events:
                data = event.to_ordered_dict()
                data["details"] = json.dumps(data["details"], ensure_ascii=False, sort_keys=True)
                writer.writerow(data)
