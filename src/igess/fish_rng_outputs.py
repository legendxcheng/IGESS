from __future__ import annotations

import json
from pathlib import Path

from .fish_rng import FishRngConfig, FishRngSimulationResult


class FishRngOutputWriter:
    ARTIFACTS = (
        "fish_rng_summary.json",
        "fish_rng_samples.json",
        "fish_rng_analysis.md",
        "fish_rng_manifest.json",
    )

    @classmethod
    def write_all(
        cls,
        result: FishRngSimulationResult,
        config: FishRngConfig,
        output_dir: str | Path,
    ) -> None:
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        cls._write_json(output / cls.ARTIFACTS[0], result.summary)
        cls._write_json(output / cls.ARTIFACTS[1], result.samples)
        (output / cls.ARTIFACTS[2]).write_text(
            cls.markdown(result), encoding="utf-8", newline="\n"
        )
        cls._write_json(
            output / cls.ARTIFACTS[3],
            {
                "schema_version": 1,
                "scenario_id": config.scenario_id,
                "random_seed": config.random_seed,
                "throws": config.throws,
                "cycle_seconds": config.cycle_seconds,
                "artifacts": list(cls.ARTIFACTS[:-1]),
            },
        )

    @staticmethod
    def _write_json(path: Path, payload) -> None:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )

    @staticmethod
    def markdown(result: FishRngSimulationResult) -> str:
        summary = result.summary
        bonus = summary["bonus"]
        mapping = summary["strength_luck_mapping"]
        independence = summary["independence"]
        duration_days = summary["represented_play_seconds"] / 86400
        interval_open = "[" if mapping["pool_id"] == 1 else "("
        return "\n".join(
            [
                "# Fish RNG Simulation",
                "",
                f"- Scenario: `{summary['scenario_id']}`",
                f"- Throws: {summary['throws']:,}",
                f"- Cycle: {summary['cycle_seconds']} seconds",
                f"- Represented continuous play: {duration_days:.2f} days",
                f"- Strength: {mapping['input_strength']}",
                f"- Strength pool: {mapping['pool_id']} "
                f"{interval_open}{mapping['interval_min_strength']}.."
                f"{mapping['interval_max_strength']}]",
                f"- strengthUpperBound: "
                f"{mapping['interval_max_strength']} (inclusive)",
                f"- Log progress: {mapping['log_progress']}",
                f"- Smooth progress: {mapping['smooth_progress']}",
                f"- Base Fish Luck: {mapping['base_fish_luck']}",
                f"- Regular Luck multiplier: {mapping['regular_luck_multiplier']}",
                f"- Fish Luck: {summary['fish_luck']}",
                f"- Trash Luck: {summary['trash_luck']}",
                "",
                "## BonusChain validation",
                "",
                f"- First-layer observed: {bonus['first_layer_observed']}",
                f"- First-layer theoretical: {bonus['first_layer_theoretical']}",
                f"- Any mutation: observed {bonus['any_mutation_observed']}, "
                f"theoretical {bonus['any_mutation_theoretical']}",
                f"- Any Luck ×2: observed {bonus['any_luck_double_observed']}, "
                f"theoretical {bonus['any_luck_double_theoretical']}",
                f"- E[FinalFishLuck / FishLuck]: observed "
                f"{bonus['expected_luck_multiplier_observed']}, theoretical "
                f"{bonus['expected_luck_multiplier_theoretical']}",
                f"- Layer reach observed: {bonus['layer_reach_observed']}",
                f"- Layer reach theoretical: {bonus['layer_reach_theoretical']}",
                "",
                "## Reward distributions",
                "",
                f"- Fish: {summary['fish']['probabilities']}",
                f"- Trash: {summary['trash']['probabilities']}",
                f"- Mutation per throw: "
                f"{summary['mutations']['probabilities_per_throw']}",
                "",
                "## Independence",
                "",
                f"- Pearson correlation of log RollPower: "
                f"{independence['log_roll_power_pearson']}",
                f"- Pearson correlation of selected reward rank: "
                f"{independence['reward_rank_pearson']}",
                "",
            ]
        )
