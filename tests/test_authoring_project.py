from __future__ import annotations

from dataclasses import FrozenInstanceError
import hashlib
from pathlib import Path
import re
import shutil

from openpyxl import Workbook, load_workbook
import pytest

from igess.authoring import AuthoringProject
from igess.authoring.response import AuthoringError


def _write_registry(datas: Path, paths: list[object]) -> Path:
    datas.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["##var", "table", "path", "mode", "key"])
    sheet.append(["##", None, None, None, None])
    sheet.append(["##type", "string", "string", "string", "string"])
    for index, path in enumerate(paths):
        sheet.append([None, f"table_{index}", path, "map", "id"])
    registry = datas / "__tables__.xlsx"
    workbook.save(registry)
    return registry


def _make_project(root: Path, paths: list[str] | None = None) -> AuthoringProject:
    root.mkdir(parents=True, exist_ok=True)
    (root / "economy.yaml").write_text("version: 1\n", encoding="utf-8")
    registrations = paths if paths is not None else ["resources.xlsx"]
    _write_registry(root / "Datas", registrations)
    for path in registrations:
        workbook_path = root / "Datas" / path
        workbook_path.parent.mkdir(parents=True, exist_ok=True)
        workbook_path.write_bytes(f"workbook:{path}".encode("utf-8"))
    (root / "luban_exports").mkdir()
    return AuthoringProject.discover(root)


def _expected_digest(root: Path, paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return f"sha256:{digest.hexdigest()}"


def test_discover_returns_frozen_canonical_direct_child_paths(tmp_path: Path) -> None:
    requested = tmp_path / "wrapper" / ".." / "model"
    project = _make_project(tmp_path / "model")
    discovered = AuthoringProject.discover(requested)
    root = (tmp_path / "model").resolve()

    assert discovered == project
    assert discovered.root == root
    assert discovered.config == root / "economy.yaml"
    assert discovered.datas == root / "Datas"
    assert discovered.exports == root / "luban_exports"
    assert discovered.runs == root / "runs"
    assert discovered.legacy_runs == root / ".igess" / "runs"
    assert discovered.reports == root / "reports"
    assert discovered.changes == root / "changes"
    assert discovered.transactions == root / ".igess" / "transactions"
    assert discovered.lock == root / ".igess" / "model.lock"
    with pytest.raises(FrozenInstanceError):
        discovered.root = tmp_path  # type: ignore[misc]


def test_discovery_does_not_search_descendants(tmp_path: Path) -> None:
    _make_project(tmp_path / "outer" / "nested")

    with pytest.raises(AuthoringError) as captured:
        AuthoringProject.discover(tmp_path / "outer")

    assert captured.value.code == "project_config_missing"
    assert captured.value.details == {
        "expected": "file",
        "path": str((tmp_path / "outer" / "economy.yaml").resolve()),
        "reason": "missing",
        "role": "project config",
    }


@pytest.mark.parametrize(
    ("name", "expected", "role", "missing_code", "wrong_type_code"),
    [
        ("economy.yaml", "file", "project config", "project_config_missing", "project_config_wrong_type"),
        ("Datas", "directory", "source tables", "source_tables_missing", "source_tables_wrong_type"),
        (
            "luban_exports",
            "directory",
            "runtime exports",
            "runtime_exports_missing",
            "runtime_exports_wrong_type",
        ),
    ],
)
def test_discovery_reports_each_missing_and_wrong_type_role(
    tmp_path: Path,
    name: str,
    expected: str,
    role: str,
    missing_code: str,
    wrong_type_code: str,
) -> None:
    root = tmp_path / name.replace(".", "-")
    _make_project(root)
    candidate = root / name
    if candidate.is_dir():
        shutil.rmtree(candidate)
    else:
        candidate.unlink()

    with pytest.raises(AuthoringError) as missing:
        AuthoringProject.discover(root)
    assert missing.value.code == missing_code
    assert missing.value.details == {
        "expected": expected,
        "path": str(candidate.resolve()),
        "reason": "missing",
        "role": role,
    }

    if expected == "file":
        candidate.mkdir()
    else:
        candidate.write_text("not a directory", encoding="utf-8")
    with pytest.raises(AuthoringError) as wrong_type:
        AuthoringProject.discover(root)
    assert wrong_type.value.code == wrong_type_code
    assert wrong_type.value.details["role"] == role
    assert wrong_type.value.details["reason"] == "wrong_type"
    assert wrong_type.value.details["expected"] == expected
    assert wrong_type.value.details["path"] == str(candidate.resolve())


def test_read_run_roots_returns_only_existing_directories_in_modern_first_order(
    tmp_path: Path,
) -> None:
    project = _make_project(tmp_path / "model")
    assert project.read_run_roots() == []

    project.legacy_runs.mkdir(parents=True)
    assert project.read_run_roots() == [project.legacy_runs]

    project.runs.mkdir()
    assert project.read_run_roots() == [project.runs, project.legacy_runs]

    project.legacy_runs.rmdir()
    project.legacy_runs.write_text("not a directory", encoding="utf-8")
    assert project.read_run_roots() == [project.runs]


def test_read_run_roots_deduplicates_directory_aliases(tmp_path: Path) -> None:
    project = _make_project(tmp_path / "model")
    project.runs.mkdir()
    project.legacy_runs.parent.mkdir()
    try:
        project.legacy_runs.symlink_to(project.runs, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"directory symlinks are unavailable: {error}")

    assert project.read_run_roots() == [project.runs]


def test_model_digest_hashes_canonical_sorted_registered_sources_exactly(tmp_path: Path) -> None:
    project = _make_project(tmp_path / "model", ["zeta.xlsx", "nested/alpha.xlsx"])
    expected_paths = [
        project.config,
        project.datas / "__tables__.xlsx",
        project.datas / "zeta.xlsx",
        project.datas / "nested" / "alpha.xlsx",
    ]

    value = project.model_digest()

    assert value == _expected_digest(project.root, expected_paths)
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", value)
    assert project.model_digest() == value


def test_model_digest_changes_for_config_registry_and_registered_workbook(tmp_path: Path) -> None:
    project = _make_project(tmp_path / "model", ["resources.xlsx"])
    original = project.model_digest()

    project.config.write_text("version: 2\n", encoding="utf-8")
    config_changed = project.model_digest()
    assert config_changed != original

    project.datas.joinpath("resources.xlsx").write_bytes(b"changed source")
    source_changed = project.model_digest()
    assert source_changed != config_changed

    registry = load_workbook(project.datas / "__tables__.xlsx")
    registry.active["B4"] = "renamed_table"
    registry.save(project.datas / "__tables__.xlsx")
    assert project.model_digest() != source_changed


def test_model_digest_ignores_unregistered_and_derived_artifacts(tmp_path: Path) -> None:
    project = _make_project(tmp_path / "model", ["resources.xlsx"])
    original = project.model_digest()

    ignored_files = [
        project.datas / "unregistered.xlsx",
        project.exports / "resources.json",
        project.runs / "run-1" / "status.json",
        project.reports / "index.html",
        project.changes / "change-1.json",
        project.transactions / "tx-1" / "journal.json",
        project.lock,
    ]
    for index, path in enumerate(ignored_files):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"ignored:{index}".encode("utf-8"))

    assert project.model_digest() == original


@pytest.mark.parametrize(
    ("registrations", "reason"),
    [
        ([None], "missing_registration_path"),
        (["../outside.xlsx"], "unsafe_registration_path"),
        (["missing.xlsx"], "registered_source_missing"),
        (["one.xlsx", "./one.xlsx"], "duplicate_registration_path"),
    ],
)
def test_model_digest_rejects_invalid_registration_paths(
    tmp_path: Path,
    registrations: list[object],
    reason: str,
) -> None:
    root = tmp_path / reason
    root.mkdir()
    (root / "economy.yaml").write_text("version: 1\n", encoding="utf-8")
    _write_registry(root / "Datas", registrations)
    (root / "Datas" / "one.xlsx").write_bytes(b"one")
    (root / "luban_exports").mkdir()
    project = AuthoringProject.discover(root)

    with pytest.raises(AuthoringError) as captured:
        project.model_digest()

    assert captured.value.code == "invalid_source_registry"
    assert captured.value.details["reason"] == reason
    assert captured.value.details["role"] == "source registry"
    assert isinstance(captured.value.details["path"], str)


def test_model_digest_rejects_absolute_duplicate_and_wrong_type_sources(tmp_path: Path) -> None:
    root = tmp_path / "model"
    project = _make_project(root, ["source.xlsx"])

    _write_registry(project.datas, [str((tmp_path / "outside.xlsx").resolve())])
    with pytest.raises(AuthoringError) as absolute:
        project.model_digest()
    assert absolute.value.details["reason"] == "unsafe_registration_path"

    _write_registry(project.datas, ["source.xlsx", "SOURCE.xlsx"])
    with pytest.raises(AuthoringError) as duplicate:
        project.model_digest()
    assert duplicate.value.details["reason"] == "duplicate_registration_path"

    _write_registry(project.datas, ["directory.xlsx"])
    (project.datas / "directory.xlsx").mkdir()
    with pytest.raises(AuthoringError) as wrong_type:
        project.model_digest()
    assert wrong_type.value.details["reason"] == "registered_source_wrong_type"


def test_model_digest_wraps_missing_or_malformed_registry_as_structured_error(tmp_path: Path) -> None:
    project = _make_project(tmp_path / "model")
    registry = project.datas / "__tables__.xlsx"
    registry.unlink()

    with pytest.raises(AuthoringError) as missing:
        project.model_digest()
    assert missing.value.code == "invalid_source_registry"
    assert missing.value.details == {
        "path": str(registry),
        "reason": "registry_missing",
        "role": "source registry",
    }

    registry.write_text("not an xlsx file", encoding="utf-8")
    with pytest.raises(AuthoringError) as malformed:
        project.model_digest()
    assert malformed.value.code == "invalid_source_registry"
    assert malformed.value.details["reason"] == "malformed_registry"
    assert isinstance(malformed.value.details["error_type"], str)
    assert all(isinstance(value, (str, int, bool)) or value is None for value in malformed.value.details.values())
