from igess.builder import ModelBuilder
from igess.loader import ConfigLoader
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
