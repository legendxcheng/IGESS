from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from igess.fish_rng import (
    FishRngConfig,
    FishRngSimulator,
    map_strength_to_fish_luck,
)
from igess.fish_throw import (
    StrengthLuckPool,
    ThresholdItem,
    ThrowInput,
    ThrowRules,
    resolve_throw,
)


CONFIG = Path("projects/fish-rng/gdd-example.json")


def _small_config(tmp_path: Path, **updates) -> Path:
    payload = json.loads(CONFIG.read_text(encoding="utf-8"))
    payload.update({"throws": 10000, "sample_throw_count": 3})
    payload.update(updates)
    path = tmp_path / "fish-rng.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _throw_rules(config: FishRngConfig) -> ThrowRules:
    return ThrowRules(
        strength_luck_pools=config.strength_luck_pools,
        bonus_base_luck=config.bonus_base_luck,
        max_bonus_layers=config.max_bonus_layers,
        bonus_results=config.bonus_results,
        mutations=config.mutations,
        fish_pool=config.fish_pool,
        trash_pool=config.trash_pool,
    )


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


def test_strength_upper_bound_is_the_inclusive_region_endpoint():
    pools = (
        StrengthLuckPool(1, "pool-1", 50, 1, 3),
        StrengthLuckPool(2, "pool-2", 2000, 5, 8),
    )

    first_endpoint = map_strength_to_fish_luck(50, pools)
    above_first_endpoint = map_strength_to_fish_luck(50.000001, pools)
    second_midpoint = map_strength_to_fish_luck((50 * 2000) ** 0.5, pools)
    second_endpoint = map_strength_to_fish_luck(2000, pools)

    assert first_endpoint.pool_id == 1
    assert first_endpoint.interval_min_strength == 1
    assert first_endpoint.interval_max_strength == 50
    assert first_endpoint.base_fish_luck == 3
    assert above_first_endpoint.pool_id == 2
    assert above_first_endpoint.base_fish_luck == pytest.approx(5, abs=1e-12)
    assert second_midpoint.log_progress == pytest.approx(0.5)
    assert second_midpoint.smooth_progress == pytest.approx(0.5)
    assert second_midpoint.base_fish_luck == pytest.approx(6.5)
    assert second_endpoint.pool_id == 2
    assert second_endpoint.base_fish_luck == 8


def test_strength_is_clamped_to_global_minimum_and_last_endpoint():
    config = FishRngConfig.load(CONFIG)
    pools = config.strength_luck_pools

    negative = map_strength_to_fish_luck(-50, pools)
    maximum = map_strength_to_fish_luck(10**20, pools)

    assert negative.clamped_strength == 1
    assert negative.base_fish_luck == 1
    assert maximum.clamped_strength == 30000000000
    assert maximum.pool_id == 13
    assert maximum.base_fish_luck == 1500


def test_resolve_throw_uses_strength_luck_and_stable_independent_domains():
    config = FishRngConfig.load(CONFIG)
    rules = _throw_rules(config)
    throw = ThrowInput(
        root_random_seed=20260722,
        throw_id=17,
        strength=10**20,
        regular_luck_multiplier=1.2,
        trash_luck=config.trash_luck,
    )

    outcome = resolve_throw(throw, rules)
    replay = resolve_throw(throw, rules)
    changed_fish_pool = replace(
        rules,
        fish_pool=(ThresholdItem("replacement", "replacement", 1),),
    )
    fish_variant = resolve_throw(throw, changed_fish_pool)

    assert replay == outcome
    assert outcome.strength_luck.clamped_strength == 30000000000
    assert outcome.strength_luck.base_fish_luck == 1500
    assert outcome.strength_luck.fish_luck == pytest.approx(1800)
    assert outcome.fish_reward is not None
    assert outcome.trash_reward is not None
    assert fish_variant.fish_reward.id == "replacement"
    assert fish_variant.strength_luck == outcome.strength_luck
    assert fish_variant.bonus_events == outcome.bonus_events
    assert fish_variant.mutation == outcome.mutation
    assert fish_variant.trash_roll_power == outcome.trash_roll_power
    assert fish_variant.trash_reward == outcome.trash_reward


def test_strength_pool_validation_preserves_luck_discontinuity(tmp_path):
    payload = json.loads(CONFIG.read_text(encoding="utf-8"))
    payload["strength_luck_pools"][1]["start_luck"] = "6"
    path = tmp_path / "broken.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    config = FishRngConfig.load(path)

    at_first_endpoint = map_strength_to_fish_luck(50, config.strength_luck_pools)
    above_first_endpoint = map_strength_to_fish_luck(
        50.000001, config.strength_luck_pools
    )
    assert at_first_endpoint.base_fish_luck == 5
    assert above_first_endpoint.base_fish_luck == pytest.approx(6, abs=1e-12)


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
