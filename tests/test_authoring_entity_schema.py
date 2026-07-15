from __future__ import annotations

from collections.abc import Mapping

import pytest

from igess.authoring.entity_schema import (
    ENTITY_SCHEMAS,
    EntitySchema,
    FieldSpec,
    ValidationContext,
    get_entity_schema,
    validate_entity_fields,
)
from igess.authoring.response import AuthoringError


TABLE_FIELDS = {
    "resource": ("id", "name", "dimension"),
    "generator": (
        "id",
        "name",
        "generator_type",
        "output_resource",
        "source_type",
        "base_output",
        "base_cost",
        "cost_resource",
        "cost_growth",
        "unlock_condition",
    ),
    "activity": ("id", "name", "source_type", "unlock_condition"),
    "activity_output": ("id", "activity_id", "output_resource", "amount_per_second"),
    "upgrade": (
        "id",
        "name",
        "target",
        "modifier_type",
        "value",
        "cost_resource",
        "base_cost",
        "unlock_condition",
    ),
    "constant": ("id", "value"),
    "milestone": ("id", "name", "condition", "reward_resource", "reward_amount"),
    "prestige_layer": (
        "id",
        "name",
        "trigger_resource",
        "reward_resource",
        "formula",
        "divisor",
        "exponent",
        "min_gain",
        "reset_resources",
        "unlock_condition",
    ),
}

YAML_ENTITIES = {
    "formula": "formulas",
    "generator_type": "generator_types",
    "source_type": "source_types",
    "modifier_type": "modifier_types",
    "behavior_policy": "behavior_policies",
    "session_pattern": "session_patterns",
    "player_profile": "player_profiles",
    "scenario": "scenarios",
    "rng_table": "rng_tables",
    "rng_scenario": "rng_scenarios",
    "regression_gate": "regression_gates",
}


def _assert_invalid(
    entity: str,
    entity_id: object,
    fields: object,
    *,
    field: str,
    context: ValidationContext | None = None,
    require_complete: bool = True,
) -> AuthoringError:
    with pytest.raises(AuthoringError) as caught:
        validate_entity_fields(
            entity,
            entity_id,  # type: ignore[arg-type]
            fields,  # type: ignore[arg-type]
            context=context,
            require_complete=require_complete,
        )
    error = caught.value
    assert error.code == "invalid_change"
    assert error.details["entity"] == entity
    assert error.details["id"] == entity_id
    assert error.details["field"] == field
    assert "value" in error.details
    assert "allowed" in error.details
    return error


def test_exports_exact_immutable_entity_schema_set() -> None:
    expected = set(TABLE_FIELDS) | set(YAML_ENTITIES)
    assert set(ENTITY_SCHEMAS) == expected
    assert len(ENTITY_SCHEMAS) == 19
    assert isinstance(ENTITY_SCHEMAS, Mapping)
    with pytest.raises(TypeError):
        ENTITY_SCHEMAS["extra"] = ENTITY_SCHEMAS["resource"]  # type: ignore[index]
    assert all(isinstance(schema, EntitySchema) for schema in ENTITY_SCHEMAS.values())
    assert all(isinstance(field, FieldSpec) for schema in ENTITY_SCHEMAS.values() for field in schema.fields)


def test_table_schema_storage_and_field_order_match_luban_contract() -> None:
    expected_workbooks = {
        "resource": "resources.xlsx",
        "generator": "generators.xlsx",
        "activity": "activities.xlsx",
        "activity_output": "activity_outputs.xlsx",
        "upgrade": "upgrades.xlsx",
        "constant": "constants.xlsx",
        "milestone": "milestones.xlsx",
        "prestige_layer": "prestige_layers.xlsx",
    }
    for entity, columns in TABLE_FIELDS.items():
        schema = get_entity_schema(entity)
        assert schema.storage_kind == "workbook"
        assert schema.storage_name == expected_workbooks[entity]
        assert schema.field_names == columns[1:]
        assert schema.required_fields == columns[1:]
        assert schema.optional_fields == ()


def test_yaml_schema_storage_names_and_optional_fields() -> None:
    expected_optional = {
        "behavior_policy": ("lookahead_depth", "include_unlock_chain_value"),
        "player_profile": ("activity_weights", "luck"),
        "rng_scenario": ("event_threshold",),
        "regression_gate": (
            "max_unlock_delay_pct",
            "max_payback_seconds",
            "min_prestige_gain",
        ),
    }
    for entity, mapping_name in YAML_ENTITIES.items():
        schema = get_entity_schema(entity)
        assert schema.storage_kind == "yaml"
        assert schema.storage_name == mapping_name
        assert schema.optional_fields == expected_optional.get(entity, ())


def test_unknown_entity_is_rejected_with_allowed_entities() -> None:
    error = _assert_invalid("unknown", "x", {}, field="entity", require_complete=False)
    assert tuple(error.details["allowed"]) == tuple(ENTITY_SCHEMAS)


@pytest.mark.parametrize("entity_id", ["", " ", "with space", "slash/id", "中文", 3, True, None])
def test_invalid_envelope_id_is_rejected(entity_id: object) -> None:
    _assert_invalid("constant", entity_id, {"value": "1"}, field="id")


@pytest.mark.parametrize("entity_id", ["a", "A-Z", "a_b.c-9", "0"])
def test_valid_envelope_id_is_accepted(entity_id: str) -> None:
    assert validate_entity_fields("constant", entity_id, {"value": "1"}) == {"value": "1"}


def test_fields_must_be_native_mapping_and_cannot_contain_id() -> None:
    _assert_invalid("constant", "c", [], field="fields")
    _assert_invalid("constant", "c", {"id": "other", "value": "1"}, field="id")


def test_unknown_and_missing_fields_are_rejected_but_partial_validation_is_available() -> None:
    missing = _assert_invalid("resource", "gold", {"name": "Gold"}, field="dimension")
    assert missing.details["value"] is None
    _assert_invalid("resource", "gold", {"name": "Gold", "dimension": "currency", "x": 1}, field="x")
    assert validate_entity_fields(
        "resource", "gold", {"name": "Gold"}, require_complete=False
    ) == {"name": "Gold"}


@pytest.mark.parametrize("value", ["", "   ", 1, True, [], {}])
def test_text_requires_nonempty_utf8_string(value: object) -> None:
    _assert_invalid("resource", "gold", {"name": value}, field="name", require_complete=False)


def test_text_preserves_unicode_and_whitespace_inside_value() -> None:
    assert validate_entity_fields(
        "resource", "gold", {"name": " 金币 "}, require_complete=False
    ) == {"name": " 金币 "}


@pytest.mark.parametrize("value", [True, False, 1, 0, "true", "false", None])
def test_boolean_field_requires_native_boolean(value: object) -> None:
    fields = {"include_unlock_chain_value": value}
    if type(value) is bool:
        assert validate_entity_fields(
            "behavior_policy", "p", fields, require_complete=False
        ) == fields
    else:
        _assert_invalid("behavior_policy", "p", fields, field="include_unlock_chain_value", require_complete=False)


@pytest.mark.parametrize("value", [0, 4])
def test_nonnegative_integer_accepts_native_int(value: int) -> None:
    assert validate_entity_fields(
        "behavior_policy", "p", {"lookahead_depth": value}, require_complete=False
    ) == {"lookahead_depth": value}


@pytest.mark.parametrize("value", [-1, True, False, "1", 1.0, None])
def test_nonnegative_integer_rejects_negative_bool_string_and_float(value: object) -> None:
    _assert_invalid(
        "behavior_policy",
        "p",
        {"lookahead_depth": value},
        field="lookahead_depth",
        require_complete=False,
    )


@pytest.mark.parametrize("value", [1, 10])
def test_positive_integer_accepts_native_positive_int(value: int) -> None:
    assert validate_entity_fields(
        "session_pattern", "s", {"offline_every_seconds": value}, require_complete=False
    ) == {"offline_every_seconds": value}


@pytest.mark.parametrize("value", [0, -1, True, "1", 1.0])
def test_positive_integer_rejects_zero_and_non_integer_tokens(value: object) -> None:
    _assert_invalid(
        "session_pattern",
        "s",
        {"offline_every_seconds": value},
        field="offline_every_seconds",
        require_complete=False,
    )


@pytest.mark.parametrize(
    ("value", "normalized"),
    [(0, "0"), (-2, "-2"), ("1.25", "1.25"), ("-2E+3", "-2E+3"), ("0.000", "0.000")],
)
def test_decimal_accepts_only_integer_tokens_or_exact_base10_strings(value: object, normalized: str) -> None:
    assert validate_entity_fields("constant", "c", {"value": value}) == {"value": normalized}


@pytest.mark.parametrize(
    "value",
    [True, False, 1.0, -0.0, float("inf"), float("nan"), "Infinity", "NaN", "+1", ".5", "1.", "1e", " 1", "1 ", None],
)
def test_decimal_rejects_boolean_float_nonfinite_and_noncanonical_strings(value: object) -> None:
    _assert_invalid("constant", "c", {"value": value}, field="value")


@pytest.mark.parametrize("value", [0, "0", "0.0", "-1", -1])
def test_positive_decimal_rejects_zero_and_negative(value: object) -> None:
    _assert_invalid(
        "activity_output",
        "out",
        {"amount_per_second": value},
        field="amount_per_second",
        require_complete=False,
    )


@pytest.mark.parametrize("value", ["1e-1000", 1, "0.01"])
def test_positive_decimal_accepts_exact_positive_values(value: object) -> None:
    expected = str(value) if isinstance(value, int) else value
    assert validate_entity_fields(
        "activity_output", "out", {"amount_per_second": value}, require_complete=False
    ) == {"amount_per_second": expected}


@pytest.mark.parametrize("value", [-1, "-0.0001"])
def test_nonnegative_decimal_rejects_negative(value: object) -> None:
    _assert_invalid("generator", "g", {"base_cost": value}, field="base_cost", require_complete=False)


@pytest.mark.parametrize("value", [0, "0.0", "2e3"])
def test_nonnegative_decimal_accepts_zero_and_positive(value: object) -> None:
    expected = str(value) if isinstance(value, int) else value
    assert validate_entity_fields(
        "generator", "g", {"base_cost": value}, require_complete=False
    ) == {"base_cost": expected}


@pytest.mark.parametrize("op", [">=", "<=", "==", ">", "<"])
def test_condition_accepts_every_operator(op: str) -> None:
    condition = f"owned(mine-1) {op} 0"
    assert validate_entity_fields(
        "generator", "g", {"unlock_condition": condition}, require_complete=False
    ) == {"unlock_condition": condition}


def test_condition_accepts_exact_always() -> None:
    assert validate_entity_fields(
        "generator", "g", {"unlock_condition": "always"}, require_complete=False
    ) == {"unlock_condition": "always"}


@pytest.mark.parametrize(
    "value",
    ["Always", " always", "owned(*) >= 1", "owned(mine) != 1", "owned(mine)>=-1", "owned(mine) >= 1.0", "owned(bad/id) >= 1", "owned() >= 1", 1],
)
def test_condition_rejects_malformed_forms(value: object) -> None:
    _assert_invalid("generator", "g", {"unlock_condition": value}, field="unlock_condition", require_complete=False)


@pytest.mark.parametrize("target", ["generator:mine.output", "generator:*.output", "generator:a_b-1.output"])
def test_upgrade_target_accepts_generator_output_forms(target: str) -> None:
    assert validate_entity_fields("upgrade", "u", {"target": target}, require_complete=False) == {"target": target}


@pytest.mark.parametrize("target", ["generator:mine", "activity:mine.output", "generator:.output", "generator:bad/id.output", 1])
def test_upgrade_target_rejects_other_forms(target: object) -> None:
    _assert_invalid("upgrade", "u", {"target": target}, field="target", require_complete=False)


@pytest.mark.parametrize(
    ("entity", "field", "allowed"),
    [
        ("modifier_type", "stage", ("flat", "add_pct", "mult", "exp")),
        ("behavior_policy", "type", ("cheap_unlock_first", "fastest_payback", "new_content_bias")),
        ("player_profile", "prestige_policy", ("conservative", "efficient_reset", "milestone_based")),
        ("scenario", "time_mode", ("tick", "analytic")),
        ("scenario", "start_state", ("new_player",)),
        ("rng_table", "algorithm", ("rarity_score",)),
    ],
)
def test_strict_enums_accept_only_documented_values(entity: str, field: str, allowed: tuple[str, ...]) -> None:
    for value in allowed:
        assert validate_entity_fields(entity, "x", {field: value}, require_complete=False) == {field: value}
    error = _assert_invalid(entity, "x", {field: "other"}, field=field, require_complete=False)
    assert tuple(error.details["allowed"]) == allowed


def test_id_lists_are_native_validate_items_and_preserve_order() -> None:
    assert validate_entity_fields(
        "scenario", "s", {"profiles": ["b", "a"]}, require_complete=False
    ) == {"profiles": ["b", "a"]}
    for value in ("a", {"a": 1}, ["ok", "bad/id"], ["ok", 1]):
        _assert_invalid("scenario", "s", {"profiles": value}, field="profiles", require_complete=False)
    _assert_invalid("scenario", "s", {"profiles": []}, field="profiles", require_complete=False)


def test_reset_resources_allows_empty_native_id_list() -> None:
    assert validate_entity_fields(
        "prestige_layer", "p", {"reset_resources": []}, require_complete=False
    ) == {"reset_resources": []}


def test_output_list_is_native_and_restricted_but_may_be_empty() -> None:
    allowed = [
        "resource_curve",
        "purchase_timeline",
        "unlock_timeline",
        "prestige_timeline",
        "bottleneck_report",
    ]
    assert validate_entity_fields("scenario", "s", {"outputs": allowed}, require_complete=False) == {"outputs": allowed}
    assert validate_entity_fields("scenario", "s", {"outputs": []}, require_complete=False) == {"outputs": []}
    _assert_invalid("scenario", "s", {"outputs": ["unknown"]}, field="outputs", require_complete=False)
    _assert_invalid("scenario", "s", {"outputs": "resource_curve"}, field="outputs", require_complete=False)


def test_decimal_maps_are_native_validate_key_kind_and_never_accept_float() -> None:
    result = validate_entity_fields(
        "player_profile",
        "p",
        {"source_efficiency": {"active": 0, "idle": "1e-2"}},
        require_complete=False,
    )
    assert result == {"source_efficiency": {"active": "0", "idle": "1e-2"}}
    for value in ([], "active:1", {"bad/id": "1"}, {"active": 1.0}, {1: "1"}):
        _assert_invalid(
            "player_profile", "p", {"source_efficiency": value}, field="source_efficiency", require_complete=False
        )


def test_regression_text_key_map_accepts_nonempty_unicode_text_keys() -> None:
    result = validate_entity_fields(
        "regression_gate",
        "s",
        {"max_unlock_delay_pct": {"首个升级": 0}},
    )
    assert result == {"max_unlock_delay_pct": {"首个升级": "0"}}


def test_formula_compiler_accepts_safe_expression_and_rejects_unsafe_or_bad_args() -> None:
    fields = {"args": ["base", "growth"], "expr": "base * pow(growth, 2)"}
    assert validate_entity_fields("formula", "cost", fields) == fields
    _assert_invalid(
        "formula",
        "cost",
        {"args": ["base"], "expr": "__import__('os').system('x')"},
        field="expr",
    )
    _assert_invalid(
        "formula", "cost", {"args": ["bad/id"], "expr": "1"}, field="args"
    )
    _assert_invalid(
        "formula", "cost", {"args": ["x", "x"], "expr": "x"}, field="args"
    )


def test_rng_rarities_accept_unordered_input_and_normalize_by_exact_denominator() -> None:
    result = validate_entity_fields(
        "rng_table",
        "loot",
        {
            "algorithm": "rarity_score",
            "rarities": {"epic": "100", "common": "1", "rare": "10"},
        },
    )
    assert list(result["rarities"]) == ["common", "rare", "epic"]
    assert result["rarities"] == {"common": "1", "rare": "10", "epic": "100"}


@pytest.mark.parametrize(
    "rarities",
    [{}, [], {"common": 0}, {"common": "-1"}, {"bad/id": "1"}, {"a": "1", "b": "1.0"}],
)
def test_rng_rarities_require_nonempty_valid_ids_positive_unique_exact_denominators(rarities: object) -> None:
    _assert_invalid("rng_table", "loot", {"rarities": rarities}, field="rarities", require_complete=False)


def test_rng_event_threshold_is_checked_when_context_has_selected_table_fields() -> None:
    context = ValidationContext(
        rng_tables={
            "loot": {
                "algorithm": "rarity_score",
                "rarities": {"common": "1", "rare": "10"},
            }
        }
    )
    fields = {"table": "loot", "event_threshold": "rare"}
    assert validate_entity_fields("rng_scenario", "rolls", fields, context=context, require_complete=False) == fields
    _assert_invalid(
        "rng_scenario",
        "rolls",
        {"table": "loot", "event_threshold": "legendary"},
        field="event_threshold",
        context=context,
        require_complete=False,
    )


def test_rng_event_threshold_is_deferred_without_selected_table_fields() -> None:
    fields = {"table": "loot", "event_threshold": "rare"}
    assert validate_entity_fields("rng_scenario", "rolls", fields, require_complete=False) == fields
    assert validate_entity_fields(
        "rng_scenario", "rolls", fields, context=ValidationContext(rng_tables={}), require_complete=False
    ) == fields


@pytest.mark.parametrize("fields", [{}, {"max_unlock_delay_pct": {}}, {"min_prestige_gain": {}, "max_payback_seconds": {}}])
def test_regression_gate_requires_at_least_one_nonempty_supported_map(fields: dict[str, object]) -> None:
    _assert_invalid("regression_gate", "scenario", fields, field="fields")


def test_regression_gate_accepts_zero_values_in_each_supported_map() -> None:
    fields = {
        "max_unlock_delay_pct": {"upgrade:first": 0},
        "max_payback_seconds": {"mine": "0"},
        "min_prestige_gain": {"soul": "0.0"},
    }
    assert validate_entity_fields("regression_gate", "scenario", fields) == {
        "max_unlock_delay_pct": {"upgrade:first": "0"},
        "max_payback_seconds": {"mine": "0"},
        "min_prestige_gain": {"soul": "0.0"},
    }


def test_every_complete_entity_schema_has_a_valid_representative() -> None:
    examples = {
        "resource": {"name": "Gold", "dimension": "currency"},
        "generator": {"name": "Mine", "generator_type": "building", "output_resource": "gold", "source_type": "idle", "base_output": "1", "base_cost": "10", "cost_resource": "gold", "cost_growth": "1.15", "unlock_condition": "always"},
        "activity": {"name": "Gather", "source_type": "active", "unlock_condition": "always"},
        "activity_output": {"activity_id": "gather", "output_resource": "gold", "amount_per_second": "1"},
        "upgrade": {"name": "Tools", "target": "generator:mine.output", "modifier_type": "mult", "value": "2", "cost_resource": "gold", "base_cost": "100", "unlock_condition": "owned(mine) >= 1"},
        "constant": {"value": "1"},
        "milestone": {"name": "First", "condition": "owned(mine) >= 1", "reward_resource": "gold", "reward_amount": "10"},
        "prestige_layer": {"name": "Soul", "trigger_resource": "gold", "reward_resource": "soul", "formula": "prestige", "divisor": "1000", "exponent": "0.5", "min_gain": "1", "reset_resources": ["gold"], "unlock_condition": "always"},
        "formula": {"args": ["x"], "expr": "x * 2"},
        "generator_type": {"cost_formula": "cost", "production_formula": "production"},
        "source_type": {"description": "Active play"},
        "modifier_type": {"stage": "mult"},
        "behavior_policy": {"type": "cheap_unlock_first"},
        "session_pattern": {"offline_every_seconds": 3600, "offline_duration_seconds": 0},
        "player_profile": {"source_efficiency": {"active": "1"}, "behavior_policy": "cheap", "session_pattern": "authoring", "prestige_policy": "conservative"},
        "scenario": {"duration_hours": "1", "time_mode": "tick", "profiles": ["default"], "start_state": "new_player", "record_interval_seconds": 1, "outputs": []},
        "rng_table": {"algorithm": "rarity_score", "rarities": {"common": "1"}},
        "rng_scenario": {"table": "loot", "rolls": 10, "trials": 2, "profiles": ["default"]},
        "regression_gate": {"min_prestige_gain": {"soul": "0"}},
    }
    assert set(examples) == set(ENTITY_SCHEMAS)
    for entity, fields in examples.items():
        assert validate_entity_fields(entity, "example", fields)
