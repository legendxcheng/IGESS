from __future__ import annotations

from .schema import Action, EconomyModel, SimulationState


def source_ref_label(model: EconomyModel, kind: str, item_id: str) -> str:
    details = model.source_details(kind, item_id)
    if not details:
        return ""
    return f"{details['source_workbook']}:{details['source_row']}"


def action_formula_trace(model: EconomyModel, action: Action, state: SimulationState) -> str:
    if action.kind == "buy_generator":
        generator = model.generators[action.item_id]
        generator_type = model.generator_types[generator.generator_type]
        owned_before = state.generators_owned[action.item_id]
        owned_after = owned_before + 1
        return (
            f"cost={generator_type['cost_formula']}"
            f"(base_cost={generator.base_cost},growth={generator.cost_growth},owned={owned_before});"
            f"output={generator_type['production_formula']}"
            f"(base_output={generator.base_output},owned={owned_after},multiplier=1)"
        )
    if action.kind == "buy_upgrade":
        upgrade = model.upgrades[action.item_id]
        return (
            f"modifier={upgrade.modifier_type}"
            f"(target={upgrade.target},value={upgrade.value})"
        )
    return ""


def prestige_formula_trace(model: EconomyModel, layer_id: str, state: SimulationState) -> str:
    layer = model.prestige_layers[layer_id]
    return (
        f"prestige={layer.formula}"
        f"(progress={state.resources[layer.trigger_resource].to_decimal_string()},"
        f"divisor={layer.divisor},exponent={layer.exponent})"
    )
