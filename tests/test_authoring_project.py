from __future__ import annotations

from dataclasses import FrozenInstanceError
import hashlib
import io
import os
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


def _write_registry_rows(datas: Path, headers: list[object], rows: list[list[object]]) -> Path:
    datas.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["##var", *headers])
    sheet.append(["##", *([None] * len(headers))])
    sheet.append(["##type", *(["string"] * len(headers))])
    for row in rows:
        sheet.append([None, *row])
    registry = datas / "__tables__.xlsx"
    workbook.save(registry)
    return registry


def _symlink_or_skip(link: Path, target: Path, *, is_directory: bool) -> None:
    try:
        link.symlink_to(target, target_is_directory=is_directory)
    except OSError as error:
        pytest.skip(f"filesystem symlinks are unavailable: {error}")


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


def test_direct_construction_canonicalizes_root_and_derives_every_path(tmp_path: Path) -> None:
    discovered = _make_project(tmp_path / "model")

    constructed = AuthoringProject(tmp_path / "wrapper" / ".." / "model")

    assert constructed == discovered
    assert all(
        isinstance(getattr(constructed, field), Path)
        for field in (
            "root",
            "config",
            "datas",
            "exports",
            "runs",
            "legacy_runs",
            "reports",
            "changes",
            "transactions",
            "lock",
        )
    )


def test_direct_construction_rejects_invalid_root_without_leaking_attribute_errors() -> None:
    with pytest.raises(TypeError, match="root"):
        AuthoringProject(object())  # type: ignore[arg-type]


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
    ("name", "is_directory", "code", "role"),
    [
        ("economy.yaml", False, "project_config_unsafe", "project config"),
        ("Datas", True, "source_tables_unsafe", "source tables"),
        ("luban_exports", True, "runtime_exports_unsafe", "runtime exports"),
    ],
)
def test_discovery_rejects_required_child_symlinks_outside_root(
    tmp_path: Path,
    name: str,
    is_directory: bool,
    code: str,
    role: str,
) -> None:
    root = tmp_path / "model"
    _make_project(root)
    candidate = root / name
    if candidate.is_dir():
        shutil.rmtree(candidate)
    else:
        candidate.unlink()
    outside = tmp_path / f"outside-{name.replace('.', '-')}"
    if is_directory:
        outside.mkdir()
    else:
        outside.write_text("version: 1\n", encoding="utf-8")
    _symlink_or_skip(candidate, outside, is_directory=is_directory)

    with pytest.raises(AuthoringError) as captured:
        AuthoringProject.discover(root)

    assert captured.value.code == code
    assert captured.value.details["reason"] == "outside_root"
    assert captured.value.details["role"] == role
    assert captured.value.details["path"] == str(candidate)
    assert captured.value.details["resolved_path"] == str(outside.resolve())


def test_discovery_rejects_required_child_target_that_is_not_direct(tmp_path: Path) -> None:
    root = tmp_path / "model"
    _make_project(root)
    project_config = root / "economy.yaml"
    project_config.unlink()
    nested_config = root / "nested" / "economy.yaml"
    nested_config.parent.mkdir()
    nested_config.write_text("version: 1\n", encoding="utf-8")
    _symlink_or_skip(project_config, nested_config, is_directory=False)

    with pytest.raises(AuthoringError) as captured:
        AuthoringProject.discover(root)

    assert captured.value.code == "project_config_unsafe"
    assert captured.value.details["reason"] == "not_direct_child"


def test_model_digest_rejects_config_retargeted_outside_root(tmp_path: Path) -> None:
    project = _make_project(tmp_path / "model")
    outside = tmp_path / "outside.yaml"
    outside.write_text("secret: true\n", encoding="utf-8")
    project.config.unlink()
    _symlink_or_skip(project.config, outside, is_directory=False)

    with pytest.raises(AuthoringError) as captured:
        project.model_digest()

    assert captured.value.code == "project_config_unsafe"
    assert captured.value.details["reason"] == "outside_root"


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


def test_read_run_roots_skips_paths_that_cannot_be_resolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _make_project(tmp_path / "model")
    project.runs.mkdir()
    project.legacy_runs.mkdir(parents=True)
    original_resolve = Path.resolve

    def flaky_resolve(path: Path, *args: object, **kwargs: object) -> Path:
        if path == project.runs:
            raise OSError("retargeted while reading")
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", flaky_resolve)

    assert project.read_run_roots() == [project.legacy_runs]


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


def test_model_digest_streams_files_with_fixed_bounded_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _make_project(tmp_path / "model")
    project.config.write_bytes(b"x" * (3 * 1024 * 1024 + 17))
    expected = project.model_digest()
    original_open = Path.open
    read_sizes: list[int] = []

    class TrackingReader:
        def __init__(self, payload: bytes) -> None:
            self._stream = io.BytesIO(payload)

        def __enter__(self) -> TrackingReader:
            return self

        def __exit__(self, *args: object) -> None:
            self._stream.close()

        def read(self, size: int = -1) -> bytes:
            read_sizes.append(size)
            assert size > 0
            return self._stream.read(size)

    payload = project.config.read_bytes()

    def tracking_open(path: Path, *args: object, **kwargs: object) -> object:
        if path == project.config:
            return TrackingReader(payload)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", tracking_open)

    assert project.model_digest() == expected
    assert len(read_sizes) > 2
    assert len(set(read_sizes)) == 1


def test_model_digest_converts_memory_error_to_structured_diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _make_project(tmp_path / "model")
    original_open = Path.open

    class ExhaustedReader:
        def __enter__(self) -> ExhaustedReader:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self, size: int = -1) -> bytes:
            raise MemoryError("simulated allocation failure")

    def exhausted_open(path: Path, *args: object, **kwargs: object) -> object:
        if path == project.config:
            return ExhaustedReader()
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", exhausted_open)

    with pytest.raises(AuthoringError) as captured:
        project.model_digest()

    assert captured.value.code == "project_config_unreadable"
    assert captured.value.details["reason"] == "source_read_error"
    assert captured.value.details["error_type"] == "MemoryError"


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


@pytest.mark.parametrize(
    ("headers", "row", "header_issue"),
    [
        (["path", "mode", "key"], ["source.xlsx", "map", "id"], "missing_required_header"),
        (
            ["table", "table", "path"],
            ["resources", "resources_copy", "source.xlsx"],
            "duplicate_header",
        ),
        (
            ["table", "path", "path"],
            ["resources", "source.xlsx", "source.xlsx"],
            "duplicate_header",
        ),
        (
            ["table", "path", "mode", "mode"],
            ["resources", "source.xlsx", "map", "map"],
            "duplicate_header",
        ),
    ],
)
def test_model_digest_rejects_missing_or_duplicate_registry_headers(
    tmp_path: Path,
    headers: list[object],
    row: list[object],
    header_issue: str,
) -> None:
    project = _make_project(tmp_path / "model", ["source.xlsx"])
    _write_registry_rows(project.datas, headers, [row])

    with pytest.raises(AuthoringError) as captured:
        project.model_digest()

    assert captured.value.code == "invalid_source_registry"
    assert captured.value.details["reason"] == "malformed_registry"
    assert captured.value.details["header_issue"] == header_issue


def test_model_digest_rejects_hard_linked_duplicate_registrations(tmp_path: Path) -> None:
    project = _make_project(tmp_path / "model", ["source.xlsx"])
    alias = project.datas / "alias.xlsx"
    try:
        os.link(project.datas / "source.xlsx", alias)
    except OSError as error:
        pytest.skip(f"filesystem hard links are unavailable: {error}")
    _write_registry(project.datas, ["source.xlsx", "alias.xlsx"])

    with pytest.raises(AuthoringError) as captured:
        project.model_digest()

    assert captured.value.code == "invalid_source_registry"
    assert captured.value.details["reason"] == "duplicate_registration_path"


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
