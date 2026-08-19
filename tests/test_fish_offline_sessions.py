from __future__ import annotations

from pathlib import Path

from fish_test_support import _snapshot
from igess.behavior import BehaviorRuntimeState
from igess.builder import ModelBuilder
from igess.fish_barbell import FishBarbellDataAdapter
from igess.fish_behavior import (
    CHEAPEST_BELOW_MATERIAL_TENTH_POLICY_ID,
    EXERCISE_BARBELL_BEHAVIOR_ID,
    HIGHEST_AFFORDABLE_POLICY_ID,
    PURCHASE_TORPEDO_BEHAVIOR_ID,
    STRENGTH_REBIRTH_BEHAVIOR_ID,
    SYNTHESIZE_BARBELL_BEHAVIOR_ID,
    TRASH_MAN_REBIRTH_BEHAVIOR_ID,
    UPGRADE_FISH_BEHAVIOR_ID,
    UPGRADE_FISH_HALL_BEHAVIOR_ID,
)
from igess.fish_hall import FishHallDataAdapter
from igess.fish_production import (
    FishProductionRuntime,
    settle_fish_production,
)
from igess.fish_session import FishDailySessionSchedule
from igess.fish_simulator import FishEconomySimulator
from igess.fish_state import (
    FishCheckpointCodec,
    FishInstance,
    OwnedBarbell,
    PlayerState,
    TrashStock,
)
from igess.fish_trash import FishTrashDataAdapter
from igess.loader import ConfigLoader
from igess.numbers import SimNumber


def test_default_profile_prioritizes_growth_in_two_hour_session() -> None:
    raw = ConfigLoader.load_rules_only("projects/fish/economy.yaml")
    profile = raw.rules.player_profiles["default"]
    pattern = raw.rules.session_patterns[profile.session_pattern]

    assert pattern["daily_online_seconds"] == 7200
    assert profile.behavior_weights["manual_throw"] == SimNumber.one()
    assert (
        profile.behavior_weights[EXERCISE_BARBELL_BEHAVIOR_ID]
        == profile.behavior_weights["manual_throw"]
    )
    assert (
        profile.behavior_weights[SYNTHESIZE_BARBELL_BEHAVIOR_ID]
        == SimNumber.parse(100)
    )
    assert (
        profile.behavior_weights[UPGRADE_FISH_HALL_BEHAVIOR_ID]
        == SimNumber.parse(100)
    )
    assert (
        profile.behavior_weights[PURCHASE_TORPEDO_BEHAVIOR_ID]
        == SimNumber.parse("1e100")
    )
    assert (
        profile.behavior_weights[UPGRADE_FISH_BEHAVIOR_ID]
        == SimNumber.parse("0.1")
    )
    expected_durations = {
        "manual_throw": 30,
        EXERCISE_BARBELL_BEHAVIOR_ID: 60,
        SYNTHESIZE_BARBELL_BEHAVIOR_ID: 10,
        UPGRADE_FISH_HALL_BEHAVIOR_ID: 10,
        PURCHASE_TORPEDO_BEHAVIOR_ID: 10,
        UPGRADE_FISH_BEHAVIOR_ID: 3,
        STRENGTH_REBIRTH_BEHAVIOR_ID: 5,
        TRASH_MAN_REBIRTH_BEHAVIOR_ID: 10,
    }
    for behavior_id, seconds in expected_durations.items():
        assert profile.behavior_durations[behavior_id] == {
            "type": "fixed",
            "seconds": seconds,
        }
    for rebirth_id in (
        STRENGTH_REBIRTH_BEHAVIOR_ID,
        TRASH_MAN_REBIRTH_BEHAVIOR_ID,
    ):
        assert profile.behavior_weights[rebirth_id] == SimNumber.parse("1e100")
    assert profile.behavior_target_policies[
        UPGRADE_FISH_BEHAVIOR_ID
    ] == CHEAPEST_BELOW_MATERIAL_TENTH_POLICY_ID
    assert profile.behavior_target_policies[
        SYNTHESIZE_BARBELL_BEHAVIOR_ID
    ] == "random_affordable"
    assert profile.behavior_target_policies[
        PURCHASE_TORPEDO_BEHAVIOR_ID
    ] == HIGHEST_AFFORDABLE_POLICY_ID


def test_offline_settlement_halves_passive_work_and_never_adds_strength(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path, trash_duration=10)
    hall_adapter = FishHallDataAdapter(snapshot)
    state = PlayerState.new(
        initial_torpedo_id=1,
        initial_strength=10,
        initial_trash_man_realm_id=2,
    )
    state.fish.items = [FishInstance(1, 101, 7, 1, 100, 1)]
    state.fish.next_instance_id = 2
    state.trash_man.highest_realm_id = 3
    state.trash_man.processing.active_trash_id = 1
    state.trash_man.processing.stocks = [TrashStock(1, 1)]
    state.barbell.owned = [OwnedBarbell(1, 1)]
    state.barbell.equipped_id = 1

    settlement = settle_fish_production(
        state,
        4,
        hall_adapter=hall_adapter,
        trash_adapter=FishTrashDataAdapter(snapshot),
        barbell_adapter=FishBarbellDataAdapter(snapshot),
        online=False,
    )

    assert settlement.money_added == SimNumber.parse(20)
    assert settlement.material_added == SimNumber.parse(5)
    assert settlement.strength_added == SimNumber.zero()
    assert settlement.state.wallet.strength.to_sim_number() == (
        SimNumber.parse(10)
    )
    assert settlement.state.trash_man.realm_id == 2
    assert settlement.state.trash_man.training_progress_seconds == 0
    assert settlement.trash_processing.work_consumed == (
        SimNumber.parse("2.5")
    )
    details = settlement.event_details()
    assert details["fish_production_mode"] == "offline"
    assert details["fish_passive_production_efficiency"] == "0.5"
    assert details["trash_processing_efficiency"] == "0.5"
    assert details["trash_man_cultivation_elapsed_seconds"] == "0"
    assert details["barbell_strength_added"] == "0"


def test_daily_online_budget_stops_barbell_training_and_replays_offline(
    tmp_path: Path,
) -> None:
    raw = ConfigLoader.load(
        "projects/fish/economy.yaml",
        "projects/fish/luban_exports",
    )
    model = ModelBuilder.build(raw)
    model.scenarios["smoke"].duration_hours = 10 / 3600
    profile = model.player_profiles["default"]
    model.session_patterns[profile.session_pattern] = {
        "daily_online_seconds": 4
    }
    profile.behavior_weights = {
        EXERCISE_BARBELL_BEHAVIOR_ID: SimNumber.one()
    }
    profile.behavior_durations = {
        EXERCISE_BARBELL_BEHAVIOR_ID: {
            "type": "fixed",
            "seconds": 2,
        }
    }
    snapshot = _snapshot(tmp_path)
    model_digest = "sha256:" + ("d" * 64)
    simulator = FishEconomySimulator(
        model,
        snapshot,
        model_digest=model_digest,
    )
    initial_state = PlayerState.new(
        initial_torpedo_id=1,
        initial_strength=0,
        initial_trash_man_realm_id=1,
    )
    initial_state.barbell.owned = [OwnedBarbell(1, 1)]
    initial_state.barbell.equipped_id = 1
    initial_checkpoint = FishCheckpointCodec.new(
        initial_state,
        model_digest=model_digest,
        scenario_id="smoke",
        profile_id="default",
        root_random_seed=model.config.random_seed,
        behavior_state=BehaviorRuntimeState().to_dict(),
        engine_runtime_state=FishProductionRuntime().to_dict(),
        context=FishHallDataAdapter(snapshot).validation_context(),
    )

    continuous = simulator.run_scenario("smoke", initial_checkpoint)
    first = simulator.run_scenario(
        "smoke",
        initial_checkpoint,
        until_seconds=7,
    )
    resumed = simulator.run_scenario("smoke", first.checkpoint)

    assert first.checkpoint.engine_state["production"]["lastSettledAt"] == 4
    first_state = FishCheckpointCodec.decode_state(
        first.checkpoint,
        expected_model_digest=model_digest,
        context=FishHallDataAdapter(snapshot).validation_context(),
    )
    assert first_state.wallet.strength.to_sim_number() == SimNumber.parse(8)
    assert resumed.checkpoint.engine_state == continuous.checkpoint.engine_state
    assert resumed.checkpoint.behavior_state == (
        continuous.checkpoint.behavior_state
    )
    assert resumed.checkpoint.event_counters == (
        continuous.checkpoint.event_counters
    )
    assert (
        first.result.timeline + resumed.result.timeline[1:]
        == continuous.result.timeline
    )
    exercise_events = [
        event
        for event in continuous.result.events
        if event.kind == "barbell_exercise_completed"
    ]
    assert [event.time_seconds for event in exercise_events] == [2, 4]
    assert all(
        event.details["barbell_strength_added"] == "4"
        for event in exercise_events
    )
    offline_event = next(
        event
        for event in continuous.result.events
        if event.kind == "fish_offline_settled"
    )
    assert offline_event.time_seconds == 10
    assert offline_event.details["barbell_strength_added"] == "0"
    assert offline_event.details["fish_passive_production_efficiency"] == "0.5"


def test_daily_session_schedule_restarts_online_each_simulation_day() -> None:
    schedule = FishDailySessionSchedule(daily_online_seconds=7200)

    assert schedule.is_online(0)
    assert schedule.is_online(7199)
    assert not schedule.is_online(7200)
    assert schedule.next_transition_after(7200) == 86400
    assert schedule.is_online(86400)
    assert schedule.next_transition_after(86400) == 93600
