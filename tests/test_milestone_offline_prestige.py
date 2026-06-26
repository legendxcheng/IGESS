from igess.builder import ModelBuilder
from igess.loader import ConfigLoader
from igess.numbers import SimNumber
from igess.schema import SimulationState
from igess.simulator import Simulator


CONFIG = "examples/shelldiver_v0/economy.yaml"
TABLES = "examples/shelldiver_v0/luban_exports"


def test_simulator_applies_milestones_offline_rewards_and_prestige():
    model = ModelBuilder.build(ConfigLoader.load(CONFIG, TABLES))
    result = Simulator(model).run_scenario("day_1_progression")
    kinds = {event.kind for event in result.events}

    assert "milestone_reward" in kinds
    assert "offline_reward" in kinds
    assert "prestige_reset" in kinds
    assert "prestige_point" in result.timeline[-1].resources


def test_prestige_reset_event_records_gain_and_reset_resource():
    model = ModelBuilder.build(ConfigLoader.load(CONFIG, TABLES))
    result = Simulator(model).run_scenario("day_1_progression")
    prestige_events = [event for event in result.events if event.kind == "prestige_reset"]

    assert prestige_events
    assert prestige_events[0].details["reward_resource"] == "prestige_point"
    assert int(prestige_events[0].details["gain"]) >= 1
    assert "fish" in prestige_events[0].details["reset_resources"]


def test_prestige_policy_changes_reset_threshold():
    raw = ConfigLoader.load(CONFIG, TABLES)
    raw.rules.player_profiles["optimizer"].prestige_policy = "conservative"
    model = ModelBuilder.build(raw)
    simulator = Simulator(model)
    state = SimulationState.new(model)
    state.generators_owned["boat"] = 5
    state.resources["fish"] = SimNumber.parse("600")
    events = []

    simulator._apply_prestige("synthetic", "optimizer", 10, state, events)

    assert events == []

    state.resources["fish"] = SimNumber.parse("2400")
    simulator._apply_prestige("synthetic", "optimizer", 20, state, events)

    assert len(events) == 1
    assert events[0].details["gain"] == "2"
