from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import stat
from typing import NoReturn

import pytest
import yaml

from igess.authoring import AuthoringError, ModelChange, parse_change_text
from igess.authoring.entity_schema import ENTITY_SCHEMAS
from igess.authoring.yaml_source import (
    find_yaml_duplicates,
    read_yaml_entity,
    upsert_yaml_entity,
)


def _base_config() -> dict[str, object]:
    return {
        "model": {
            "id": "authoring_test",
            "tick_seconds": 1,
            "number_backend": "bignum_log",
            "random_seed": 20260626,
        },
        "formulas": {
            "cost": {"args": ["x"], "expr": "x"},
            "production": {"args": ["x"], "expr": "x"},
        },
        "generator_types": {
            "building": {
                "cost_formula": "cost",
                "production_formula": "production",
            }
        },
        "source_types": {
            "active": {"description": "Active play"},
            "idle": {"description": "Idle play"},
        },
        "modifier_pipeline": {"order": ["base", "flat", "add_pct", "mult", "exp"]},
        "modifier_types": {"multiply": {"stage": "mult"}},
        "behavior_policies": {
            "cheap": {"type": "cheap_unlock_first"},
            "planner": {"type": "fastest_payback", "lookahead_depth": 1},
        },
        "session_patterns": {
            "short": {
                "offline_every_seconds": 60,
                "offline_duration_seconds": 0,
            }
        },
        "player_profiles": {
            "default": {
                "source_efficiency": {"active": "1", "idle": "1"},
                "behavior_policy": "cheap",
                "session_pattern": "short",
                "prestige_policy": "conservative",
                "activity_weights": {"gather": "1", "explore": "2"},
                "luck": "1",
            },
            "second": {
                "source_efficiency": {"active": "1", "idle": "1"},
                "behavior_policy": "cheap",
                "session_pattern": "short",
                "prestige_policy": "conservative",
            },
        },
        "scenarios": {
            "smoke": {
                "duration_hours": "1",
                "time_mode": "tick",
                "profiles": ["default"],
                "start_state": "new_player",
                "record_interval_seconds": 1,
                "outputs": ["resource_curve"],
            },
            "gate_target": {
                "duration_hours": "1",
                "time_mode": "tick",
                "profiles": ["default"],
                "start_state": "new_player",
                "record_interval_seconds": 1,
                "outputs": [],
            },
        },
        "rng_tables": {
            "loot": {
                "algorithm": "rarity_score",
                "rarities": {"common": "1", "rare": "10"},
            }
        },
        "rng_scenarios": {
            "rolls": {
                "table": "loot",
                "rolls": 10,
                "trials": 2,
                "profiles": ["default"],
                "event_threshold": "rare",
            }
        },
        "regression_gates": {
            "smoke": {
                "max_unlock_delay_pct": {"first upgrade": "5"},
                "min_prestige_gain": {"soul": "1"},
            }
        },
    }


def _write_config(path: Path, data: dict[str, object] | None = None) -> None:
    text = yaml.safe_dump(data or _base_config(), allow_unicode=True, sort_keys=False)
    path.write_text(text, encoding="utf-8", newline="\n")


def _change(entity: str, entity_id: str, fields: dict[str, object]) -> ModelChange:
    return ModelChange(1, "upsert", entity, entity_id, fields)


def _patch(
    path: Path,
    entity: str,
    entity_id: str,
    fields: dict[str, object],
) -> ModelChange:
    current = read_yaml_entity(path, entity, entity_id)
    assert current is not None
    return parse_change_text(
        json.dumps(
            {
                "version": 1,
                "operation": "upsert",
                "entity": entity,
                "id": entity_id,
                "fields": fields,
            }
        ),
        "json",
        current=current,
    )


_ENTITY_CASES = {
    "formula": (
        "new_formula",
        {"args": ["x"], "expr": "x"},
        {"args": ["x"], "expr": "x + 1"},
    ),
    "generator_type": (
        "new_generator_type",
        {"cost_formula": "cost", "production_formula": "production"},
        {"cost_formula": "production", "production_formula": "production"},
    ),
    "source_type": (
        "new_source_type",
        {"description": "新来源"},
        {"description": "Updated source"},
    ),
    "modifier_type": (
        "new_modifier_type",
        {"stage": "flat"},
        {"stage": "mult"},
    ),
    "behavior_policy": (
        "new_behavior_policy",
        {"type": "fastest_payback", "lookahead_depth": 1},
        {"type": "fastest_payback", "lookahead_depth": 2},
    ),
    "session_pattern": (
        "new_session_pattern",
        {"offline_every_seconds": 30, "offline_duration_seconds": 0},
        {"offline_every_seconds": 45, "offline_duration_seconds": 0},
    ),
    "player_profile": (
        "new_player_profile",
        {
            "source_efficiency": {"active": "1"},
            "behavior_policy": "cheap",
            "session_pattern": "short",
            "prestige_policy": "conservative",
        },
        {
            "source_efficiency": {"active": "2"},
            "behavior_policy": "cheap",
            "session_pattern": "short",
            "prestige_policy": "conservative",
        },
    ),
    "scenario": (
        "new_scenario",
        {
            "duration_hours": "1",
            "time_mode": "tick",
            "profiles": ["default"],
            "start_state": "new_player",
            "record_interval_seconds": 1,
            "outputs": [],
        },
        {
            "duration_hours": "2",
            "time_mode": "tick",
            "profiles": ["default"],
            "start_state": "new_player",
            "record_interval_seconds": 1,
            "outputs": [],
        },
    ),
    "rng_table": (
        "new_rng_table",
        {"algorithm": "rarity_score", "rarities": {"common": "1"}},
        {"algorithm": "rarity_score", "rarities": {"common": "2"}},
    ),
    "rng_scenario": (
        "new_rng_scenario",
        {"table": "loot", "rolls": 10, "trials": 2, "profiles": ["default"]},
        {"table": "loot", "rolls": 20, "trials": 2, "profiles": ["default"]},
    ),
    "regression_gate": (
        "gate_target",
        {"max_payback_seconds": {"mine": "10"}},
        {"max_payback_seconds": {"mine": "20"}},
    ),
}


@pytest.mark.parametrize("entity", tuple(_ENTITY_CASES))
def test_every_yaml_entity_creates_and_updates_at_its_exact_mapping(
    tmp_path: Path,
    entity: str,
) -> None:
    path = tmp_path / "economy.yaml"
    data = _base_config()
    entity_id, created_fields, updated_fields = _ENTITY_CASES[entity]
    storage = ENTITY_SCHEMAS[entity].storage_name
    assert isinstance(data[storage], dict)
    data[storage].pop(entity_id, None)
    _write_config(path, data)

    assert upsert_yaml_entity(path, _change(entity, entity_id, created_fields)) is True
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert loaded[storage][entity_id] == created_fields
    assert "id" not in loaded[storage][entity_id]
    assert read_yaml_entity(path, entity, entity_id) == created_fields

    assert upsert_yaml_entity(path, _change(entity, entity_id, updated_fields)) is True
    assert read_yaml_entity(path, entity, entity_id) == updated_fields


def test_read_accepts_a_mapping_and_returns_none_for_a_missing_id() -> None:
    data = _base_config()
    assert read_yaml_entity(data, "formula", "cost") == {
        "args": ["x"],
        "expr": "x",
    }
    assert read_yaml_entity(data, "formula", "absent") is None
    assert find_yaml_duplicates(data, "formula") == []


def test_player_profile_patch_recursively_merges_maps(tmp_path: Path) -> None:
    path = tmp_path / "economy.yaml"
    _write_config(path)

    change = _patch(
        path,
        "player_profile",
        "default",
        {
            "source_efficiency": {"active": "2"},
            "activity_weights": {"gather": None, "new_activity": "3"},
        },
    )
    assert upsert_yaml_entity(path, change) is True

    assert read_yaml_entity(path, "player_profile", "default") == {
        "source_efficiency": {"active": "2", "idle": "1"},
        "behavior_policy": "cheap",
        "session_pattern": "short",
        "prestige_policy": "conservative",
        "activity_weights": {"explore": "2", "new_activity": "3"},
        "luck": "1",
    }


def test_scenario_patch_replaces_lists_instead_of_merging_them(tmp_path: Path) -> None:
    path = tmp_path / "economy.yaml"
    _write_config(path)

    change = _patch(
        path,
        "scenario",
        "smoke",
        {"profiles": ["second"], "outputs": ["unlock_timeline"]},
    )
    assert upsert_yaml_entity(path, change) is True
    fields = read_yaml_entity(path, "scenario", "smoke")
    assert fields is not None
    assert fields["profiles"] == ["second"]
    assert fields["outputs"] == ["unlock_timeline"]


def test_optional_field_deletion_is_persisted(tmp_path: Path) -> None:
    path = tmp_path / "economy.yaml"
    _write_config(path)

    change = _patch(path, "behavior_policy", "planner", {"lookahead_depth": None})
    assert upsert_yaml_entity(path, change) is True
    assert read_yaml_entity(path, "behavior_policy", "planner") == {
        "type": "fastest_payback"
    }


def test_required_field_deletion_fails_before_any_write(tmp_path: Path) -> None:
    path = tmp_path / "economy.yaml"
    _write_config(path)
    before = path.read_bytes()
    current = read_yaml_entity(path, "scenario", "smoke")

    with pytest.raises(AuthoringError) as caught:
        parse_change_text(
            json.dumps(
                {
                    "version": 1,
                    "operation": "upsert",
                    "entity": "scenario",
                    "id": "smoke",
                    "fields": {"profiles": None},
                }
            ),
            "json",
            current=current,
        )

    assert caught.value.code == "invalid_change"
    assert path.read_bytes() == before


def test_regression_gate_patch_merges_nested_rules_and_removes_one_rule(
    tmp_path: Path,
) -> None:
    path = tmp_path / "economy.yaml"
    _write_config(path)

    change = _patch(
        path,
        "regression_gate",
        "smoke",
        {
            "max_unlock_delay_pct": {
                "first upgrade": None,
                "second upgrade": "7",
            },
            "min_prestige_gain": {"gem": "2"},
        },
    )
    assert upsert_yaml_entity(path, change) is True
    assert read_yaml_entity(path, "regression_gate", "smoke") == {
        "max_unlock_delay_pct": {"second upgrade": "7"},
        "min_prestige_gain": {"soul": "1", "gem": "2"},
    }


def test_rng_rarities_are_written_and_reloaded_in_exact_denominator_order(
    tmp_path: Path,
) -> None:
    path = tmp_path / "economy.yaml"
    _write_config(path)
    unordered = {
        "algorithm": "rarity_score",
        "rarities": {"epic": "100", "common": "1", "rare": "10"},
    }

    assert upsert_yaml_entity(path, _change("rng_table", "ordered", unordered)) is True
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert list(raw["rng_tables"]["ordered"]["rarities"]) == [
        "common",
        "rare",
        "epic",
    ]
    reloaded = read_yaml_entity(path, "rng_table", "ordered")
    assert reloaded is not None
    assert list(reloaded["rarities"]) == ["common", "rare", "epic"]


@pytest.mark.parametrize(
    ("entity", "entity_id", "fields", "field", "value"),
    [
        (
            "generator_type",
            "bad",
            {"cost_formula": "missing", "production_formula": "production"},
            "cost_formula",
            "missing",
        ),
        (
            "player_profile",
            "bad",
            {
                "source_efficiency": {"missing_source": "1"},
                "behavior_policy": "missing_policy",
                "session_pattern": "short",
                "prestige_policy": "conservative",
            },
            "behavior_policy",
            "missing_policy",
        ),
        (
            "scenario",
            "bad",
            {
                "duration_hours": "1",
                "time_mode": "tick",
                "profiles": ["missing_profile"],
                "start_state": "new_player",
                "record_interval_seconds": 1,
                "outputs": [],
            },
            "profiles",
            "missing_profile",
        ),
        (
            "rng_scenario",
            "bad",
            {
                "table": "missing_table",
                "rolls": 1,
                "trials": 1,
                "profiles": ["default"],
            },
            "table",
            "missing_table",
        ),
        (
            "regression_gate",
            "missing_scenario",
            {"min_prestige_gain": {"soul": "1"}},
            "id",
            "missing_scenario",
        ),
    ],
)
def test_unknown_yaml_references_are_structured_and_do_not_mutate_the_file(
    tmp_path: Path,
    entity: str,
    entity_id: str,
    fields: dict[str, object],
    field: str,
    value: str,
) -> None:
    path = tmp_path / "economy.yaml"
    _write_config(path)
    before = path.read_bytes()

    with pytest.raises(AuthoringError) as caught:
        upsert_yaml_entity(path, _change(entity, entity_id, fields))

    assert caught.value.code == "invalid_change"
    assert caught.value.details["reason"] == "unknown_reference"
    assert caught.value.details["entity"] == entity
    assert caught.value.details["id"] == entity_id
    assert caught.value.details["field"] == field
    assert caught.value.details["value"] == value
    json.dumps(dict(caught.value.details), allow_nan=False)
    assert path.read_bytes() == before


def test_rng_scenario_validates_threshold_against_its_selected_table(
    tmp_path: Path,
) -> None:
    path = tmp_path / "economy.yaml"
    _write_config(path)
    before = path.read_bytes()
    change = _change(
        "rng_scenario",
        "bad_threshold",
        {
            "table": "loot",
            "rolls": 1,
            "trials": 1,
            "profiles": ["default"],
            "event_threshold": "epic",
        },
    )

    with pytest.raises(AuthoringError) as caught:
        upsert_yaml_entity(path, change)

    assert caught.value.code == "invalid_change"
    assert caught.value.details["field"] == "event_threshold"
    assert caught.value.details["allowed"] == ("common", "rare")
    assert path.read_bytes() == before


def test_duplicate_entity_ids_can_be_found_and_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "economy.yaml"
    path.write_text(
        "model: {id: duplicate}\n"
        "formulas:\n"
        "  same: {args: [x], expr: x}\n"
        "  other: {args: [x], expr: x}\n"
        "  same: {args: [x], expr: x + 1}\n",
        encoding="utf-8",
        newline="\n",
    )

    assert find_yaml_duplicates(path, "formula") == ["same"]
    with pytest.raises(AuthoringError) as read_error:
        read_yaml_entity(path, "formula", "same")
    assert read_error.value.code == "invalid_yaml_source"
    assert read_error.value.details["reason"] == "duplicate_key"

    before = path.read_bytes()
    with pytest.raises(AuthoringError) as write_error:
        upsert_yaml_entity(path, _change("formula", "new", {"args": ["x"], "expr": "x"}))
    assert write_error.value.code == "invalid_yaml_source"
    assert path.read_bytes() == before


def test_duplicate_scan_rejects_deep_yaml_before_composition(tmp_path: Path) -> None:
    path = tmp_path / "economy.yaml"
    nested = "value"
    for _ in range(80):
        nested = f"[{nested}]"
    path.write_text(f"formulas: {nested}\n", encoding="utf-8", newline="\n")

    with pytest.raises(AuthoringError) as caught:
        find_yaml_duplicates(path, "formula")

    assert caught.value.code == "invalid_yaml_source"
    assert caught.value.details["reason"] == "nesting_depth_exceeded"
    assert caught.value.details["phase"] == "scan"


def test_duplicate_scan_rejects_alias_fanout_before_composition(tmp_path: Path) -> None:
    path = tmp_path / "economy.yaml"
    aliases = ", ".join("*shared" for _ in range(5000))
    path.write_text(
        f"shared: &shared {{value: exact}}\nitems: [{aliases}]\n",
        encoding="utf-8",
        newline="\n",
    )

    with pytest.raises(AuthoringError) as caught:
        find_yaml_duplicates(path, "formula")

    assert caught.value.code == "invalid_yaml_source"
    assert caught.value.details["reason"] == "alias_budget_exceeded"
    assert caught.value.details["phase"] == "scan"


def test_duplicate_scan_converts_composer_recursion_to_stable_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "economy.yaml"
    path.write_text("formulas: {}\n", encoding="utf-8", newline="\n")

    def recurse(*args: object, **kwargs: object) -> NoReturn:
        del args, kwargs
        raise RecursionError("composer recursion")

    monkeypatch.setattr("igess.authoring.yaml_source.yaml.compose", recurse)
    with pytest.raises(AuthoringError) as caught:
        find_yaml_duplicates(path, "formula")

    assert caught.value.code == "invalid_yaml_source"
    assert caught.value.details["reason"] == "compose_error"
    assert caught.value.details["error_type"] == "RecursionError"


@pytest.mark.parametrize(
    ("source", "reason"),
    [
        ("scenarios:\n  smoke:\n    duration_hours: 0.1\n", "unsupported_float"),
        ("formulas:\n  bad: !python/object:os.system {}\n", "unsupported_tag"),
        ("formulas:\n  bad: &bad\n    args: [*bad]\n    expr: x\n", "cyclic_structure"),
    ],
)
def test_strict_yaml_rejects_unsupported_values_with_json_safe_diagnostics(
    tmp_path: Path,
    source: str,
    reason: str,
) -> None:
    path = tmp_path / "economy.yaml"
    path.write_text(source, encoding="utf-8", newline="\n")

    with pytest.raises(AuthoringError) as caught:
        read_yaml_entity(path, "formula", "bad")

    assert caught.value.code == "invalid_yaml_source"
    assert caught.value.details["reason"] == reason
    json.dumps(dict(caught.value.details), allow_nan=False)


def test_serialization_is_canonical_ordered_utf8_lf_and_repeatable(
    tmp_path: Path,
) -> None:
    path = tmp_path / "economy.yaml"
    data = _base_config()
    data["tail_marker"] = {"保留": "末尾"}
    _write_config(path, data)
    before_data = yaml.safe_load(path.read_text(encoding="utf-8"))

    change = _change("formula", "unicode_formula", {"args": ["x"], "expr": "x + 1"})
    assert upsert_yaml_entity(path, change) is True
    first = path.read_bytes()
    assert b"\r" not in first
    assert first.endswith(b"\n") and not first.endswith(b"\n\n")
    decoded = first.decode("utf-8")
    assert "保留" in decoded

    after_data = yaml.safe_load(decoded)
    assert list(after_data) == [*before_data]
    assert list(after_data["formulas"]) == ["cost", "production", "unicode_formula"]
    assert after_data["tail_marker"] == {"保留": "末尾"}

    assert upsert_yaml_entity(path, change) is False
    assert path.read_bytes() == first


def test_exponent_like_strings_remain_exact_and_reload_after_unrelated_edit(
    tmp_path: Path,
) -> None:
    path = tmp_path / "economy.yaml"
    exponent_values = ["1e3", "1E+3", "-1e-3", "1.0e3", "-1.0E+3"]
    data = _base_config()
    _write_config(path, data)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write("engine_defaults:\n")
        for index, value in enumerate(exponent_values):
            handle.write(f"  value_{index}: '{value}'\n")

    change = _patch(path, "source_type", "active", {"description": "Updated"})
    assert upsert_yaml_entity(path, change) is True
    written = path.read_text(encoding="utf-8")
    for value in exponent_values:
        assert f"'{value}'" in written
    assert list(yaml.safe_load(written)["engine_defaults"].values()) == exponent_values
    assert read_yaml_entity(path, "source_type", "active") == {
        "description": "Updated"
    }

    first = path.read_bytes()
    assert upsert_yaml_entity(path, change) is False
    assert path.read_bytes() == first


def test_comments_are_deliberately_not_preserved(tmp_path: Path) -> None:
    path = tmp_path / "economy.yaml"
    _write_config(path)
    original = path.read_text(encoding="utf-8")
    path.write_text("# author comment\n" + original, encoding="utf-8", newline="\n")

    change = _patch(path, "source_type", "active", {"description": "Updated"})
    assert upsert_yaml_entity(path, change) is True
    assert "# author comment" not in path.read_text(encoding="utf-8")


def test_atomic_replace_failure_preserves_original_and_cleans_temp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "economy.yaml"
    _write_config(path)
    before = path.read_bytes()

    def fail_replace(
        source: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        target: object,
    ) -> None:
        del source, target
        raise OSError("replace failed")

    monkeypatch.setattr("igess.authoring.yaml_source.os.replace", fail_replace)
    with pytest.raises(AuthoringError) as caught:
        upsert_yaml_entity(
            path,
            _change("source_type", "new", {"description": "New source"}),
        )

    assert caught.value.code == "yaml_write_failed"
    assert caught.value.details["reason"] == "replace_error"
    assert caught.value.details["error_type"] == "OSError"
    assert path.read_bytes() == before
    assert list(tmp_path.glob(".*.tmp")) == []


def test_replace_that_installs_planned_bytes_then_raises_is_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "economy.yaml"
    _write_config(path)
    real_replace = os.replace

    def replace_then_raise(
        source: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        target: str | bytes | os.PathLike[str] | os.PathLike[bytes],
    ) -> NoReturn:
        real_replace(source, target)
        raise OSError("replace wrapper failed after success")

    monkeypatch.setattr("igess.authoring.yaml_source.os.replace", replace_then_raise)
    assert upsert_yaml_entity(
        path,
        _change("source_type", "new", {"description": "New source"}),
    ) is True

    assert read_yaml_entity(path, "source_type", "new") == {
        "description": "New source"
    }
    assert list(tmp_path.glob(".*.tmp")) == []


def test_atomic_write_applies_only_the_source_permission_bits_to_temp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "economy.yaml"
    _write_config(path)
    expected_mode = stat.S_IMODE(path.stat().st_mode)
    calls: list[tuple[Path, int]] = []
    real_chmod = os.chmod

    def record_chmod(target: str | os.PathLike[str], mode: int) -> None:
        calls.append((Path(target), mode))
        real_chmod(target, mode)

    monkeypatch.setattr("igess.authoring.yaml_source.os.chmod", record_chmod)
    assert upsert_yaml_entity(
        path,
        _change("source_type", "new", {"description": "New source"}),
    ) is True

    assert len(calls) == 1
    assert calls[0][0].parent == path.parent
    assert calls[0][0] != path
    assert calls[0][1] == expected_mode


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission contract")
def test_atomic_write_preserves_posix_permission_mode(tmp_path: Path) -> None:
    path = tmp_path / "economy.yaml"
    _write_config(path)
    path.chmod(0o640)

    assert upsert_yaml_entity(
        path,
        _change("source_type", "new", {"description": "New source"}),
    ) is True

    assert stat.S_IMODE(path.stat().st_mode) == 0o640


def test_mapping_and_entity_shape_errors_are_stable(tmp_path: Path) -> None:
    path = tmp_path / "economy.yaml"
    path.write_text("formulas: []\n", encoding="utf-8", newline="\n")

    with pytest.raises(AuthoringError) as caught:
        read_yaml_entity(path, "formula", "x")
    assert caught.value.code == "invalid_yaml_source"
    assert caught.value.details["reason"] == "entity_mapping_not_mapping"


def test_explicit_null_entity_is_invalid_instead_of_missing(tmp_path: Path) -> None:
    path = tmp_path / "economy.yaml"
    path.write_text("formulas:\n  null_formula: null\n", encoding="utf-8", newline="\n")

    with pytest.raises(AuthoringError) as caught:
        read_yaml_entity(path, "formula", "null_formula")
    assert caught.value.code == "invalid_yaml_source"
    assert caught.value.details["reason"] == "entity_not_mapping"


def test_input_mapping_is_not_mutated_by_reads_or_writes(tmp_path: Path) -> None:
    data = _base_config()
    original = deepcopy(data)
    assert read_yaml_entity(data, "scenario", "smoke") is not None
    assert data == original

    path = tmp_path / "economy.yaml"
    _write_config(path, data)
    fields = {"description": "External"}
    change = _change("source_type", "external", fields)
    assert upsert_yaml_entity(path, change) is True
    assert fields == {"description": "External"}
