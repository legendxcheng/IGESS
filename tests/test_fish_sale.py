from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

import pytest

from fish_test_support import _snapshot, _big
from igess.builder import ModelBuilder
from igess.fish_behavior_simulator import FishBehaviorSimulator
from igess.fish_commands import FishCommandError, sell_fish
from igess.fish_hall import FishHallDataAdapter
from igess.fish_sale import FishSalePolicy, sale_targets, SALE_PERIOD_COUNTER
from igess.fish_state import FishInstance, PlayerState
from igess.loader import ConfigLoader
from igess.numbers import SimNumber
from igess.reporting.view_model import _fish_economy_rows


def _stock(hall):
    state = PlayerState.new(initial_torpedo_id=1, initial_strength=50)
    state.fish.items = [
        FishInstance(1, 201, 7, 20, 100, 0),  # low quality, deployed
        FishInstance(2, 101, 7, 10, 100, 0),  # deployed, second quality slot
        FishInstance(3, 101, 2, 1, 100, 0),   # highest quality, undeployed
        FishInstance(4, 201, 2, 3, 100, 0),   # second highest quality, undeployed
        FishInstance(5, 201, 7, 2, 100, 0),   # upgraded but disposable
    ]
    state.fish.next_instance_id = 6
    layout = hall.expected_layout(state)
    for item in state.fish.items:
        item.hall_slot = layout.get(item.instance_id, 0)
    return state


def test_sale_protects_deployed_and_quality_group_but_not_sunk_cost(tmp_path):
    hall = FishHallDataAdapter(_snapshot(tmp_path))
    state = _stock(hall)
    assert sale_targets(state, hall) == (5,)
    # Game command permits any undeployed ordinary fish, even a policy-protected fish.
    before = state.to_dict()
    result = sell_fish(state, (3, 5), hall_adapter=hall)
    assert result.prices == ("150", "80")
    assert result.material_added == SimNumber.parse(230)
    assert result.state.wallet.money == state.wallet.money
    assert result.state.wallet.material.to_sim_number() == SimNumber.parse(230)
    assert result.state.fish.next_instance_id == 6
    assert result.state.statistics == state.statistics
    assert state.to_dict() == before
    assert hall.snapshot(result.state, use_cache=True).deployed_instance_ids == (1, 2)
    # A fresh capture restoring the old length must not revive deleted cache entries.
    result.state.fish.items.extend([
        FishInstance(6, 101, 2, 30, 100, 0), FishInstance(7, 101, 7, 1, 100, 0),
    ])
    result.state.fish.next_instance_id = 8
    cached = hall.apply_cached_layout(result.state)
    assert cached == hall.snapshot(result.state)
    assert 6 in cached.deployed_instance_ids


@pytest.mark.parametrize("ids", [(5, 1), (5, 999), (5, 5), (), (True,), (1.0,)])
def test_invalid_batch_is_atomic(tmp_path, ids):
    hall = FishHallDataAdapter(_snapshot(tmp_path))
    state = _stock(hall)
    before = state.to_dict()
    with pytest.raises(FishCommandError):
        sell_fish(state, ids, hall_adapter=hall)
    assert state.to_dict() == before


def test_beasts_cannot_be_sold(tmp_path):
    snapshot = _snapshot(tmp_path)
    tables = dict(snapshot.tables)
    tables["tbfish"] = (*tables["tbfish"], SimpleNamespace(
        id=999, rarityId=9, productionMode="best_hall_fish", baseMoneyPerSecond=_big(0),
    ))
    hall = FishHallDataAdapter(replace(snapshot, tables=tables))
    state = _stock(hall)
    state.fish.items.append(FishInstance(6, 999, 7, 1, 100, 0))
    state.fish.next_instance_id = 7
    with pytest.raises(FishCommandError, match="beast"):
        sell_fish(state, (5, 6), hall_adapter=hall)
    assert len(state.fish.items) == 6
    assert state.wallet.material.to_sim_number() == 0


def test_quality_ties_and_expansion_change_sale_group(tmp_path):
    hall = FishHallDataAdapter(_snapshot(tmp_path))
    state = _stock(hall)
    # Top X counts instances, and equal quality preserves previous level investment.
    state.fish.items[3].fish_id = 101
    state.fish.items[3].mutation_id = 7
    state.fish.items[3].level = 1
    state.fish.items.append(FishInstance(6, 101, 7, 1, 100, 0))
    state.fish.next_instance_id = 7
    assert sale_targets(state, hall) == (4, 5, 6)
    state.fish_hall.upgrade_level = 1
    assert sale_targets(state, hall) == (5, 6)


def _simulator(tmp_path, *, daily=86400, compact=False, mutate=True, profile_id="default"):
    model = ModelBuilder.build(ConfigLoader.load("projects/fish/economy.yaml", "projects/fish/luban_exports"))
    scenario = model.scenarios["smoke"]
    scenario.duration_hours = 1 if daily == 86400 else 25
    scenario.record_interval_seconds = 300
    scenario.profiles = [profile_id]
    if compact:
        scenario.outputs.append("compact_event_details")
    profile = model.player_profiles[profile_id]
    profile.behavior_weights = {"manual_throw": SimNumber.one(), "sell_fish": SimNumber.one()}
    profile.behavior_durations = {
        "manual_throw": {"type": "fixed", "seconds": 30},
        "sell_fish": {"type": "fixed", "seconds": 3},
    }
    profile.behavior_target_policies = {"sell_fish": "keep_deployed_and_top_quality"}
    model.session_patterns[profile.session_pattern]["daily_online_seconds"] = daily
    return FishBehaviorSimulator(model, _snapshot(tmp_path), model_digest="sha256:" + "a" * 64, _mutate_state=mutate)


@pytest.mark.parametrize("split", [299, 301, 303, 604])
def test_sale_checkpoint_preserves_batch_clock_and_inventory(tmp_path, split):
    simulator = _simulator(tmp_path)
    result, checkpoint = simulator.run_scenario("smoke")
    first, mid = simulator.run_scenario("smoke", until_seconds=split)
    second, resumed = simulator.run_scenario("smoke", mid)
    assert resumed == checkpoint
    keep = lambda events: [event for event in events if event.kind != "fish_engine_ready"]
    assert keep(first.events + second.events) == keep(result.events)
    sales = [event for event in result.events if event.kind == "fish_sold"]
    assert sales[0].time_seconds == 303
    assert all(int(event.details["behavior_duration_seconds"]) == 3 for event in sales)
    caught = checkpoint.engine_state["statistics"]["totalFishCaught"]
    assert len(checkpoint.engine_state["fish"]["items"]) + checkpoint.event_counters["fish_sold_count"] == caught
    assert checkpoint.engine_state["fish"]["nextInstanceId"] == caught + 1
    assert caught > 10  # trusted throw path succeeds after a sale
    if split == 301:
        assert mid.behavior_state["active"]["behavior_id"] == "sell_fish"
        assert mid.event_counters.get("fish_sold_count", 0) == 0


@pytest.mark.parametrize("split", [301, 500, 86401])
def test_sale_defers_across_offline_and_does_not_reset_clock(tmp_path, split):
    simulator = _simulator(tmp_path, daily=302)
    result, checkpoint = simulator.run_scenario("smoke")
    first, mid = simulator.run_scenario("smoke", until_seconds=split)
    second, resumed = simulator.run_scenario("smoke", mid)
    assert checkpoint == resumed
    sales = [event for event in result.events if event.kind == "fish_sold"]
    assert sales[0].time_seconds == 86403
    assert all(event.time_seconds % 86400 <= 302 for event in sales)
    assert [event for event in first.events + second.events if event.kind == "fish_sold"] == sales


def test_copy_and_mutable_loops_and_compact_sale_ledger_agree(tmp_path):
    result, checkpoint = _simulator(tmp_path).run_scenario("smoke")
    copied, copy_checkpoint = _simulator(tmp_path, mutate=False).run_scenario("smoke")
    compact, compact_checkpoint = _simulator(tmp_path, compact=True).run_scenario("smoke")
    assert copied == result
    assert copy_checkpoint == compact_checkpoint == checkpoint
    sale_ledger = lambda run: [{key: value for key, value in event.details.items()
        if key.startswith("fish_sale_") or key.endswith("_fish_sale")}
        for event in run.events if event.kind == "fish_sold"]
    assert sale_ledger(result) == sale_ledger(compact)


def test_paid_profile_does_not_multiply_sale_prices(tmp_path):
    result, _ = _simulator(tmp_path, profile_id="paid_20pct").run_scenario("smoke")
    normal, _ = _simulator(tmp_path).run_scenario("smoke")
    prices = lambda run: [event.details["fish_sale_material_added"] for event in run.events if event.kind == "fish_sold"]
    # RNG is profile-keyed, so directly verify each sold fixture fish's price range.
    allowed = {Decimal(80), Decimal(100), Decimal(120), Decimal(150)}
    import json
    for event in result.events:
        if event.kind == "fish_sold":
            assert {Decimal(value) for value in json.loads(event.details["fish_sale_prices"])} <= allowed
    assert prices(result) and prices(normal)


def test_empty_period_is_skipped_but_insufficient_online_time_remains_due(tmp_path):
    hall = FishHallDataAdapter(_snapshot(tmp_path))
    policy = FishSalePolicy(300)
    counters = {}
    empty = PlayerState.new(initial_torpedo_id=1)
    def candidate(state, at, remaining):
        return policy.due_candidate(state, hall_adapter=hall, active_seconds=at,
            remaining_online_seconds=remaining, duration_seconds=3, counters=counters)
    assert candidate(empty, 300, 100) is None
    assert counters[SALE_PERIOD_COUNTER] == 1
    assert candidate(_stock(hall), 301, 100) is None
    assert candidate(_stock(hall), 600, 2) is None
    assert counters[SALE_PERIOD_COUNTER] == 1
    assert candidate(_stock(hall), 902, 100) is not None


def test_material_chart_counts_sale_and_processing_without_conflating_them():
    events = [{"profile_id": "default", "time_seconds": 303, "kind": "fish_sold", "details": {
        "fish_sale_material_added": "100", "trash_material_added": "6", "fish_hall_money_added": "30",
    }}]
    rates, totals = _fish_economy_rows(events, profile_id="default", active_duration_seconds=600,
        daily_online_seconds=7200, interval_seconds=300)
    assert totals[-1]["resource_acquired_cumulative"]["exact_value"] == "106"
    assert totals[-1]["fish_sale_material_cumulative"]["exact_value"] == "100"
    assert totals[-1]["trash_material_cumulative"]["exact_value"] == "6"
    assert rates[-1]["money_acquired"]["exact_value"] == "30"


@pytest.mark.parametrize("urgent", ["strength_rebirth", "fund_trash_man_breakthrough"])
def test_due_sale_waits_for_rebirth_or_immediate_breakthrough(tmp_path, urgent):
    from igess.fish_state import BigNumberDTO
    simulator = _simulator(tmp_path)
    _, checkpoint = simulator.run_scenario("smoke", until_seconds=300)
    if urgent == "strength_rebirth":
        checkpoint.engine_state["wallet"]["strength"] = BigNumberDTO.from_value(1000).to_dict()
    profile = simulator.model.player_profiles["default"]
    profile.behavior_weights[urgent] = SimNumber.one()
    profile.behavior_durations[urgent] = {"type": "fixed", "seconds": 10}
    result, _ = simulator.run_scenario("smoke", checkpoint, until_seconds=313)
    started = [event.details["behavior_id"] for event in result.events if event.kind == "fish_behavior_started"]
    assert started[:2] == [urgent, "sell_fish"]
    sale = next(event for event in result.events if event.kind == "fish_sold")
    assert sale.time_seconds == 313


def test_due_sale_precedes_normal_purchase(tmp_path):
    simulator = _simulator(tmp_path)
    _, checkpoint = simulator.run_scenario("smoke", until_seconds=300)
    profile = simulator.model.player_profiles["default"]
    profile.behavior_weights["purchase_torpedo"] = SimNumber.parse("1e100")
    profile.behavior_durations["purchase_torpedo"] = {"type": "fixed", "seconds": 10}
    profile.behavior_target_policies["purchase_torpedo"] = "highest_affordable"
    result, _ = simulator.run_scenario("smoke", checkpoint, until_seconds=314)
    started = [event.details["behavior_id"] for event in result.events if event.kind == "fish_behavior_started"]
    assert started[:2] == ["sell_fish", "purchase_torpedo"]


def test_long_action_is_not_interrupted_and_missed_periods_coalesce(tmp_path):
    simulator = _simulator(tmp_path)
    profile = simulator.model.player_profiles["default"]
    profile.behavior_durations["manual_throw"]["seconds"] = 1000
    result, checkpoint = simulator.run_scenario("smoke")
    sales = [event for event in result.events if event.kind == "fish_sold"]
    assert [event.time_seconds for event in sales] == [3003]
    assert checkpoint.event_counters[SALE_PERIOD_COUNTER] == 10


def test_sale_checkpoint_rejects_inconsistent_inventory_and_future_period(tmp_path):
    simulator = _simulator(tmp_path)
    _, checkpoint = simulator.run_scenario("smoke", until_seconds=304)
    counters = dict(checkpoint.event_counters)
    checkpoint.event_counters["fish_sold_count"] += 1
    with pytest.raises(ValueError, match="committed state"):
        simulator.run_scenario("smoke", checkpoint)
    checkpoint.event_counters.update(counters)
    checkpoint.event_counters[SALE_PERIOD_COUNTER] = 999
    with pytest.raises(ValueError, match="sale period"):
        simulator.run_scenario("smoke", checkpoint)


def test_invalid_sale_completion_does_not_commit_background_production(tmp_path):
    from igess.behavior import BehaviorDecision
    simulator = _simulator(tmp_path)
    state = _stock(simulator.hall_adapter)
    before = state.to_dict()
    decision = BehaviorDecision(0, "default", "sell_fish", "[5,1]", 3, 0, 3)
    with pytest.raises(FishCommandError, match="deployed"):
        simulator.adapter.complete(state, decision, root_random_seed=1, next_throw_id=0, _mutate=True)
    assert state.to_dict() == before


def test_sale_formal_workflow_records_manifest_checkpoint_and_report(tmp_path):
    import json
    from pathlib import Path
    import yaml
    from igess.engines import EngineRegistry
    from igess.workflows import WorkflowService

    snapshot = _snapshot(tmp_path)
    class Provider:
        def load_tables(self, data_root, required_tables):
            return snapshot.tables
        def apply_overrides(self, tables, assignments):
            raise AssertionError("No overrides in this scenario")

    data_root = tmp_path / "data"
    data_root.mkdir()
    for name in snapshot.tables:
        (data_root / f"{name}.json").write_text("{}", encoding="utf-8")
    config = yaml.safe_load(Path("projects/fish/economy.yaml").read_text(encoding="utf-8"))
    config["engine"].update(data_root=str(data_root), production_data=False)
    config["scenarios"]["smoke"].update(duration_hours=1, record_interval_seconds=300)
    config["scenarios"]["smoke"]["outputs"].append("compact_event_details")
    profile = config["player_profiles"]["default"]
    profile["behavior_weights"] = {"manual_throw": "1", "sell_fish": "1"}
    config_path = tmp_path / "economy.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    service = WorkflowService(".", runs_root=tmp_path / "runs",
        engine_registry=EngineRegistry.standard(fish_luban_provider=Provider()))
    run = service.run_scenario(config_path, Path("projects/fish/luban_exports"), "smoke")
    assert run.status == "success", run.message
    manifest = json.loads((run.output_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert all((run.output_dir / name).is_file() for name in manifest["artifacts"])
    assert manifest["strategy"]["parameters"]["fish_sale"]["resource"] == "material"
    events = json.loads((run.output_dir / "events.json").read_text(encoding="utf-8"))
    sales = [event for event in events if event["kind"] == "fish_sold"]
    assert sales
    report = json.loads((run.report_index.parent / "report_data.json").read_text(encoding="utf-8"))
    summary = report["fish_progression"]["investment"]["profiles"]["default"]
    assert summary["sale_batch_count"] == len(sales)
    assert Decimal(summary["sale_material"]["exact_value"]) == sum(
        Decimal(event["details"]["fish_sale_material_added"]) for event in sales)
    assert "卖鱼材料" in (run.report_index.parent / "assets/report.js").read_text(encoding="utf-8")
    progression = json.loads((run.output_dir / "behavior_progression.json").read_text(encoding="utf-8"))
    assert "fish_sold" in progression["excluded_event_kinds"]
