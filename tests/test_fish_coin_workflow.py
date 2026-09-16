from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import yaml
import pytest

from fish_test_support import _snapshot
from igess.engines import EngineRegistry
from igess.builder import ModelBuilder
from igess.fish_behavior_simulator import FishBehaviorSimulator
from igess.fish_data import FishDataError
from igess.loader import ConfigLoader
from igess.numbers import SimNumber
from igess.workflows import WorkflowService


class CoinScenarioProvider:
    def __init__(self, root: Path):
        snapshot = _snapshot(root)
        snapshot.table("tbbarbell")[0].price = 10000
        snapshot.table("tbbarbell")[1].price = 20000
        # Unused beast fields must not be required by the ordinary-fish scenario.
        beast = SimpleNamespace(id=2009, rarityId=20, productionMode="best_hall_fish")
        self.snapshot = replace(snapshot, tables={
            **snapshot.tables, "tbfish": (*snapshot.table("tbfish"), beast),
        })

    def load_tables(self, data_root, required_tables):
        return self.snapshot.tables

    def apply_overrides(self, tables, assignments):
        raise AssertionError("This scenario uses no overrides")


def test_coin_workflow_retains_ledger_and_excludes_beasts(tmp_path: Path) -> None:
    provider = CoinScenarioProvider(tmp_path)
    data_root = tmp_path / "data"
    data_root.mkdir()
    for name in provider.snapshot.tables:
        (data_root / f"{name}.json").write_text("{}", encoding="utf-8")
    config = yaml.safe_load(Path("projects/fish/economy.yaml").read_text(encoding="utf-8"))
    config["engine"]["data_root"] = str(data_root)
    config["engine"]["production_data"] = False
    profile = config["player_profiles"]["default"]
    profile["behavior_weights"] = {"manual_throw": "1", "upgrade_fish": "1", "synthesize_barbell": "100"}
    profile["behavior_target_policies"] = {
        "upgrade_fish": "deployed_quality_lowest_level", "synthesize_barbell": "cheapest_improvement",
    }
    profile["behavior_durations"]["manual_throw"]["seconds"] = 1
    config["scenarios"]["smoke"]["duration_hours"] = str(120 / 3600)
    config["scenarios"]["smoke"]["outputs"].append("compact_event_details")
    config_path = tmp_path / "economy.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    service = WorkflowService(
        ".", runs_root=tmp_path / "runs",
        engine_registry=EngineRegistry.standard(fish_luban_provider=provider),
    )
    run = service.run_scenario(config_path, Path("projects/fish/luban_exports"), "smoke")
    assert run.status == "success", run.message
    assert run.report_index.is_file()
    events = json.loads((run.output_dir / "events.json").read_text(encoding="utf-8"))
    upgrades = [event for event in events if event["kind"] == "fish_upgraded"]
    assert upgrades
    for event in upgrades:
        details = event["details"]
        assert details["fish_upgrade_price_resource"] == "money"
        assert "money_before_fish_upgrade" in details
        assert "money_after_fish_upgrade" in details
        assert "fish_upgrade_hall_income_delta" in details
        assert "material_after_fish_upgrade" not in details
    caught = [event["details"]["fish_id"] for event in events if event["kind"] == "fish_throw_resolved"]
    assert caught and set(caught) <= {"101", "201"}
    manifest = json.loads((run.output_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["fish_simulation_scope"] == "ordinary_fish_only"
    assert manifest["model_digest"] == run.model_digest
    report = json.loads((run.report_index.parent / "report_data.json").read_text(encoding="utf-8"))
    investment = report["fish_progression"]["investment"]
    assert investment["scope"] == "ordinary_fish_only"
    summary = investment["profiles"]["default"]
    assert summary["upgrade_count"] == len(upgrades)
    assert summary["coin_spent"]["chart_value"] > 0
    assert summary["effective_upgrade_percent"]["chart_value"] == 100


@pytest.mark.parametrize("mutate", [False, True])
def test_coin_upgrade_replays_from_mid_action_checkpoint(tmp_path: Path, mutate: bool) -> None:
    snapshot = CoinScenarioProvider(tmp_path).snapshot
    model = ModelBuilder.build(ConfigLoader.load("projects/fish/economy.yaml", "projects/fish/luban_exports"))
    model.scenarios["smoke"].duration_hours = 120 / 3600
    profile = model.player_profiles["default"]
    profile.behavior_weights = {"manual_throw": SimNumber.one(), "upgrade_fish": SimNumber.one()}
    profile.behavior_durations["manual_throw"] = {"type": "fixed", "seconds": 1}
    digest = "sha256:" + "c" * 64
    simulator = FishBehaviorSimulator(model, snapshot, model_digest=digest, _mutate_state=mutate)
    continuous, expected = simulator.run_scenario("smoke")
    upgrade = next(event for event in continuous.events
                   if event.kind == "fish_behavior_started" and event.details["behavior_id"] == "upgrade_fish")
    first, checkpoint = FishBehaviorSimulator(model, snapshot, model_digest=digest, _mutate_state=mutate).run_scenario(
        "smoke", until_seconds=upgrade.time_seconds + 1,
    )
    assert checkpoint.behavior_state["active"]["behavior_id"] == "upgrade_fish"
    assert not any(event.kind == "fish_upgraded" for event in first.events)
    resumed, actual = FishBehaviorSimulator(model, snapshot, model_digest=digest, _mutate_state=mutate).run_scenario("smoke", checkpoint)
    assert actual == expected
    assert [e for e in first.events + resumed.events if e.kind != "fish_engine_ready"] == [
        e for e in continuous.events if e.kind != "fish_engine_ready"
    ]


def test_beast_checkpoint_is_rejected_without_rewriting_input(tmp_path: Path) -> None:
    snapshot = CoinScenarioProvider(tmp_path).snapshot
    model = ModelBuilder.build(ConfigLoader.load("projects/fish/economy.yaml", "projects/fish/luban_exports"))
    simulator = FishBehaviorSimulator(model, snapshot, model_digest="sha256:" + "c" * 64)
    model.scenarios["smoke"].duration_hours = 120 / 3600
    model.player_profiles["default"].behavior_weights = {"manual_throw": SimNumber.one()}
    _, checkpoint = simulator.run_scenario("smoke", until_seconds=31)
    checkpoint.engine_state["fish"]["items"][0]["fishId"] = 2009
    original = json.dumps(checkpoint.engine_state, sort_keys=True)
    with pytest.raises(FishDataError, match="beast state is unsupported"):
        simulator.run_scenario("smoke", checkpoint)
    assert json.dumps(checkpoint.engine_state, sort_keys=True) == original
