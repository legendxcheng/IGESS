from igess.builder import ModelBuilder
from igess.loader import ConfigLoader
from igess.modifiers import Modifier, ModifierStack
from igess.numbers import SimNumber
from igess.policy import PolicyEngine
from igess.schema import Action, SimulationState


CONFIG = "examples/shelldiver_v0/economy.yaml"
TABLES = "examples/shelldiver_v0/luban_exports"


def test_modifier_pipeline_uses_declared_order():
    result = ModifierStack.apply(
        base=SimNumber.parse("10"),
        modifiers=[
            Modifier(stage="flat", value=SimNumber.parse("5")),
            Modifier(stage="mult", value=SimNumber.parse("2")),
            Modifier(stage="add_pct", value=SimNumber.parse("0.5")),
        ],
    )

    assert result.to_decimal_string() == "45"


def test_fastest_payback_uses_one_step_unlock_lookahead():
    model = ModelBuilder.build(ConfigLoader.load(CONFIG, TABLES))
    state = SimulationState.new(model)
    state.resources["fish"] = SimNumber.parse("1000")
    state.generators_owned["fisherman"] = 9

    action = PolicyEngine(model).choose_action("optimizer", state)

    assert action is not None
    assert action.kind == "buy_generator"
    assert action.item_id == "fisherman"


def test_fastest_payback_lookahead_uses_modifier_pipeline_delta():
    model = ModelBuilder.build(ConfigLoader.load(CONFIG, TABLES))
    state = SimulationState.new(model)
    state.generators_owned["fisherman"] = 9
    action = Action(
        kind="buy_generator",
        item_id="fisherman",
        cost_resource="fish",
        cost=SimNumber.parse("10"),
        score=SimNumber.parse("10"),
    )

    bonus = PolicyEngine(model)._unlock_chain_bonus(action, state)

    assert bonus.to_decimal_string() == "10"


def test_cheap_unlock_first_prefers_affordable_lowest_cost_item():
    model = ModelBuilder.build(ConfigLoader.load(CONFIG, TABLES))
    state = SimulationState.new(model)
    state.resources["fish"] = SimNumber.parse("1000")
    state.generators_owned["fisherman"] = 5

    action = PolicyEngine(model).choose_action("casual", state)

    assert action is not None
    assert action.kind == "buy_generator"
    assert action.item_id == "fisherman"
