from __future__ import annotations

import json
import os
from pathlib import Path
import stat

import pytest

from igess.authoring import AuthoringProject, ModelChange
from igess.authoring import exports as exports_module
from igess.authoring.exports import (
    apply_to_candidate,
    compute_export_digest,
    ephemeral_export,
    export_candidate,
    stage_sources,
)
from igess.authoring.response import AuthoringError
from igess.authoring.templates import initialize_authoring_project


def _blank_project(tmp_path: Path) -> AuthoringProject:
    root = initialize_authoring_project(tmp_path / "project", "export_test")
    return AuthoringProject.discover(root)


def test_stage_sources_copies_only_registered_authoritative_files(tmp_path: Path) -> None:
    project = _blank_project(tmp_path)
    (project.root / "notes.txt").write_text("not authoritative", encoding="utf-8")
    (project.datas / "unregistered.xlsx").write_bytes(b"not registered")
    (project.exports / "stale.json").write_text("[]", encoding="utf-8")
    for name in ("runs", "reports", "changes", ".igess"):
        directory = project.root / name
        directory.mkdir(exist_ok=True)
        (directory / "sentinel").write_text(name, encoding="utf-8")

    expected = {
        "economy.yaml",
        "Datas/__tables__.xlsx",
        "Datas/resources.xlsx",
        "Datas/generators.xlsx",
        "Datas/activities.xlsx",
        "Datas/activity_outputs.xlsx",
        "Datas/upgrades.xlsx",
        "Datas/constants.xlsx",
        "Datas/milestones.xlsx",
        "Datas/prestige_layers.xlsx",
    }

    staged = stage_sources(project, tmp_path / "transaction")

    actual_files = {
        path.relative_to(staged.root).as_posix()
        for path in staged.root.rglob("*")
        if path.is_file()
    }
    assert actual_files == expected
    assert staged.config == staged.root / "economy.yaml"
    assert staged.datas == staged.root / "Datas"
    assert staged.exports == staged.root / "luban_exports"
    assert staged.exports.is_dir()
    assert staged.source_paths == tuple(sorted(expected))
    assert staged.source_digest == project.model_digest()


def test_stage_sources_preserves_source_permission_bits(tmp_path: Path) -> None:
    project = _blank_project(tmp_path)
    source = project.config
    os.chmod(source, stat.S_IRUSR | stat.S_IWUSR)

    staged = stage_sources(project, tmp_path / "transaction")

    assert stat.S_IMODE(staged.config.stat().st_mode) == stat.S_IMODE(source.stat().st_mode)


def test_stage_sources_failure_cleans_only_its_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _blank_project(tmp_path)
    transaction = tmp_path / "transaction"
    transaction.mkdir()
    (transaction / "keep.txt").write_text("keep", encoding="utf-8")

    def fail_copy(*_args: object, **_kwargs: object) -> None:
        raise OSError("copy interrupted")

    monkeypatch.setattr(exports_module, "_copy_opened_source", fail_copy)

    with pytest.raises(OSError, match="copy interrupted"):
        stage_sources(project, transaction)

    assert not (transaction / "candidate").exists()
    assert (transaction / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert project.config.exists()


def test_stage_sources_rejects_source_changed_during_copy_and_cleans(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _blank_project(tmp_path)
    original_copy = exports_module._copy_opened_source

    def replace_config_after_copy(*args: object, **kwargs: object) -> None:
        original_copy(*args, **kwargs)
        destination = args[1]
        if Path(destination).name == "economy.yaml":
            project.config.write_bytes(project.config.read_bytes() + b"# drift\n")

    monkeypatch.setattr(exports_module, "_copy_opened_source", replace_config_after_copy)

    with pytest.raises(AuthoringError) as caught:
        stage_sources(project, tmp_path / "transaction")

    assert caught.value.details["reason"] == "source_identity_changed"
    assert not (tmp_path / "transaction" / "candidate").exists()


def _change(entity: str, entity_id: str, fields: dict[str, object]) -> ModelChange:
    return ModelChange(1, "upsert", entity, entity_id, fields)


def test_apply_to_candidate_dispatches_yaml_without_touching_original(tmp_path: Path) -> None:
    project = _blank_project(tmp_path)
    original = project.config.read_bytes()
    staged = stage_sources(project, tmp_path / "transaction")
    change = _change(
        "source_type",
        "manual",
        {"description": "Manual player actions"},
    )

    changed = apply_to_candidate(staged, change)

    assert changed == ("economy.yaml",)
    assert project.config.read_bytes() == original
    assert b"manual" in staged.config.read_bytes()
    assert apply_to_candidate(staged, change) == ()


def test_apply_to_candidate_rejects_retargeted_candidate_path(tmp_path: Path) -> None:
    project = _blank_project(tmp_path)
    original = project.config.read_bytes()
    staged = stage_sources(project, tmp_path / "transaction")
    object.__setattr__(staged, "config", project.config)

    with pytest.raises(AuthoringError) as caught:
        apply_to_candidate(
            staged,
            _change("source_type", "manual", {"description": "Manual actions"}),
        )

    assert caught.value.details["reason"] == "path_retargeted"
    assert project.config.read_bytes() == original


def test_apply_to_candidate_dispatches_canonical_workbook_without_touching_original(
    tmp_path: Path,
) -> None:
    project = _blank_project(tmp_path)
    original = (project.datas / "resources.xlsx").read_bytes()
    staged = stage_sources(project, tmp_path / "transaction")
    change = _change(
        "resource",
        "coins",
        {"name": "Coins", "dimension": "currency"},
    )

    changed = apply_to_candidate(staged, change)

    assert changed == ("Datas/resources.xlsx",)
    assert (project.datas / "resources.xlsx").read_bytes() == original
    assert (staged.datas / "resources.xlsx").read_bytes() != original
    assert apply_to_candidate(staged, change) == ()


_TABLE_CHANGES = (
    ("resource", "coins", {"name": "Coins", "dimension": "currency"}),
    (
        "generator",
        "mine",
        {
            "name": "Mine",
            "generator_type": "building",
            "output_resource": "coins",
            "source_type": "generator",
            "base_output": "0.125",
            "base_cost": "10.00",
            "cost_resource": "coins",
            "cost_growth": "1.15",
            "unlock_condition": "always",
        },
    ),
    (
        "activity",
        "tap",
        {
            "name": "Tap",
            "source_type": "active",
            "unlock_condition": "always",
        },
    ),
    (
        "activity_output",
        "tap_coins",
        {
            "activity_id": "tap",
            "output_resource": "coins",
            "amount_per_second": "2.500",
        },
    ),
    (
        "upgrade",
        "better_mine",
        {
            "name": "Better Mine",
            "target": "generator:mine.output",
            "modifier_type": "multiply",
            "value": "2.00",
            "cost_resource": "coins",
            "base_cost": "25.0",
            "unlock_condition": "always",
        },
    ),
    ("constant", "starter_coins", {"value": "100.000"}),
    (
        "milestone",
        "first_mine",
        {
            "name": "First Mine",
            "condition": "owned(mine) >= 1",
            "reward_resource": "coins",
            "reward_amount": "3.75",
        },
    ),
    (
        "prestige_layer",
        "rebirth",
        {
            "name": "Rebirth",
            "trigger_resource": "coins",
            "reward_resource": "coins",
            "formula": "prestige_gain",
            "divisor": "1000.00",
            "exponent": "0.5",
            "min_gain": "1.0",
            "reset_resources": ["coins"],
            "unlock_condition": "owned(mine) >= 10",
        },
    ),
)

_YAML_CHANGES = (
    ("formula", "linear", {"args": ["x"], "expr": "x + 1"}),
    (
        "generator_type",
        "manual_building",
        {"cost_formula": "exponential_cost", "production_formula": "generator_output"},
    ),
    ("source_type", "manual", {"description": "Manual action"}),
    ("modifier_type", "bonus", {"stage": "mult"}),
    ("behavior_policy", "idle", {"type": "cheap_unlock_first"}),
    (
        "session_pattern",
        "short",
        {"offline_every_seconds": 30, "offline_duration_seconds": 5},
    ),
    (
        "player_profile",
        "tester",
        {
            "source_efficiency": {"active": "1.0"},
            "behavior_policy": "idle",
            "session_pattern": "short",
            "prestige_policy": "conservative",
        },
    ),
    (
        "scenario",
        "tiny",
        {
            "duration_hours": "0.1",
            "time_mode": "tick",
            "profiles": ["tester"],
            "start_state": "new_player",
            "record_interval_seconds": 1,
            "outputs": ["resource_curve"],
        },
    ),
    (
        "rng_table",
        "loot",
        {"algorithm": "rarity_score", "rarities": {"common": "1", "rare": "10"}},
    ),
    (
        "rng_scenario",
        "loot_smoke",
        {"table": "loot", "rolls": 10, "trials": 3, "profiles": ["tester"]},
    ),
    ("regression_gate", "tiny", {"min_prestige_gain": {"default": "1"}}),
)


def test_apply_to_candidate_supports_every_yaml_entity(tmp_path: Path) -> None:
    project = _blank_project(tmp_path)
    staged = stage_sources(project, tmp_path / "transaction")

    changed = [
        apply_to_candidate(staged, _change(entity, entity_id, fields))
        for entity, entity_id, fields in _YAML_CHANGES
    ]

    assert changed == [("economy.yaml",)] * 11


def _populated_candidate(tmp_path: Path) -> tuple[AuthoringProject, object]:
    project = _blank_project(tmp_path)
    staged = stage_sources(project, tmp_path / "transaction")
    for entity, entity_id, fields in _TABLE_CHANGES:
        apply_to_candidate(staged, _change(entity, entity_id, fields))
    return project, staged


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_export_candidate_uses_real_eight_table_export_with_exact_source_metadata(
    tmp_path: Path,
) -> None:
    project, candidate = _populated_candidate(tmp_path)
    (project.exports / "committed.json").write_text("committed\n", encoding="utf-8")
    committed_before = _tree_bytes(project.exports)

    result = export_candidate(candidate, tmp_path / "runtime")

    assert _tree_bytes(project.exports) == committed_before
    assert result.root == tmp_path / "runtime"
    assert len(result.written_paths) == 8
    assert result.digest == compute_export_digest(result.root)
    expected = {
        "resources": ("coins", "resources.xlsx", {"name": "Coins"}),
        "generators": (
            "mine",
            "generators.xlsx",
            {"base_output": "0.125", "base_cost": "10.00", "cost_growth": "1.15"},
        ),
        "activities": ("tap", "activities.xlsx", {"name": "Tap"}),
        "activity_outputs": (
            "tap_coins",
            "activity_outputs.xlsx",
            {"amount_per_second": "2.500"},
        ),
        "upgrades": (
            "better_mine",
            "upgrades.xlsx",
            {"value": "2.00", "base_cost": "25.0"},
        ),
        "constants": ("starter_coins", "constants.xlsx", {"value": "100.000"}),
        "milestones": (
            "first_mine",
            "milestones.xlsx",
            {"reward_amount": "3.75"},
        ),
        "prestige_layers": (
            "rebirth",
            "prestige_layers.xlsx",
            {
                "divisor": "1000.00",
                "exponent": "0.5",
                "min_gain": "1.0",
                "reset_resources": ["coins"],
            },
        ),
    }
    for table, (entity_id, workbook, exact_fields) in expected.items():
        rows = json.loads((result.root / f"{table}.json").read_text(encoding="utf-8"))
        indexed = {row["id"]: row for row in rows}
        row = indexed[entity_id]
        for field, value in exact_fields.items():
            assert row[field] == value
        assert row["_source"] == {"table": table, "workbook": workbook, "row": 4}


def test_export_candidate_refuses_to_overwrite_project_committed_exports(
    tmp_path: Path,
) -> None:
    project, candidate = _populated_candidate(tmp_path)
    (project.exports / "committed.json").write_text("committed", encoding="utf-8")
    before = _tree_bytes(project.exports)

    with pytest.raises(AuthoringError) as caught:
        export_candidate(candidate, project.exports)

    assert caught.value.details["reason"] == "committed_export_target"
    assert _tree_bytes(project.exports) == before


def test_export_digest_is_order_independent_and_path_and_byte_sensitive(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "a.json").write_bytes(b"a")
    (first / "z.json").write_bytes(b"z")
    (second / "z.json").write_bytes(b"z")
    (second / "a.json").write_bytes(b"a")

    baseline = compute_export_digest(first)
    assert baseline == compute_export_digest(second)
    (second / "a.json").write_bytes(b"changed")
    assert baseline != compute_export_digest(second)
    (second / "a.json").write_bytes(b"a")
    (second / "z.json").rename(second / "y.json")
    assert baseline != compute_export_digest(second)


def test_export_digest_rejects_symlinks_and_enforces_file_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "exports"
    root.mkdir()
    (root / "a.json").write_text("[]", encoding="utf-8")
    link = root / "link.json"
    try:
        link.symlink_to(root / "a.json")
    except OSError as error:
        pytest.skip(f"filesystem symlinks are unavailable: {error}")
    with pytest.raises(AuthoringError) as caught:
        compute_export_digest(root)
    assert caught.value.details["reason"] == "unsafe_export_output"

    link.unlink()
    (root / "b.json").write_text("[]", encoding="utf-8")
    monkeypatch.setattr(exports_module, "_MAX_EXPORT_FILES", 1)
    with pytest.raises(AuthoringError) as caught:
        compute_export_digest(root)
    assert caught.value.details["reason"] == "export_budget_exceeded"


def test_export_candidate_rejects_same_byte_source_identity_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, candidate = _populated_candidate(tmp_path)
    real_exporter = exports_module.export_registered_workbooks

    def replace_after_export(datas: Path, output: Path) -> list[Path]:
        written = real_exporter(datas, output)
        content = candidate.config.read_bytes()
        replacement = candidate.config.with_suffix(".replacement")
        replacement.write_bytes(content)
        os.replace(replacement, candidate.config)
        return written

    monkeypatch.setattr(exports_module, "export_registered_workbooks", replace_after_export)

    with pytest.raises(AuthoringError) as caught:
        export_candidate(candidate, tmp_path / "runtime")

    assert caught.value.details["reason"] == "source_identity_changed"
    assert not (tmp_path / "runtime").exists()
    assert not list(tmp_path.glob(".runtime-export-*"))


def test_export_candidate_rejects_unreported_directory_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, candidate = _populated_candidate(tmp_path)

    def unexpected_directory(_datas: Path, output: Path) -> list[Path]:
        (output / "unexpected").mkdir()
        return []

    monkeypatch.setattr(exports_module, "export_registered_workbooks", unexpected_directory)
    with pytest.raises(AuthoringError) as caught:
        export_candidate(candidate, tmp_path / "runtime")
    assert caught.value.details["reason"] == "unexpected_export_output"


def test_export_candidate_cleans_partial_tree_on_base_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, candidate = _populated_candidate(tmp_path)

    class StopNow(BaseException):
        pass

    def interrupted(_datas: Path, output: Path) -> list[Path]:
        (output / "partial.json").write_text("[]", encoding="utf-8")
        raise StopNow

    monkeypatch.setattr(exports_module, "export_registered_workbooks", interrupted)
    with pytest.raises(StopNow):
        export_candidate(candidate, tmp_path / "runtime")
    assert not (tmp_path / "runtime").exists()
    assert not list(tmp_path.glob(".runtime-export-*"))


def test_export_failure_removes_partial_new_output_and_preserves_existing_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, candidate = _populated_candidate(tmp_path)
    out = tmp_path / "runtime"
    out.mkdir()
    (out / "old.json").write_text("old", encoding="utf-8")

    def fail_after_partial(_datas: Path, output: Path) -> list[Path]:
        (output / "partial.json").write_text("[]", encoding="utf-8")
        raise ValueError("broken export")

    monkeypatch.setattr(exports_module, "export_registered_workbooks", fail_after_partial)

    with pytest.raises(AuthoringError) as caught:
        export_candidate(candidate, out)

    assert caught.value.code == "authoring_export_failed"
    assert caught.value.details["reason"] == "exporter_error"
    assert _tree_bytes(out) == {"old.json": b"old"}
    assert not list(tmp_path.glob(".runtime-export-*"))


def test_ephemeral_export_lives_until_exit_and_always_cleans(tmp_path: Path) -> None:
    project = _blank_project(tmp_path)
    (project.exports / "committed.json").write_text("committed", encoding="utf-8")
    committed_before = _tree_bytes(project.exports)
    retained_root: Path

    with ephemeral_export(project) as result:
        retained_root = result.workspace
        assert result.workspace.exists()
        assert result.candidate_config.exists()
        assert result.candidate_datas.exists()
        assert result.export_root.exists()
        assert result.export_digest == compute_export_digest(result.export_root)

    assert not retained_root.exists()
    assert _tree_bytes(project.exports) == committed_before

    interrupted_root: Path | None = None

    class StopNow(BaseException):
        pass

    with pytest.raises(StopNow):
        with ephemeral_export(project) as result:
            interrupted_root = result.workspace
            raise StopNow
    assert interrupted_root is not None
    assert not interrupted_root.exists()
    assert _tree_bytes(project.exports) == committed_before
