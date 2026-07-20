from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from igess.fish_rng import (
    FishRngConfig,
    FishRngSimulator,
    map_strength_to_fish_luck,
)


CONFIG = Path("projects/fish-rng/gdd-example.json")


def _small_config(tmp_path: Path, **updates) -> Path:
    payload = json.loads(CONFIG.read_text(encoding="utf-8"))
    payload.update({"throws": 10000, "sample_throw_count": 3})
    payload.update(updates)
    path = tmp_path / "fish-rng.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_gdd_config_loads_mutually_exclusive_bonus_and_conditional_mutations():
    config = FishRngConfig.load(CONFIG)

    assert config.cycle_seconds == 30
    assert config.strength == 100
    assert config.regular_luck_multiplier == 1
    assert config.fish_luck == pytest.approx(5.92652752)
    assert config.trash_luck == 20
    assert len(config.strength_luck_pools) == 13
    assert [row.result_type for row in config.bonus_results] == [
        "no_bonus",
        "mutation",
        "luck_double",
    ]
    assert sum(row.weight for row in config.mutations) == 100000
    assert config.max_bonus_layers == 4


def test_strength_maps_directly_by_log_progress_smoothstep_and_luck_lerp():
    config = FishRngConfig.load(CONFIG)
    pools = config.strength_luck_pools

    minimum = map_strength_to_fish_luck(-10, pools)
    first_cap = map_strength_to_fish_luck(50, pools)
    second_start = map_strength_to_fish_luck(50.000001, pools)
    second_cap = map_strength_to_fish_luck(2000, pools)
    maximum = map_strength_to_fish_luck(10**20, pools)

    assert minimum.clamped_strength == 1
    assert minimum.pool_id == 1
    assert minimum.fish_luck == 1
    assert first_cap.pool_id == 1
    assert first_cap.fish_luck == 5
    assert second_start.pool_id == 2
    assert second_start.fish_luck == pytest.approx(5, abs=1e-12)
    assert second_cap.pool_id == 2
    assert second_cap.fish_luck == 15
    assert maximum.clamped_strength == 30000000000
    assert maximum.fish_luck == 1500


def test_strength_pool_midpoint_uses_geometric_strength_midpoint():
    config = FishRngConfig.load(CONFIG)

    mapping = map_strength_to_fish_luck(
        (2000 * 30000) ** 0.5,
        config.strength_luck_pools,
        regular_luck_multiplier=1.2,
    )

    assert mapping.pool_id == 3
    assert mapping.log_progress == pytest.approx(0.5)
    assert mapping.smooth_progress == pytest.approx(0.5)
    assert mapping.base_fish_luck == pytest.approx(22.5)
    assert mapping.fish_luck == pytest.approx(27)


def test_strength_pool_validation_rejects_luck_discontinuity(tmp_path):
    payload = json.loads(CONFIG.read_text(encoding="utf-8"))
    payload["strength_luck_pools"][1]["start_luck"] = "6"
    path = tmp_path / "broken.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="continuous Luck endpoints"):
        FishRngConfig.load(path)


def test_gdd_boundary_selection_disables_mutation_after_first_hit():
    simulator = FishRngSimulator(FishRngConfig.load(CONFIG))

    assert simulator._select_bonus(3.78, True).result_type == "no_bonus"
    assert simulator._select_bonus(3.787878787878788, True).result_type == "mutation"
    assert simulator._select_bonus(9.999, True).result_type == "mutation"
    assert simulator._select_bonus(10, True).result_type == "luck_double"
    assert simulator._select_bonus(9.999, False).result_type == "no_bonus"
    assert simulator._select_bonus(10, False).result_type == "luck_double"


def test_simulation_matches_gdd_bonus_targets_and_independent_streams(tmp_path):
    config = FishRngConfig.load(_small_config(tmp_path, throws=200000))
    result = FishRngSimulator(config).run().summary
    bonus = result["bonus"]

    assert result["fish_luck"] == pytest.approx(5.92652752)
    assert result["strength_luck_mapping"]["pool_id"] == 2
    assert bonus["first_layer_observed"]["no_bonus"] == pytest.approx(0.736, abs=0.004)
    assert bonus["first_layer_observed"]["mutation"] == pytest.approx(0.164, abs=0.004)
    assert bonus["first_layer_observed"]["luck_double"] == pytest.approx(0.1, abs=0.003)
    assert bonus["any_mutation_observed"] == pytest.approx(
        bonus["any_mutation_theoretical"], abs=0.004
    )
    assert bonus["any_luck_double_observed"] == pytest.approx(
        bonus["any_luck_double_theoretical"], abs=0.004
    )
    assert bonus["expected_luck_multiplier_observed"] == pytest.approx(
        bonus["expected_luck_multiplier_theoretical"], abs=0.006
    )
    assert abs(result["independence"]["log_roll_power_pearson"]) < 0.015
    assert abs(result["independence"]["reward_rank_pearson"]) < 0.015


def test_cli_writes_deterministic_fish_rng_artifacts(tmp_path):
    config = _small_config(tmp_path)
    first = tmp_path / "first"
    second = tmp_path / "second"

    for output in (first, second):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "igess.cli",
                "fish-rng-run",
                "--config",
                str(config),
                "--out",
                str(output),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr

    artifacts = {
        "fish_rng_summary.json",
        "fish_rng_samples.json",
        "fish_rng_analysis.md",
        "fish_rng_manifest.json",
    }
    assert {path.name for path in first.iterdir()} == artifacts
    for name in artifacts:
        assert (first / name).read_bytes() == (second / name).read_bytes()
        assert b"\r\n" not in (first / name).read_bytes()
