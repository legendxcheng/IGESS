from __future__ import annotations

import csv
import json
from pathlib import Path

from .rng import RngSimulationResult
from .schema import EconomyModel


class RngOutputWriter:
    ARTIFACTS = [
        "rng_summary.json",
        "rng_distribution.csv",
        "rng_events.json",
        "rng_events.csv",
        "rng_analysis.md",
    ]

    @classmethod
    def write_all(
        cls,
        result: RngSimulationResult,
        output_dir: str | Path,
        model: EconomyModel,
    ) -> None:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        cls.write_summary_json(result, output_dir / "rng_summary.json")
        cls.write_distribution_csv(result, output_dir / "rng_distribution.csv")
        cls.write_events_json(result, output_dir / "rng_events.json")
        cls.write_events_csv(result, output_dir / "rng_events.csv")
        (output_dir / "rng_analysis.md").write_text(
            cls.markdown(result), encoding="utf-8", newline="\n"
        )
        cls.write_manifest(result, model, output_dir / "rng_manifest.json")

    @classmethod
    def write_summary_json(cls, result: RngSimulationResult, path: Path) -> None:
        payload = [summary.to_ordered_dict() for summary in result.summaries]
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )

    @classmethod
    def write_distribution_csv(cls, result: RngSimulationResult, path: Path) -> None:
        fieldnames = ["scenario_id", "profile_id", "trial_index", "best_rarity", "first_hits"]
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
            writer.writeheader()
            for row in result.distribution:
                data = row.to_ordered_dict()
                data["first_hits"] = json.dumps(
                    data["first_hits"], ensure_ascii=False, sort_keys=True
                )
                writer.writerow(data)

    @classmethod
    def write_events_json(cls, result: RngSimulationResult, path: Path) -> None:
        payload = [event.to_ordered_dict() for event in result.events]
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )

    @classmethod
    def write_events_csv(cls, result: RngSimulationResult, path: Path) -> None:
        fieldnames = [
            "scenario_id",
            "profile_id",
            "trial_index",
            "roll_index",
            "rarity_id",
            "denominator",
        ]
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
            writer.writeheader()
            for event in result.events:
                writer.writerow(event.to_ordered_dict())

    @classmethod
    def write_manifest(cls, result: RngSimulationResult, model: EconomyModel, path: Path) -> None:
        payload = {
            "schema_version": 1,
            "scenario_id": result.scenario_id,
            "model_id": model.config.model_id,
            "random_seed": model.config.random_seed,
            "profiles": sorted({summary.profile_id for summary in result.summaries}),
            "artifacts": list(cls.ARTIFACTS),
        }
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )

    @classmethod
    def markdown(cls, result: RngSimulationResult) -> str:
        lines = [
            "# RNG Simulation Analysis",
            "",
            f"Scenario: `{result.scenario_id}`",
            "",
            "## Profiles",
            "",
        ]
        for summary in result.summaries:
            lines.extend(
                [
                    f"### {summary.profile_id}",
                    "",
                    f"- Rolls per trial: {summary.rolls}",
                    f"- Trials: {summary.trials}",
                    f"- Total rolls: {summary.total_rolls}",
                    f"- Rarity counts: {summary.rarity_counts}",
                    f"- Observed probabilities: {summary.observed_probabilities}",
                    f"- Theoretical pick probabilities: {summary.theoretical_pick_probabilities}",
                    f"- Theoretical reach probabilities: {summary.theoretical_probabilities}",
                    "",
                ]
            )
        lines.extend(
            [
                "## Events",
                "",
                f"- Recorded high-rarity events: {len(result.events)}",
                "",
            ]
        )
        return "\n".join(lines)
