import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from igess.builder import ModelBuilder
from igess.linter import ConfigError, ConfigLinter
from igess.loader import ConfigLoader
from igess.numbers import SimNumber


CONFIG = Path("examples/shelldiver_v0/economy.yaml")
TABLES = Path("examples/shelldiver_v0/luban_exports")


def _write_rng_config(tmp_path, mutator=None):
    data = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    data["player_profiles"]["optimizer"]["luck"] = 5.65
    data["rng_tables"] = {
        "aura_roll": {
            "algorithm": "rarity_score",
            "rarities": {
                "common": 1,
                "rare": 10,
                "epic": 100,
                "legendary": 1000,
                "mythic": 10000,
                "secret": 1000000,
            },
        }
    }
    data["rng_scenarios"] = {
        "aura_baseline": {
            "table": "aura_roll",
            "rolls": 1000,
            "trials": 5,
            "profiles": ["optimizer"],
            "event_threshold": "mythic",
        }
    }
    if mutator is not None:
        mutator(data)
    path = tmp_path / "economy.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8", newline="\n")
    return path


def test_rng_config_loads_tables_scenarios_and_profile_luck(tmp_path):
    config = _write_rng_config(tmp_path)

    model = ModelBuilder.build(ConfigLoader.load(config, TABLES))

    assert model.player_profiles["optimizer"].luck == 5.65
    assert model.rng_tables["aura_roll"].algorithm == "rarity_score"
    assert [rarity.id for rarity in model.rng_tables["aura_roll"].rarities] == [
        "common",
        "rare",
        "epic",
        "legendary",
        "mythic",
        "secret",
    ]
    assert model.rng_tables["aura_roll"].rarities[-1].denominator == 1000000
    assert model.rng_scenarios["aura_baseline"].table == "aura_roll"
    assert model.rng_scenarios["aura_baseline"].rolls == 1000
    assert model.rng_scenarios["aura_baseline"].trials == 5
    assert model.rng_scenarios["aura_baseline"].event_threshold == "mythic"


def test_rng_linter_rejects_unknown_algorithm(tmp_path):
    config = _write_rng_config(
        tmp_path,
        lambda data: data["rng_tables"]["aura_roll"].update({"algorithm": "weighted_pool"}),
    )

    with pytest.raises(ConfigError, match="rng_table 'aura_roll' unknown algorithm"):
        ConfigLinter.validate(ConfigLoader.load(config, TABLES))


def test_rng_linter_rejects_non_positive_denominator(tmp_path):
    config = _write_rng_config(
        tmp_path,
        lambda data: data["rng_tables"]["aura_roll"]["rarities"].update({"broken": 0}),
    )

    with pytest.raises(ConfigError, match="rng_table 'aura_roll' rarity 'broken'"):
        ConfigLinter.validate(ConfigLoader.load(config, TABLES))


def test_rarity_score_selects_highest_reached_rarity_by_log_power(tmp_path):
    from igess.rng import select_rarity_by_log_power

    config = _write_rng_config(tmp_path)
    model = ModelBuilder.build(ConfigLoader.load(config, TABLES))

    rarity = select_rarity_by_log_power(
        model.rng_tables["aura_roll"].rarities,
        luck=model.player_profiles["optimizer"].luck,
        u=0.0002,
    )

    assert rarity.id == "mythic"
    assert rarity.denominator == 10000


def test_rarity_probability_is_luck_over_denominator_clamped_to_one():
    from igess.rng import rarity_probability

    assert rarity_probability(SimNumber.parse("5.65"), SimNumber.parse("10")) == SimNumber.parse(
        "0.565"
    )
    assert rarity_probability(SimNumber.parse("5.65"), SimNumber.parse("1")) == SimNumber.one()


def test_rng_simulator_is_deterministic_and_records_first_hits(tmp_path):
    from igess.rng import RngSimulator

    def make_epic_guaranteed(data):
        data["rng_tables"]["aura_roll"]["rarities"] = {
            "common": 1,
            "rare": 2,
            "epic": 5,
            "secret": 1000000,
        }
        data["rng_scenarios"]["aura_baseline"].update(
            {"rolls": 20, "trials": 3, "event_threshold": "epic"}
        )

    config = _write_rng_config(tmp_path, make_epic_guaranteed)
    model = ModelBuilder.build(ConfigLoader.load(config, TABLES))

    first = RngSimulator(model).run_scenario("aura_baseline")
    second = RngSimulator(model).run_scenario("aura_baseline")

    assert [row.to_ordered_dict() for row in first.summaries] == [
        row.to_ordered_dict() for row in second.summaries
    ]
    assert [row.to_ordered_dict() for row in first.distribution] == [
        row.to_ordered_dict() for row in second.distribution
    ]
    assert [event.to_ordered_dict() for event in first.events] == [
        event.to_ordered_dict() for event in second.events
    ]
    summary = first.summaries[0]
    assert summary.profile_id == "optimizer"
    assert summary.rarity_counts["epic"] == 60
    assert summary.theoretical_probabilities["epic"] == "1"
    assert summary.theoretical_pick_probabilities["common"] == "0"
    assert summary.theoretical_pick_probabilities["epic"] == "0.99999435"
    assert summary.theoretical_pick_probabilities["secret"] == "0.00000565"
    assert summary.observed_probabilities["epic"] == "1"
    assert len(first.distribution) == 3
    assert all(row.best_rarity == "epic" for row in first.distribution)
    assert all(row.first_hits["epic"] == 1 for row in first.distribution)
    assert len(first.events) == 60


def test_rng_cli_writes_deterministic_artifacts(tmp_path):
    config = _write_rng_config(
        tmp_path,
        lambda data: data["rng_scenarios"]["aura_baseline"].update(
            {"rolls": 25, "trials": 2, "event_threshold": "legendary"}
        ),
    )
    first_out = tmp_path / "first"
    second_out = tmp_path / "second"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path.cwd() / "src")

    for output_dir in (first_out, second_out):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "igess.cli",
                "rng-run",
                "--config",
                str(config),
                "--scenario",
                "aura_baseline",
                "--out",
                str(output_dir),
            ],
            check=False,
            capture_output=True,
            cwd=Path.cwd(),
            env=env,
            text=True,
        )
        assert result.returncode == 0, result.stderr

    artifacts = [
        "rng_summary.json",
        "rng_distribution.csv",
        "rng_events.json",
        "rng_events.csv",
        "rng_analysis.md",
        "rng_manifest.json",
    ]
    for artifact in artifacts:
        first_bytes = (first_out / artifact).read_bytes()
        second_bytes = (second_out / artifact).read_bytes()
        assert first_bytes == second_bytes, artifact
        assert b"\r\n" not in first_bytes, artifact

    summary = json.loads((first_out / "rng_summary.json").read_text(encoding="utf-8"))
    assert summary[0]["scenario_id"] == "aura_baseline"
    assert summary[0]["profile_id"] == "optimizer"
    manifest = json.loads((first_out / "rng_manifest.json").read_text(encoding="utf-8"))
    assert manifest["artifacts"] == artifacts[:-1]
