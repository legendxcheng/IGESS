from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
import json
from pathlib import Path

import pytest
import yaml

from fish_test_support import _snapshot
from igess.builder import ModelBuilder
from igess.cli import main
from igess.fish_simulator import FishEconomySimulator
from igess.loader import ConfigLoader
from igess.numbers import SimNumber
from igess.paid_reporting import compare_milestones, milestone_times
from igess.payments import PaymentExperiment
from igess.schema import ActivityOutputRow, ActivityRow
from igess.simulator import Simulator
from igess.workflows import WorkflowService


def experiment_payload():
    return {
        "schema_version": 1, "data_status": "example", "source": "test fixture",
        "currency": "TEST", "profile": "casual", "scenarios": ["day_1_progression"],
        "products": {"pack": {"price": "0.10", "grants": {"fish": "10"}, "multipliers": {"active": "2"}, "duration_seconds": 4}},
        "plans": {"paid": {"purchases": [{"at_seconds": 3, "product_id": "pack"}]}},
    }


def activity_model():
    model = ModelBuilder.build(ConfigLoader.load("examples/shelldiver_v0/economy.yaml", "examples/shelldiver_v0/luban_exports"))
    model.generators = {}
    model.upgrades = {}
    model.milestones = {}
    model.prestige_layers = {}
    model.constants = {}
    model.activities = {"work": ActivityRow("work", "Work", "active")}
    model.activity_outputs = {"output": ActivityOutputRow("output", "work", "fish", "1")}
    profile = model.player_profiles["casual"]
    profile.source_efficiency = {"active": SimNumber.one()}
    profile.activity_weights = {"work": SimNumber.one()}
    model.session_patterns[profile.session_pattern] = {}
    model.scenarios["day_1_progression"] = replace(model.scenarios["day_1_progression"], duration_hours=10 / 3600, record_interval_seconds=1, profiles=["casual"])
    return model


@pytest.mark.parametrize("mode", ["tick", "analytic"])
def test_generic_purchase_grant_and_expiry_are_exact(mode):
    model = activity_model()
    model.scenarios["day_1_progression"].time_mode = mode
    model.payment_plan = PaymentExperiment.from_mapping(experiment_payload()).plans[1]
    run = Simulator(model).run_scenario("day_1_progression")
    rows = {row.time_seconds: row for row in run.timeline}
    assert rows[2].resources["fish"] == "2"
    assert rows[3].resources["fish"] == "13"
    assert rows[7].resources["fish"] == "21"
    assert rows[10].resources["fish"] == "24"
    assert rows[3].total_cps == "2"
    assert rows[7].total_cps == "1"
    assert [(event.kind, event.time_seconds) for event in run.events if event.kind.startswith("paid_")] == [("paid_purchase", 3), ("paid_entitlement_expired", 7)]
    assert model.player_profiles["casual"].source_efficiency == {"active": SimNumber.one()}


def test_repeated_purchases_stack_and_money_is_exact():
    data = experiment_payload()
    data["plans"]["paid"]["purchases"] += [{"at_seconds": 5, "product_id": "pack", "quantity": 2}]
    plan = PaymentExperiment.from_mapping(data).plans[1]
    assert plan.spent_at(5) == Decimal("0.30")
    assert plan.multipliers_at(5)["active"] == SimNumber.parse(8)
    assert plan.multipliers_at(7)["active"] == SimNumber.parse(4)
    assert plan.multipliers_at(9) == {}
    assert plan.grants_at(5)["fish"] == SimNumber.parse(20)


def test_unknown_resources_and_misaligned_generic_times_fail_before_running():
    data = experiment_payload()
    data["products"]["pack"]["grants"] = {"typo_resource": "1"}
    plan = PaymentExperiment.from_mapping(data).plans[1]
    with pytest.raises(ValueError, match="unknown grant resources"):
        plan.validate_model(activity_model(), "casual")
    model = activity_model()
    model.config = replace(model.config, tick_seconds=2)
    with pytest.raises(ValueError, match="align"):
        PaymentExperiment.from_mapping(experiment_payload()).plans[1].validate_model(model, "casual")


def test_yaml_rejects_duplicate_prices_and_precise_spending_is_preserved(tmp_path):
    path = tmp_path / "duplicate.yaml"
    path.write_text("schema_version: 1\nschema_version: 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unique"):
        PaymentExperiment.read(path)
    data = experiment_payload()
    data["products"]["pack"]["price"] = "1000000000000000000000000000000.01"
    data["plans"]["paid"]["purchases"][0]["quantity"] = 3
    plan = PaymentExperiment.from_mapping(data).plans[1]
    assert plan.spent_at(3) == Decimal("3000000000000000000000000000000.03")


def test_generic_zero_purchase_matches_existing_simulation():
    model = activity_model()
    ordinary = Simulator(model).run_scenario("day_1_progression")
    model.payment_plan = PaymentExperiment.from_mapping(experiment_payload()).plans[0]
    assert Simulator(model).run_scenario("day_1_progression") == ordinary


@pytest.mark.parametrize("change,match", [
    (lambda d: d.update(unknown=True), "unknown fields"),
    (lambda d: d["products"]["pack"].update(price="NaN"), "positive finite"),
    (lambda d: d["products"]["pack"].update(price=-1), "positive finite"),
    (lambda d: d["products"]["pack"].update(duration_seconds=True), "integer"),
    (lambda d: d["plans"]["paid"]["purchases"][0].update(product_id="missing"), "Unknown product"),
    (lambda d: d["plans"]["paid"]["purchases"][0].update(at_seconds=-1), "integer"),
    (lambda d: d["plans"]["paid"]["purchases"][0].update(quantity=0), "integer"),
    (lambda d: d["plans"].update(free={"purchases": []}), "reserved"),
])
def test_invalid_experiment_rejected(change, match):
    data = experiment_payload()
    change(data)
    with pytest.raises(ValueError, match=match):
        PaymentExperiment.from_mapping(data)


def test_missing_milestones_do_not_become_zero_or_saved_time():
    rows = compare_milestones({"a": 100, "b": 0}, {"b": 0, "c": 50})
    assert rows[0]["status"] == "free_only"
    assert rows[0]["paid_seconds"] is None
    assert rows[0]["saved_wall_seconds"] is None
    assert rows[1]["saved_wall_seconds"] == 0
    assert rows[2]["status"] == "paid_only"
    assert rows[2]["saved_wall_seconds"] is None
    assert compare_milestones({"a": 86410}, {"a": 90}, {"daily_online_seconds": 100})[0]["saved_active_seconds"] == 20


def test_torpedo_purchase_and_skipped_tiers_count_as_reached():
    free = milestone_times([{"kind": "torpedo_purchased", "time_seconds": 100, "details": {"torpedo_id_after": "2"}}])
    paid = milestone_times([{"kind": "torpedo_purchased", "time_seconds": 50, "details": {"torpedo_id_after": "3"}}])
    rows = compare_milestones(free, paid)
    assert rows[0]["milestone"] == "torpedo:2"
    assert rows[0]["saved_wall_seconds"] == 50
    assert rows[1]["status"] == "paid_only"


def fish_model():
    model = activity_model()
    model.config = replace(model.config, engine_id="fish")
    model.engine_settings = {"active_throw": {"initial_strength": "10", "interval_seconds": 1, "regular_luck_multiplier": "1", "bonus_base_luck": "1", "max_bonus_layers": 4}}
    profile = model.player_profiles["casual"]
    profile.behavior_weights = {"manual_throw": SimNumber.one()}
    profile.behavior_durations = {"manual_throw": {"type": "fixed", "seconds": 10}}
    profile.behavior_target_policies = {}
    data = experiment_payload()
    data["products"]["pack"]["grants"] = {"strength": "100", "money": "25"}
    data["products"]["pack"]["multipliers"] = {"fish_hall_money": "2"}
    model.payment_plan = PaymentExperiment.from_mapping(data).plans[1]
    return model


@pytest.mark.parametrize("split", [2, 3, 5, 7, 9])
def test_fish_resume_does_not_repeat_purchase_or_redraw_active_behavior(tmp_path, split):
    model = fish_model()
    data = _snapshot(tmp_path)
    simulator = FishEconomySimulator(model, data, model_digest="sha256:" + "a" * 64)
    full = simulator.run_scenario("day_1_progression")
    first = simulator.run_scenario("day_1_progression", until_seconds=split)
    second = simulator.run_scenario("day_1_progression", first.checkpoint)
    assert full.checkpoint.to_dict() == second.checkpoint.to_dict()
    merged = [event for event in first.result.events + second.result.events if event.kind != "fish_engine_ready"]
    assert merged == [event for event in full.result.events if event.kind != "fish_engine_ready"]
    assert sum(event.kind == "paid_purchase" for event in merged) == 1
    assert full.checkpoint.engine_state["statistics"]["totalThrows"] == 1
    assert Decimal(full.result.timeline[-1].resources["strength"]) == 110
    assert Decimal(full.result.timeline[-1].resources["money"]) == 25


def test_zero_purchase_fish_matches_existing_simulation(tmp_path):
    model = fish_model()
    model.payment_plan = PaymentExperiment.from_mapping(experiment_payload()).plans[0]
    data = _snapshot(tmp_path)
    baseline = FishEconomySimulator(model, data, model_digest="sha256:" + "a" * 64).run_scenario("day_1_progression")
    model.payment_plan = None
    old = FishEconomySimulator(model, data, model_digest="sha256:" + "a" * 64).run_scenario("day_1_progression")
    assert baseline.result == old.result
    assert baseline.checkpoint == old.checkpoint


def test_fish_offline_bonus_settles_at_purchase_and_expiry(tmp_path):
    model = fish_model()
    model.scenarios["day_1_progression"].duration_hours = 12 / 3600
    profile = model.player_profiles["casual"]
    profile.behavior_durations = {"manual_throw": {"type": "fixed", "seconds": 1}}
    model.session_patterns[profile.session_pattern] = {"daily_online_seconds": 5}
    payload = experiment_payload()
    payload["products"]["pack"] = {"price": "1", "multipliers": {"fish_hall_money": "2"}, "duration_seconds": 4}
    payload["plans"]["paid"]["purchases"][0]["at_seconds"] = 6
    model.payment_plan = PaymentExperiment.from_mapping(payload).plans[1]
    snapshot = _snapshot(tmp_path)
    paid = FishEconomySimulator(model, snapshot, model_digest="sha256:" + "b" * 64).run_scenario("day_1_progression")
    model.payment_plan = None
    free = FishEconomySimulator(model, snapshot, model_digest="sha256:" + "b" * 64).run_scenario("day_1_progression")
    assert paid.checkpoint.next_throw_id == free.checkpoint.next_throw_id == 5
    cps = Decimal(free.result.timeline[-1].total_cps)
    difference = Decimal(paid.result.timeline[-1].resources["money"]) - Decimal(free.result.timeline[-1].resources["money"])
    assert difference == cps * 4 * Decimal("0.5")
    assert paid.result.timeline[-1].total_cps == free.result.timeline[-1].total_cps


def test_fish_training_bonus_during_active_behavior(tmp_path):
    from igess.behavior import BehaviorRuntimeState
    from igess.fish_hall import FishHallDataAdapter
    from igess.fish_production import FishProductionRuntime
    from igess.fish_state import FishCheckpointCodec, OwnedBarbell, PlayerState

    model = fish_model()
    profile = model.player_profiles["casual"]
    profile.behavior_weights = {"exercise_barbell": SimNumber.one()}
    profile.behavior_durations = {"exercise_barbell": {"type": "fixed", "seconds": 10}}
    payload = experiment_payload()
    payload["products"]["pack"] = {"price": "1", "multipliers": {"barbell_strength": "2"}, "duration_seconds": 4}
    model.payment_plan = PaymentExperiment.from_mapping(payload).plans[1]
    snapshot = _snapshot(tmp_path)
    state = PlayerState.new(initial_torpedo_id=1, initial_trash_man_realm_id=1)
    state.barbell.owned = [OwnedBarbell(1, 1)]
    state.barbell.equipped_id = 1
    digest = "sha256:" + "c" * 64
    checkpoint = FishCheckpointCodec.new(
        state, model_digest=digest, scenario_id="day_1_progression", profile_id="casual",
        root_random_seed=model.config.random_seed,
        behavior_state=BehaviorRuntimeState().to_dict(), engine_runtime_state=FishProductionRuntime().to_dict(),
        context=FishHallDataAdapter(snapshot).validation_context(),
    )
    simulator = FishEconomySimulator(model, snapshot, model_digest=digest)
    full = simulator.run_scenario("day_1_progression", checkpoint)
    first = simulator.run_scenario("day_1_progression", checkpoint, until_seconds=5)
    resumed = simulator.run_scenario("day_1_progression", first.checkpoint)
    assert full.checkpoint == resumed.checkpoint
    # Fixture barbell gives 2 strength/s: 6 ordinary seconds + 4 doubled seconds.
    assert Decimal(full.result.timeline[-1].resources["strength"]) == 28


def test_fish_paid_formal_artifacts_include_progression_and_checkpoint(tmp_path):
    from igess.engines import FishEngineAdapter, PreparedEngine
    from igess.paid_experiments import execute_paid_experiment
    from igess.run_registry import RunRegistry

    model = fish_model()
    plan = model.payment_plan
    model.payment_plan = None
    baseline = replace(plan, id="free", purchases=())
    experiment = PaymentExperiment("casual", ("day_1_progression",), (baseline, plan))
    prepared = PreparedEngine("fish", model, "sha256:" + "d" * 64, domain_model=_snapshot(tmp_path / "data"))
    result = execute_paid_experiment(prepared, FishEngineAdapter(), experiment, RunRegistry(tmp_path / "runs"), tmp_path / "report", tmp_path)
    assert result["status"] == "success"
    assert result["runs"][1]["spent"] == "0.10"
    assert "fish_state" in result["runs"][1]
    assert "system_progression_count" in result["runs"][1]["progression"]
    assert len(result["runs"][1]["purchase_ledger"]) == 1


def test_paid_report_failure_does_not_claim_a_successful_experiment(tmp_path, monkeypatch):
    import igess.formal_run as formal
    from igess.paid_experiments import execute_paid_experiment

    class FailingReports(formal.FormalRunExecutor):
        def __init__(self, *args, **kwargs):
            def fail(*_args):
                raise ValueError("report fixture failure")
            super().__init__(*args, report_writer=fail, **kwargs)

    monkeypatch.setattr("igess.paid_experiments.FormalRunExecutor", FailingReports)
    service = WorkflowService("examples/shelldiver_v0", runs_root=tmp_path / "runs", authoring=False)
    result = service.run_paid_experiment("examples/paid/generic-example.yaml", tmp_path / "report")
    assert result["status"] == "failed"
    assert all(row["status"] == "failed" and "spent" not in row for row in result["runs"])
    assert all((Path(row["run_dir"]) / "timeline.json").exists() for row in result["runs"])


def test_generic_paid_workflow_registers_runs_and_outputs_report(tmp_path):
    service = WorkflowService("examples/shelldiver_v0", runs_root=tmp_path / "runs", authoring=False)
    result = service.run_paid_experiment("examples/paid/generic-example.yaml", tmp_path / "report")
    assert result["status"] == "success"
    assert len(result["runs"]) == 3
    assert {row["plan_id"]: row["spent"] for row in result["runs"]} == {"free": "0", "starter_only": "6.00", "starter_and_boost": "9.00"}
    assert len(service.list_runs()) == 3
    manifests = [json.loads((Path(row["run_dir"]) / "run_manifest.json").read_text()) for row in result["runs"]]
    assert all(item["profiles"] == ["casual"] for item in manifests)
    assert len({item["paid_simulation"]["base_model_digest"] for item in manifests}) == 1
    assert len({item["model_digest"] for item in manifests}) == 3
    page = (tmp_path / "report" / "index.html").read_text(encoding="utf-8")
    assert "示例商品" in page and "购买明细" in page
    assert (tmp_path / "report" / "paid_milestones.csv").exists()
    with pytest.raises(FileExistsError):
        service.run_paid_experiment("examples/paid/generic-example.yaml", tmp_path / "report")


def test_paid_cli_accepts_experiment(tmp_path, monkeypatch):
    # Exercise argument dispatch without writing into the example project's history.
    original = WorkflowService.run_paid_experiment
    def run(service, *args, **kwargs):
        from igess.run_registry import RunRegistry
        service.registry = RunRegistry(tmp_path / "runs")
        return original(service, *args, **kwargs)
    monkeypatch.setattr(WorkflowService, "run_paid_experiment", run)
    assert main(["paid-run", "--project", "examples/shelldiver_v0", "--experiment", "examples/paid/generic-example.yaml", "--out", str(tmp_path / "report")]) == 0
