from __future__ import annotations

from dataclasses import FrozenInstanceError
import json
from types import MappingProxyType

import pytest

from igess.authoring import (
    ModelChange as PublicModelChange,
    merge_fields as public_merge_fields,
    parse_change_text as public_parse_change_text,
)
from igess.authoring.change import ModelChange, merge_fields, parse_change_text
from igess.authoring.entity_schema import get_entity_schema
from igess.authoring.response import AuthoringError


def _parse(payload: object, *, current: dict[str, object] | None = None) -> ModelChange:
    return parse_change_text(json.dumps(payload), "json", current=current)


def _valid_resource(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "version": 1,
        "operation": "upsert",
        "entity": "resource",
        "id": "gold",
        "fields": {"name": "Gold", "dimension": "currency"},
    }
    payload.update(overrides)
    return payload


def _assert_invalid(
    text: str,
    format_name: str = "json",
    *,
    current: dict[str, object] | None = None,
    field: str | None = None,
) -> AuthoringError:
    with pytest.raises(AuthoringError) as caught:
        parse_change_text(text, format_name, current=current)
    error = caught.value
    assert error.code == "invalid_change"
    if field is not None:
        assert error.details["field"] == field
    return error


def test_change_api_is_available_from_the_authoring_package() -> None:
    assert PublicModelChange is ModelChange
    assert public_merge_fields is merge_fields
    assert public_parse_change_text is parse_change_text


def test_json_and_yaml_equivalent_documents_produce_the_same_frozen_change() -> None:
    json_text = json.dumps(_valid_resource())
    yaml_text = """\
version: 1
operation: upsert
entity: resource
id: gold
fields:
  name: Gold
  dimension: currency
"""

    from_json = parse_change_text(json_text, "json")
    from_yaml = parse_change_text(yaml_text, "yaml")

    assert from_json == from_yaml == ModelChange(
        version=1,
        operation="upsert",
        entity="resource",
        id="gold",
        fields={"name": "Gold", "dimension": "currency"},
    )
    assert isinstance(from_json.fields, MappingProxyType)
    with pytest.raises(TypeError):
        from_json.fields["name"] = "Changed"  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        from_json.id = "changed"  # type: ignore[misc]


def test_change_defensively_copies_nested_values_and_serializes_for_audit() -> None:
    fields = {
        "duration_hours": "1",
        "time_mode": "tick",
        "profiles": ["default"],
        "start_state": "new_player",
        "record_interval_seconds": 1,
        "outputs": ["resource_curve"],
    }
    change = ModelChange(1, "upsert", "scenario", "smoke", fields)
    fields["profiles"].append("mutated")  # type: ignore[union-attr]

    assert change.fields["profiles"] == ("default",)
    payload = change.to_payload()
    assert list(payload) == ["version", "operation", "entity", "id", "fields"]
    assert payload["fields"]["profiles"] == ["default"]
    payload["fields"]["profiles"].append("audit-only")
    assert change.to_payload()["fields"]["profiles"] == ["default"]
    assert json.loads(json.dumps(change.to_payload(), allow_nan=False)) == change.to_payload()


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"operation": "upsert", "entity": "resource", "id": "gold", "fields": {}}, "version"),
        ({"version": 1, "entity": "resource", "id": "gold", "fields": {}}, "operation"),
        ({"version": 1, "operation": "upsert", "id": "gold", "fields": {}}, "entity"),
        ({"version": 1, "operation": "upsert", "entity": "resource", "fields": {}}, "id"),
        ({"version": 1, "operation": "upsert", "entity": "resource", "id": "gold"}, "fields"),
    ],
)
def test_missing_required_top_level_key_is_rejected(payload: dict[str, object], field: str) -> None:
    error = _assert_invalid(json.dumps(payload), field=field)
    assert error.details["value"] is None


def test_unknown_top_level_keys_are_rejected_as_an_exact_contract() -> None:
    payload = _valid_resource(extra="not-supported")
    error = _assert_invalid(json.dumps(payload), field="extra")
    assert error.details["value"] == "not-supported"
    assert tuple(error.details["allowed"]) == (
        "version",
        "operation",
        "entity",
        "id",
        "fields",
        "if_model_digest",
    )


@pytest.mark.parametrize("version", [True, False, 0, 2, "1", None])
def test_version_must_be_native_integer_one(version: object) -> None:
    error = _assert_invalid(json.dumps(_valid_resource(version=version)), field="version")
    assert tuple(error.details["allowed"]) == (1,)


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"operation": "delete"}, "operation"),
        ({"entity": "unknown"}, "entity"),
        ({"id": "bad/id"}, "id"),
        ({"fields": []}, "fields"),
        ({"fields": {"id": "other", "name": "Gold", "dimension": "currency"}}, "id"),
        ({"fields": {"name": "Gold", "dimension": "currency", "unknown": 1}}, "unknown"),
    ],
)
def test_operation_entity_id_and_fields_use_precise_validation(
    overrides: dict[str, object], field: str
) -> None:
    _assert_invalid(json.dumps(_valid_resource(**overrides)), field=field)


@pytest.mark.parametrize("entity", [[], {}, 1, True, None])
def test_non_string_entity_is_a_stable_invalid_change(entity: object) -> None:
    _assert_invalid(json.dumps(_valid_resource(entity=entity)), field="entity")


@pytest.mark.parametrize(
    "text",
    [
        '{"version":1,"operation":"upsert","entity":"constant","id":"x","fields":{"value":1.0}}',
        '{"version":1,"operation":"upsert","entity":"constant","id":"x","fields":{"value":1e3}}',
        '{"version":1,"operation":"upsert","entity":"constant","id":"x","fields":{"value":NaN}}',
        '{"version":1,"operation":"upsert","entity":"constant","id":"x","fields":{"value":Infinity}}',
        '{"version":1.0,"operation":"upsert","entity":"constant","id":"x","fields":{"value":"1"}}',
    ],
)
def test_json_rejects_float_exponent_and_nonfinite_numeric_tokens_at_any_depth(text: str) -> None:
    error = _assert_invalid(text)
    assert error.details["reason"] == "floating_number"


@pytest.mark.parametrize("value", ["1.25", "1e3", "1E+3", ".nan", ".inf", "-.Inf"])
def test_yaml_rejects_every_unquoted_float_form(value: str) -> None:
    text = f"""\
version: 1
operation: upsert
entity: constant
id: x
fields:
  value: {value}
"""
    error = _assert_invalid(text, "yaml")
    assert error.details["reason"] == "floating_number"


def test_quoted_yaml_decimal_and_native_integer_economic_value_are_exact() -> None:
    quoted = parse_change_text(
        "version: 1\noperation: upsert\nentity: constant\nid: x\nfields:\n  value: '1e3'\n",
        "yaml",
    )
    integer = _parse(
        {
            "version": 1,
            "operation": "upsert",
            "entity": "constant",
            "id": "x",
            "fields": {"value": 1000},
        }
    )
    assert quoted.fields == {"value": "1e3"}
    assert integer.fields == {"value": "1000"}


def test_native_integer_fields_remain_integers_and_booleans_are_not_integers() -> None:
    valid = {
        "version": 1,
        "operation": "upsert",
        "entity": "session_pattern",
        "id": "authoring",
        "fields": {"offline_every_seconds": 60, "offline_duration_seconds": 0},
    }
    assert _parse(valid).fields == {
        "offline_every_seconds": 60,
        "offline_duration_seconds": 0,
    }
    valid["fields"] = {
        "offline_every_seconds": True,
        "offline_duration_seconds": 0,
    }
    _assert_invalid(json.dumps(valid), field="offline_every_seconds")


@pytest.mark.parametrize(
    ("text", "format_name"),
    [
        ('{"version":1,"version":1,"operation":"upsert","entity":"constant","id":"x","fields":{"value":"1"}}', "json"),
        ("version: 1\nversion: 1\noperation: upsert\nentity: constant\nid: x\nfields:\n  value: '1'\n", "yaml"),
        ('{"version":1,"operation":"upsert","entity":"constant","id":"x","fields":{"value":"1","value":"2"}}', "json"),
        ("version: 1\noperation: upsert\nentity: constant\nid: x\nfields:\n  value: '1'\n  value: '2'\n", "yaml"),
    ],
)
def test_duplicate_keys_are_rejected_at_every_mapping_depth(text: str, format_name: str) -> None:
    error = _assert_invalid(text, format_name)
    assert error.details["reason"] == "duplicate_key"


@pytest.mark.parametrize(
    ("text", "expected_path"),
    [
        (
            """\
version: 1
operation: upsert
entity: player_profile
id: default
fields:
  source_efficiency: &loop
    active: *loop
  behavior_policy: cheap
  session_pattern: authoring
  prestige_policy: conservative
""",
            "$.fields.source_efficiency.active",
        ),
        (
            """\
version: 1
operation: upsert
entity: scenario
id: smoke
fields:
  duration_hours: '1'
  time_mode: tick
  profiles: &loop
    - *loop
  start_state: new_player
  record_interval_seconds: 1
  outputs: []
""",
            "$.fields.profiles[0]",
        ),
    ],
)
def test_yaml_alias_cycles_are_rejected_as_safe_typed_errors(
    text: str, expected_path: str
) -> None:
    error = _assert_invalid(text, "yaml")
    assert error.details["reason"] == "cyclic_structure"
    assert error.details["path"] == expected_path
    assert error.details["cycle_to"].startswith("$.fields")
    assert len(error.details["path"]) <= 512
    json.dumps(dict(error.details), allow_nan=False)


def test_shared_acyclic_yaml_alias_is_accepted_in_each_branch() -> None:
    change = parse_change_text(
        """\
version: 1
operation: upsert
entity: regression_gate
id: smoke
fields:
  max_unlock_delay_pct: &limits
    first_upgrade: '10'
  max_payback_seconds: *limits
""",
        "yaml",
    )
    assert change.fields == {
        "max_unlock_delay_pct": {"first_upgrade": "10"},
        "max_payback_seconds": {"first_upgrade": "10"},
    }


@pytest.mark.parametrize(
    ("text", "format_name", "reason"),
    [
        ("{not-json", "json", "invalid_syntax"),
        ("fields: [", "yaml", "invalid_syntax"),
        ("[]", "json", "root_not_mapping"),
        ("version: 1", "toml", "unsupported_format"),
    ],
)
def test_parser_failures_are_stable_typed_errors_without_low_level_exception_text(
    text: str, format_name: str, reason: str
) -> None:
    error = _assert_invalid(text, format_name)
    assert error.details["reason"] == reason
    assert type(error).__name__ not in error.message
    assert "line " not in error.message.lower()


def test_invalid_yaml_values_in_diagnostics_remain_strict_json_serializable() -> None:
    error = _assert_invalid(
        "version: 1\noperation: upsert\nentity: resource\nid: gold\nfields: {}\nextra: 2026-07-15\n",
        "yaml",
        field="extra",
    )
    encoded = json.dumps(dict(error.details), allow_nan=False)
    assert json.loads(encoded)["value"] == "<date>"


@pytest.mark.parametrize(
    "digest",
    [
        "",
        "sha256:abc",
        "sha256:" + "A" * 64,
        "SHA256:" + "a" * 64,
        "sha256:" + "g" * 64,
        1,
        True,
    ],
)
def test_if_model_digest_must_be_lowercase_sha256_when_non_null(digest: object) -> None:
    error = _assert_invalid(
        json.dumps(_valid_resource(if_model_digest=digest)), field="if_model_digest"
    )
    assert tuple(error.details["allowed"]) == ("null", "sha256:<64 lowercase hex>")


def test_if_model_digest_may_be_absent_or_null_and_is_serialized_only_when_present() -> None:
    absent = _parse(_valid_resource())
    null = _parse(_valid_resource(if_model_digest=None))
    digest = "sha256:" + "a" * 64
    present = _parse(_valid_resource(if_model_digest=digest))

    assert absent.if_model_digest is None
    assert null.if_model_digest is None
    assert "if_model_digest" not in absent.to_payload()
    assert "if_model_digest" not in null.to_payload()
    assert present.if_model_digest == digest
    assert present.to_payload()["if_model_digest"] == digest


def test_create_requires_all_schema_required_fields() -> None:
    payload = _valid_resource(fields={"name": "Gold"})
    _assert_invalid(json.dumps(payload), field="dimension")


def test_update_retains_omitted_values_and_normalizes_only_after_complete_merge() -> None:
    current = {"name": "Gold", "dimension": "currency"}
    change = _parse(_valid_resource(fields={"name": "Coins"}), current=current)
    assert change.fields == {"name": "Coins", "dimension": "currency"}


def test_update_recursively_merges_profile_maps_and_deletes_nested_keys() -> None:
    current = {
        "source_efficiency": {"active": "1", "offline": "0.5"},
        "behavior_policy": "cheap",
        "session_pattern": "authoring",
        "prestige_policy": "conservative",
        "activity_weights": {"gather": "1", "fish": "2"},
    }
    payload = {
        "version": 1,
        "operation": "upsert",
        "entity": "player_profile",
        "id": "default",
        "fields": {
            "source_efficiency": {"active": 2, "offline": None},
            "activity_weights": {"fish": None, "mine": 3},
        },
    }

    change = _parse(payload, current=current)

    assert change.fields == {
        "source_efficiency": {"active": "2"},
        "behavior_policy": "cheap",
        "session_pattern": "authoring",
        "prestige_policy": "conservative",
        "activity_weights": {"gather": "1", "mine": "3"},
    }


def test_update_replaces_scenario_lists_instead_of_merging_them() -> None:
    current = {
        "duration_hours": "1",
        "time_mode": "tick",
        "profiles": ["default", "expert"],
        "start_state": "new_player",
        "record_interval_seconds": 1,
        "outputs": ["resource_curve", "purchase_timeline"],
    }
    payload = {
        "version": 1,
        "operation": "upsert",
        "entity": "scenario",
        "id": "smoke",
        "fields": {"profiles": ["default"], "outputs": []},
    }
    change = _parse(payload, current=current)
    assert change.fields["profiles"] == ("default",)
    assert change.fields["outputs"] == ()


def test_update_null_deletes_optional_field_but_required_null_is_rejected() -> None:
    current = {
        "type": "cheap_unlock_first",
        "lookahead_depth": 2,
        "include_unlock_chain_value": True,
    }
    optional = {
        "version": 1,
        "operation": "upsert",
        "entity": "behavior_policy",
        "id": "cheap",
        "fields": {"lookahead_depth": None},
    }
    required = {**optional, "fields": {"type": None}}

    change = _parse(optional, current=current)
    assert change.fields == {
        "type": "cheap_unlock_first",
        "include_unlock_chain_value": True,
    }
    _assert_invalid(json.dumps(required), current=current, field="type")


def test_merge_fields_has_rfc7396_container_semantics_without_mutating_inputs() -> None:
    current = {
        "source_efficiency": {"active": "1", "offline": "0.5"},
        "behavior_policy": "cheap",
        "session_pattern": "authoring",
        "prestige_policy": "conservative",
        "activity_weights": {"gather": "1"},
    }
    patch = {
        "source_efficiency": {"offline": None, "generator": "1"},
        "activity_weights": None,
    }
    current_snapshot = json.loads(json.dumps(current))
    patch_snapshot = json.loads(json.dumps(patch))

    merged = merge_fields(current, patch, get_entity_schema("player_profile"))

    assert merged == {
        "source_efficiency": {"active": "1", "generator": "1"},
        "behavior_policy": "cheap",
        "session_pattern": "authoring",
        "prestige_policy": "conservative",
    }
    assert current == current_snapshot
    assert patch == patch_snapshot


def test_previous_frozen_change_fields_can_be_used_as_current_without_leaking_tuples() -> None:
    original = _parse(
        {
            "version": 1,
            "operation": "upsert",
            "entity": "scenario",
            "id": "smoke",
            "fields": {
                "duration_hours": "1",
                "time_mode": "tick",
                "profiles": ["default"],
                "start_state": "new_player",
                "record_interval_seconds": 1,
                "outputs": ["resource_curve"],
            },
        }
    )
    update = _parse(
        {
            "version": 1,
            "operation": "upsert",
            "entity": "scenario",
            "id": "smoke",
            "fields": {"duration_hours": "2"},
        },
        current=original.fields,  # type: ignore[arg-type]
    )
    assert update.fields["profiles"] == ("default",)
    assert update.fields["outputs"] == ("resource_curve",)


def test_merge_fields_rejects_required_null_and_unknown_fields() -> None:
    schema = get_entity_schema("behavior_policy")
    current = {"type": "cheap_unlock_first"}
    with pytest.raises(AuthoringError) as required:
        merge_fields(current, {"type": None}, schema)
    assert required.value.details["field"] == "type"
    with pytest.raises(AuthoringError) as unknown:
        merge_fields(current, {"unknown": 1}, schema)
    assert unknown.value.details["field"] == "unknown"


@pytest.mark.parametrize("cyclic_side", ["current", "patch"])
def test_merge_fields_rejects_programmatic_cycles_before_recursive_processing(
    cyclic_side: str,
) -> None:
    schema = get_entity_schema("player_profile")
    current: dict[str, object] = {
        "source_efficiency": {"active": "1"},
        "behavior_policy": "cheap",
        "session_pattern": "authoring",
        "prestige_policy": "conservative",
    }
    patch: dict[str, object] = {"activity_weights": {"gather": "1"}}
    loop: dict[str, object] = {}
    loop["self"] = loop
    if cyclic_side == "current":
        current["source_efficiency"] = loop
    else:
        patch["activity_weights"] = loop

    with pytest.raises(AuthoringError) as caught:
        merge_fields(current, patch, schema)

    error = caught.value
    assert error.code == "invalid_change"
    assert error.details["reason"] == "cyclic_structure"
    assert error.details["path"].endswith(".self")
    json.dumps(dict(error.details), allow_nan=False)


def test_direct_model_change_rejects_cycle_before_recursive_freeze() -> None:
    fields: dict[str, object] = {}
    fields["loop"] = fields
    with pytest.raises(AuthoringError) as caught:
        ModelChange(1, "upsert", "resource", "gold", fields)
    assert caught.value.details["reason"] == "cyclic_structure"


def test_create_with_empty_current_argument_is_an_update_but_still_requires_complete_result() -> None:
    payload = {
        "version": 1,
        "operation": "upsert",
        "entity": "resource",
        "id": "gold",
        "fields": {"name": "Gold"},
    }
    _assert_invalid(json.dumps(payload), current={}, field="dimension")
