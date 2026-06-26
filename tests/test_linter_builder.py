import copy

import pytest

from igess.builder import ModelBuilder
from igess.linter import ConfigError, ConfigLinter
from igess.loader import ConfigLoader


CONFIG = "examples/shelldiver_v0/economy.yaml"
TABLES = "examples/shelldiver_v0/luban_exports"


def test_loader_linter_and_builder_accept_sample_config():
    raw = ConfigLoader.load(CONFIG, TABLES)

    ConfigLinter.validate(raw)
    model = ModelBuilder.build(raw)

    assert model.config.model_id == "shelldiver_incremental_v0"
    assert set(model.resources) == {"fish", "prestige_point"}
    assert set(model.generators) == {"fisherman", "boat", "net"}
    assert set(model.milestones) == {"first_boat", "small_fleet"}
    assert set(model.prestige_layers) == {"reef_renown"}
    assert "exponential_cost" in model.formulas


def test_linter_rejects_missing_resource_reference():
    raw = ConfigLoader.load(CONFIG, TABLES)
    broken = copy.deepcopy(raw)
    broken.generators[0].output_resource = "coin"

    with pytest.raises(ConfigError, match="unknown output_resource"):
        ConfigLinter.validate(broken)


def test_linter_rejects_bad_modifier_target():
    raw = ConfigLoader.load(CONFIG, TABLES)
    broken = copy.deepcopy(raw)
    broken.upgrades[0].target = "generator:ghost.output"

    with pytest.raises(ConfigError, match="unknown modifier target"):
        ConfigLinter.validate(broken)


def test_linter_rejects_formula_arg_mismatch():
    raw = ConfigLoader.load(CONFIG, TABLES)
    broken = copy.deepcopy(raw)
    broken.rules.formulas["generator_output"].expr = "base_output * missing"

    with pytest.raises(ConfigError, match="unknown formula name"):
        ConfigLinter.validate(broken)


def test_linter_rejects_bad_milestone_reward_resource():
    raw = ConfigLoader.load(CONFIG, TABLES)
    broken = copy.deepcopy(raw)
    broken.milestones[0].reward_resource = "coin"

    with pytest.raises(ConfigError, match="unknown reward_resource"):
        ConfigLinter.validate(broken)


def test_linter_rejects_bad_prestige_reset_resource():
    raw = ConfigLoader.load(CONFIG, TABLES)
    broken = copy.deepcopy(raw)
    broken.prestige_layers[0].reset_resources = ["coin"]

    with pytest.raises(ConfigError, match="unknown reset_resource"):
        ConfigLinter.validate(broken)


def test_linter_rejects_unlock_dependency_cycles():
    raw = ConfigLoader.load(CONFIG, TABLES)
    broken = copy.deepcopy(raw)
    for generator in broken.generators:
        if generator.id == "fisherman":
            generator.unlock_condition = "owned(net) >= 1"
        elif generator.id == "boat":
            generator.unlock_condition = "owned(fisherman) >= 5"
        elif generator.id == "net":
            generator.unlock_condition = "owned(boat) >= 3"

    with pytest.raises(ConfigError, match="unlock dependency cycle"):
        ConfigLinter.validate(broken)


def test_linter_rejects_unknown_scenario_time_mode():
    raw = ConfigLoader.load(CONFIG, TABLES)
    broken = copy.deepcopy(raw)
    broken.rules.scenarios["day_1_progression"].time_mode = "warp"

    with pytest.raises(ConfigError, match="unknown time_mode"):
        ConfigLinter.validate(broken)


def test_linter_rejects_non_positive_scenario_timing():
    raw = ConfigLoader.load(CONFIG, TABLES)
    broken = copy.deepcopy(raw)
    broken.rules.scenarios["day_1_progression"].record_interval_seconds = 0

    with pytest.raises(ConfigError, match="record_interval_seconds"):
        ConfigLinter.validate(broken)

    broken = copy.deepcopy(raw)
    broken.rules.scenarios["day_1_progression"].duration_hours = 0

    with pytest.raises(ConfigError, match="duration_hours"):
        ConfigLinter.validate(broken)
