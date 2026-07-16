from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from igess.authoring import AuthoringProject
from igess.authoring.templates import initialize_authoring_project
from igess import run_registry as registry_module
from igess.run_registry import RunRecord, RunRegistry


_DIGEST = "sha256:" + "a" * 64


def _paths(run_dir: Path) -> dict[str, Path]:
    return {
        "output_dir": run_dir / "output",
        "report_dir": run_dir / "report",
        "report_index": run_dir / "report" / "index.html",
    }


def _write(
    registry: RunRegistry,
    run_id: str,
    *,
    kind: str,
    status: str = "success",
    change_id: str | None = None,
    digest: str = _DIGEST,
) -> RunRecord:
    run_dir = registry.runs_root / run_id
    return registry.write_status(
        run_dir,
        status=status,
        scenario_id="smoke" if kind == "smoke" else "day_1",
        message=f"{kind} {status}",
        kind=kind,
        change_id=change_id,
        model_digest=digest,
        **_paths(run_dir),
    )


def test_authoring_status_is_schema_versioned_and_attributable(tmp_path: Path) -> None:
    registry = RunRegistry(tmp_path / "runs")
    run_dir = registry.new_run_dir("smoke", kind="smoke", change_id="rule-1")

    record = registry.write_status(
        run_dir,
        status="success",
        scenario_id="smoke",
        message="Probe complete",
        kind="smoke",
        change_id="rule-1",
        model_digest=_DIGEST,
        **_paths(run_dir),
    )

    payload = json.loads(record.status_path.read_text(encoding="utf-8"))
    assert payload == {
        "change_id": "rule-1",
        "kind": "smoke",
        "message": "Probe complete",
        "model_digest": _DIGEST,
        "output_dir": str(run_dir / "output"),
        "report_dir": str(run_dir / "report"),
        "report_index": str(run_dir / "report" / "index.html"),
        "run_id": run_dir.name,
        "scenario_id": "smoke",
        "status": "success",
        "version": 1,
    }
    assert record.version == 1
    assert record.kind == "smoke"
    assert record.change_id == "rule-1"
    assert record.model_digest == _DIGEST


def test_authoring_status_accepts_the_canonical_project_model_digest(tmp_path: Path) -> None:
    project_root = initialize_authoring_project(tmp_path / "model")
    project = AuthoringProject.discover(project_root)
    digest = project.model_digest()
    registry = RunRegistry(project.runs)
    run_dir = registry.new_run_dir("day_1", kind="formal")

    record = registry.write_status(
        run_dir,
        status="success",
        scenario_id="day_1",
        message="Formal run complete",
        kind="formal",
        model_digest=digest,
        **_paths(run_dir),
    )

    assert digest.startswith("sha256:")
    assert record.model_digest == digest
    assert registry.list_runs() == [record]


@pytest.mark.parametrize("kind", ["smoke", "formal", "advice"])
def test_new_authoring_status_requires_a_model_digest(tmp_path: Path, kind: str) -> None:
    registry = RunRegistry(tmp_path / "runs")
    run_dir = registry.runs_root / "20260715T010203000000Z-run"

    with pytest.raises(ValueError, match="model_digest"):
        registry.write_status(
            run_dir,
            status="success",
            scenario_id="smoke",
            message="done",
            kind=kind,
            change_id="rule-1" if kind == "smoke" else None,
            model_digest=None,
            **_paths(run_dir),
        )
    assert not run_dir.exists()


def test_authoring_status_rejects_a_bare_hex_digest(tmp_path: Path) -> None:
    registry = RunRegistry(tmp_path / "runs")
    run_dir = registry.runs_root / "20260715T010203000000Z-run"

    with pytest.raises(ValueError, match="sha256:<64 lowercase hex>"):
        registry.write_status(
            run_dir,
            status="success",
            scenario_id="day_1",
            message="done",
            kind="formal",
            model_digest="a" * 64,
            **_paths(run_dir),
        )
    assert not run_dir.exists()


def test_legacy_status_loads_with_compatibility_defaults_and_paths(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    run_dir = root / "20260715T010203000000Z-day_1"
    run_dir.mkdir(parents=True)
    payload = {
        "run_id": run_dir.name,
        "status": "success",
        "scenario_id": "day_1",
        "message": "legacy",
        "output_dir": str(run_dir / "old-output"),
        "report_dir": str(run_dir / "old-report"),
        "report_index": str(run_dir / "old-report" / "home.html"),
    }
    (run_dir / "run_status.json").write_text(json.dumps(payload), encoding="utf-8")

    [record] = RunRegistry(root).list_runs()

    assert record.version is None
    assert record.kind == "formal"
    assert record.change_id is None
    assert record.model_digest is None
    assert record.run_dir == run_dir
    assert record.output_dir == Path(payload["output_dir"])
    assert record.report_dir == Path(payload["report_dir"])
    assert record.report_index == Path(payload["report_index"])


def test_run_record_new_fields_have_backward_compatible_defaults(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    record = RunRecord(
        "run",
        "success",
        "day_1",
        "done",
        run_dir,
        run_dir / "output",
        run_dir / "report",
        run_dir / "report" / "index.html",
        run_dir / "run_status.json",
    )

    assert record.version is None
    assert record.kind == "formal"
    assert record.change_id is None
    assert record.model_digest is None


def test_new_run_ids_distinguish_automatic_smoke_from_scenario_runs(tmp_path: Path) -> None:
    registry = RunRegistry(tmp_path / "runs")

    formal = registry.new_run_dir("day 1", kind="formal")
    advice = registry.new_run_dir("advice_day 1", kind="advice")
    smoke = registry.new_run_dir("smoke", kind="smoke", change_id="rule_1")

    assert formal.name.endswith("-day_1")
    assert advice.name.endswith("-advice_day_1")
    assert smoke.name.endswith("-smoke-rule_1")


def test_list_runs_merges_roots_with_modern_duplicate_precedence(tmp_path: Path) -> None:
    modern = tmp_path / "runs"
    legacy = tmp_path / ".igess" / "runs"
    modern_registry = RunRegistry(modern)
    legacy_registry = RunRegistry(legacy)
    duplicate = "20260715T010203000000Z-day_1"
    modern_record = _write(modern_registry, duplicate, kind="formal", status="success")
    _write(legacy_registry, duplicate, kind="formal", status="failed")
    legacy_only = _write(
        legacy_registry,
        "20260715T010204000000Z-day_2",
        kind="advice",
        status="failed",
    )

    records = RunRegistry(modern, read_roots=[modern, legacy]).list_runs()

    assert [(record.run_id, record.status) for record in records] == [
        (duplicate, "success"),
        (legacy_only.run_id, "failed"),
    ]
    assert records[0].status_path == modern_record.status_path


def test_latest_smoke_uses_merged_history(tmp_path: Path) -> None:
    modern = tmp_path / "runs"
    legacy = tmp_path / ".igess" / "runs"
    old = _write(
        RunRegistry(legacy),
        "20260715T010203000000Z-smoke-old",
        kind="smoke",
        change_id="old",
    )
    new = _write(
        RunRegistry(modern),
        "20260715T010204000000Z-smoke-new",
        kind="smoke",
        change_id="new",
    )
    registry = RunRegistry(modern, read_roots=[legacy])

    assert registry.latest_smoke() == new
    assert registry.latest(kind="smoke") == new
    assert old in registry.list_runs()


def test_prune_smoke_keeps_newest_twenty_and_never_other_kinds(tmp_path: Path) -> None:
    registry = RunRegistry(tmp_path / "runs")
    smoke_ids: list[str] = []
    for index in range(22):
        run_id = f"20260715T{index:06d}000000Z-smoke-rule-{index:02d}"
        smoke_ids.append(run_id)
        _write(
            registry,
            run_id,
            kind="smoke",
            status="success" if index % 2 else "failed",
            change_id=f"rule-{index:02d}",
        )
    formal_ids = [f"20260716T00000{i}000000Z-day_{i}" for i in range(2)]
    advice_ids = [f"20260717T00000{i}000000Z-advice_day_{i}" for i in range(2)]
    for index, run_id in enumerate(formal_ids):
        _write(registry, run_id, kind="formal", status="success" if index else "failed")
    for index, run_id in enumerate(advice_ids):
        _write(registry, run_id, kind="advice", status="failed" if index else "success")

    deleted = registry.prune_smoke(keep=20)

    assert deleted == smoke_ids[:2]
    assert [run_id for run_id in smoke_ids if (registry.runs_root / run_id).exists()] == smoke_ids[2:]
    assert all((registry.runs_root / run_id).is_dir() for run_id in formal_ids + advice_ids)


def test_list_runs_skips_corrupt_or_unsafe_records_without_losing_valid_history(
    tmp_path: Path,
) -> None:
    registry = RunRegistry(tmp_path / "runs")
    valid = _write(
        registry,
        "20260715T010203000000Z-day_1",
        kind="formal",
    )
    corrupt = registry.runs_root / "20260715T010204000000Z-corrupt"
    corrupt.mkdir()
    (corrupt / "run_status.json").write_text("{", encoding="utf-8")
    unsafe = registry.runs_root / "20260715T010205000000Z-unsafe"
    unsafe.mkdir()
    (unsafe / "run_status.json").write_text(
        json.dumps(
            {
                "version": 1,
                "run_id": unsafe.name,
                "status": "success",
                "scenario_id": "day_1",
                "message": "unsafe",
                "kind": "formal",
                "change_id": None,
                "model_digest": _DIGEST,
                "output_dir": str(tmp_path / "outside"),
                "report_dir": str(tmp_path / "outside"),
                "report_index": str(tmp_path / "outside" / "index.html"),
            }
        ),
        encoding="utf-8",
    )

    assert registry.list_runs() == [valid]


@pytest.mark.parametrize("version", [True, 1.0])
def test_version_requires_the_exact_integer_one(tmp_path: Path, version: object) -> None:
    registry = RunRegistry(tmp_path / "runs")
    record = _write(
        registry,
        "20260715T010203000000Z-day_1",
        kind="formal",
    )
    payload = json.loads(record.status_path.read_text(encoding="utf-8"))
    payload["version"] = version
    record.status_path.write_text(json.dumps(payload), encoding="utf-8")

    assert registry.list_runs() == []


def test_write_status_refuses_status_symlink_without_touching_target(tmp_path: Path) -> None:
    registry = RunRegistry(tmp_path / "runs")
    run_dir = registry.runs_root / "20260715T010203000000Z-day_1"
    run_dir.mkdir(parents=True)
    outside = tmp_path / "outside.json"
    outside.write_text("outside-must-stay", encoding="utf-8")
    status_path = run_dir / "run_status.json"
    try:
        status_path.symlink_to(outside)
    except OSError as error:
        pytest.skip(f"file links unavailable: {error}")

    with pytest.raises(ValueError, match="link|reparse"):
        registry.write_status(
            run_dir,
            status="success",
            scenario_id="day_1",
            message="done",
            kind="formal",
            model_digest=_DIGEST,
            **_paths(run_dir),
        )

    assert outside.read_text(encoding="utf-8") == "outside-must-stay"
    assert status_path.is_symlink()
    assert not list(run_dir.glob(".run_status.*.tmp"))


def test_write_status_replace_failure_preserves_old_status_and_cleans_temp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = RunRegistry(tmp_path / "runs")
    record = _write(
        registry,
        "20260715T010203000000Z-day_1",
        kind="formal",
    )
    before = record.status_path.read_bytes()
    original_replace = os.replace

    def failing_replace(source: object, destination: object, *args: object, **kwargs: object):
        if Path(destination).name == record.status_path.name:
            raise OSError("injected replace failure")
        return original_replace(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, "replace", failing_replace)

    with pytest.raises(OSError, match="injected replace failure"):
        registry.write_status(
            record.run_dir,
            status="failed",
            scenario_id="day_1",
            message="new status",
            kind="formal",
            model_digest=_DIGEST,
            **_paths(record.run_dir),
        )

    assert record.status_path.read_bytes() == before
    assert not list(record.run_dir.glob(".run_status.*.tmp"))


def test_write_status_parent_swap_never_writes_payload_or_temp_outside_registry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = RunRegistry(tmp_path / "runs")
    run_dir = registry.runs_root / "20260715T010203000000Z-day_1"
    run_dir.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    displaced = registry.runs_root / ".displaced-run"
    original_open = registry_module._open_exclusive_regular
    swapped = False

    def swapping_open(path: Path, *args: object, **kwargs: object) -> int:
        nonlocal swapped
        if not swapped:
            swapped = True
            os.replace(run_dir, displaced)
            try:
                run_dir.symlink_to(outside, target_is_directory=True)
            except OSError as error:
                pytest.skip(f"directory links unavailable: {error}")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(registry_module, "_open_exclusive_regular", swapping_open)

    with pytest.raises(ValueError, match="changed|outside|parent"):
        registry.write_status(
            run_dir,
            status="success",
            scenario_id="day_1",
            message="PAYLOAD-MUST-NOT-ESCAPE",
            kind="formal",
            model_digest=_DIGEST,
            **_paths(run_dir),
        )

    assert swapped
    assert list(outside.iterdir()) == []
    assert all(
        b"PAYLOAD-MUST-NOT-ESCAPE" not in path.read_bytes()
        for path in displaced.iterdir()
        if path.is_file()
    )


def test_status_read_rejects_leaf_retargeted_after_its_single_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = RunRegistry(tmp_path / "runs")
    record = _write(
        registry,
        "20260715T010203000000Z-day_1",
        kind="formal",
    )
    replacement = record.run_dir / "replacement.json"
    replacement.write_bytes(record.status_path.read_bytes())
    original_open = os.open
    swapped = False
    status_opens = 0

    def swapping_open(path: object, flags: int, mode: int = 0o777, *, dir_fd=None):
        nonlocal status_opens, swapped
        fd = original_open(path, flags, mode, dir_fd=dir_fd)
        if Path(path) == record.status_path:
            status_opens += 1
            if not swapped:
                swapped = True
                os.replace(replacement, record.status_path)
        return fd

    monkeypatch.setattr(os, "open", swapping_open)

    assert registry.list_runs() == []
    assert swapped
    assert status_opens == 1


def test_status_read_is_bounded_when_file_grows_after_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = RunRegistry(tmp_path / "runs")
    record = _write(
        registry,
        "20260715T010203000000Z-day_1",
        kind="formal",
    )
    original_read = os.read
    requested = 0
    grown = False

    def growing_read(fd: int, size: int) -> bytes:
        nonlocal grown, requested
        requested += size
        if not grown:
            grown = True
            with record.status_path.open("ab") as stream:
                stream.write(b" " * (registry_module._MAX_STATUS_BYTES + 1))
        return original_read(fd, size)

    monkeypatch.setattr(os, "read", growing_read)

    assert registry.list_runs() == []
    assert grown
    assert requested <= registry_module._MAX_STATUS_BYTES + 1


def test_prune_smoke_refuses_a_linked_run_directory(tmp_path: Path) -> None:
    registry = RunRegistry(tmp_path / "runs")
    real = tmp_path / "outside-run"
    real.mkdir()
    linked = registry.runs_root / "20260715T010203000000Z-smoke-rule"
    registry.runs_root.mkdir(parents=True)
    try:
        linked.symlink_to(real, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"directory links unavailable: {error}")
    (real / "run_status.json").write_text(
        json.dumps(
            {
                "version": 1,
                "run_id": linked.name,
                "status": "success",
                "scenario_id": "smoke",
                "message": "unsafe",
                "kind": "smoke",
                "change_id": "rule",
                "model_digest": _DIGEST,
                "output_dir": str(real / "output"),
                "report_dir": str(real / "report"),
                "report_index": str(real / "report" / "index.html"),
            }
        ),
        encoding="utf-8",
    )

    registry.prune_smoke(keep=0)

    assert linked.exists()
    assert (real / "run_status.json").exists()


def test_prune_smoke_does_not_delete_a_formal_directory_swapped_during_quarantine(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = RunRegistry(tmp_path / "runs")
    smoke = _write(
        registry,
        "20260715T010203000000Z-smoke-rule",
        kind="smoke",
        change_id="rule",
    )
    formal = _write(
        registry,
        "20260715T010204000000Z-day_1",
        kind="formal",
    )
    (smoke.run_dir / "smoke.marker").write_text("smoke", encoding="utf-8")
    (formal.run_dir / "formal.marker").write_text("formal", encoding="utf-8")
    original_replace = os.replace
    raced = False

    def racing_replace(source: object, destination: object, *args: object, **kwargs: object):
        nonlocal raced
        source_path = Path(source)
        destination_path = Path(destination)
        if (
            not raced
            and source_path == smoke.run_dir
            and destination_path.parent.name == ".run-trash"
        ):
            raced = True
            holding = registry.runs_root / ".race-holding"
            original_replace(smoke.run_dir, holding)
            original_replace(formal.run_dir, smoke.run_dir)
            original_replace(holding, formal.run_dir)
        return original_replace(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, "replace", racing_replace)

    assert registry.prune_smoke(keep=0) == []
    assert raced
    assert sorted(path.read_text(encoding="utf-8") for path in tmp_path.rglob("*.marker")) == [
        "formal",
        "smoke",
    ]
    assert [(item.run_id, item.kind) for item in registry.list_runs()] == [
        (smoke.run_id, "smoke"),
        (formal.run_id, "formal"),
    ]


def test_prune_final_delete_binding_rejects_a_swapped_formal_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = RunRegistry(tmp_path / "runs")
    smoke = _write(
        registry,
        "20260715T010203000000Z-smoke-rule",
        kind="smoke",
        change_id="rule",
    )
    formal = _write(
        registry,
        "20260715T010204000000Z-day_1",
        kind="formal",
    )
    advice = _write(
        registry,
        "20260715T010205000000Z-advice-day_1",
        kind="advice",
    )
    (smoke.run_dir / "smoke.marker").write_text("smoke", encoding="utf-8")
    (formal.run_dir / "formal.marker").write_text("formal", encoding="utf-8")
    (advice.run_dir / "advice.marker").write_text("advice", encoding="utf-8")
    original_delete = getattr(
        registry_module,
        "_delete_bound_tombstone",
        lambda *_args, **_kwargs: False,
    )
    raced = False

    def racing_delete(
        trash: Path,
        tombstone: Path,
        identity: os.stat_result,
        *args: object,
        **kwargs: object,
    ) -> bool:
        nonlocal raced
        raced = True
        holding = registry.runs_root / ".final-delete-holding"
        os.replace(tombstone, holding)
        os.replace(formal.run_dir, tombstone)
        os.replace(holding, formal.run_dir)
        return original_delete(trash, tombstone, identity, *args, **kwargs)

    monkeypatch.setattr(
        registry_module,
        "_delete_bound_tombstone",
        racing_delete,
        raising=False,
    )

    assert registry.prune_smoke(keep=0) == []
    assert raced
    assert sorted(path.read_text(encoding="utf-8") for path in tmp_path.rglob("*.marker")) == [
        "advice",
        "formal",
        "smoke",
    ]
    assert [(item.run_id, item.kind) for item in registry.list_runs()] == [
        (smoke.run_id, "smoke"),
        (formal.run_id, "formal"),
        (advice.run_id, "advice"),
    ]


def test_bound_prune_deletes_reparse_entry_without_following_external_target(
    tmp_path: Path,
) -> None:
    registry = RunRegistry(tmp_path / "runs")
    smoke = _write(
        registry,
        "20260715T010203000000Z-smoke-rule",
        kind="smoke",
        change_id="rule",
    )
    outside = tmp_path / "outside-prune-target"
    outside.mkdir()
    marker = outside / "marker.txt"
    marker.write_text("keep", encoding="utf-8")
    link = smoke.run_dir / "outside-link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"directory links unavailable: {error}")

    assert registry.prune_smoke(keep=0) == [smoke.run_id]
    assert not smoke.run_dir.exists()
    assert marker.read_text(encoding="utf-8") == "keep"


@pytest.mark.skipif(os.name != "nt", reason="Windows handle race")
def test_windows_bound_prune_rejects_child_replaced_after_enumeration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = RunRegistry(tmp_path / "runs")
    smoke = _write(
        registry,
        "20260715T010203000000Z-smoke-rule",
        kind="smoke",
        change_id="rule",
    )
    formal = _write(
        registry,
        "20260715T010204000000Z-day_1",
        kind="formal",
    )
    victim = smoke.run_dir / "victim.marker"
    victim.write_text("smoke-child", encoding="utf-8")
    formal_marker = formal.run_dir / "formal.marker"
    formal_marker.write_text("formal-child", encoding="utf-8")
    original_delete = registry_module._windows_delete_entry
    raced = False

    def racing_delete(path: Path, *args: object, **kwargs: object) -> bool:
        nonlocal raced
        if not raced and path.name == victim.name:
            raced = True
            holding = formal.run_dir / ".child-holding"
            os.replace(path, holding)
            os.replace(formal_marker, path)
            os.replace(holding, formal_marker)
        return original_delete(path, *args, **kwargs)

    monkeypatch.setattr(registry_module, "_windows_delete_entry", racing_delete)

    assert registry.prune_smoke(keep=0) == []
    assert raced
    assert sorted(path.read_text(encoding="utf-8") for path in tmp_path.rglob("*.marker")) == [
        "formal-child",
        "smoke-child",
    ]

    assert registry.prune_smoke(keep=0) == []
    assert sorted(
        path.read_text(encoding="utf-8") for path in tmp_path.rglob("*.marker")
    ) == [
        "formal-child",
        "smoke-child",
    ]
    assert [(item.run_id, item.kind) for item in registry.list_runs()] == [
        (formal.run_id, "formal"),
    ]

def test_prune_builds_the_allowlist_before_the_run_enters_trash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = RunRegistry(tmp_path / "runs")
    smoke = _write(
        registry,
        "20260715T010203000000Z-smoke-rule",
        kind="smoke",
        change_id="rule",
    )
    formal = _write(
        registry,
        "20260715T010204000000Z-day_1",
        kind="formal",
    )
    formal_marker = formal.run_dir / "formal.marker"
    formal_marker.write_text("formal-child", encoding="utf-8")
    original_snapshot = registry_module._snapshot_tombstone_entries
    injected = False

    def injecting_snapshot(
        run_dir: Path,
        expected_identity: os.stat_result,
    ) -> tuple[object, ...]:
        nonlocal injected
        if run_dir.parent.name == ".run-trash":
            injected = True
            os.replace(formal_marker, run_dir / "foreign.marker")
        return original_snapshot(run_dir, expected_identity)

    monkeypatch.setattr(
        registry_module,
        "_snapshot_tombstone_entries",
        injecting_snapshot,
    )

    assert registry.prune_smoke(keep=0) == [smoke.run_id]
    assert not injected
    assert formal_marker.read_text(encoding="utf-8") == "formal-child"


def test_prune_never_rebaselines_a_child_added_between_snapshot_and_move(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = RunRegistry(tmp_path / "runs")
    smoke = _write(
        registry,
        "20260715T010203000000Z-smoke-rule",
        kind="smoke",
        change_id="rule",
    )
    formal = _write(
        registry,
        "20260715T010204000000Z-day_1",
        kind="formal",
    )
    formal_marker = formal.run_dir / "formal.marker"
    formal_marker.write_text("formal-child", encoding="utf-8")
    original_replace = os.replace
    injected = False

    def injecting_replace(
        source: object,
        destination: object,
        *args: object,
        **kwargs: object,
    ) -> None:
        nonlocal injected
        source_path = Path(source)
        destination_path = Path(destination)
        original_replace(source, destination, *args, **kwargs)
        if (
            not injected
            and source_path == smoke.run_dir
            and destination_path.parent.name == ".run-trash"
        ):
            injected = True
            original_replace(
                formal_marker,
                destination_path / "foreign.marker",
            )

    monkeypatch.setattr(os, "replace", injecting_replace)

    assert registry.prune_smoke(keep=0) == []
    assert injected
    assert [
        path.read_text(encoding="utf-8")
        for path in tmp_path.rglob("foreign.marker")
    ] == ["formal-child"]
    trash = registry.runs_root / ".run-trash"
    assert list(trash.glob("tomb-????????????????????????????????"))
    assert list(trash.glob("tomb-????????????????????????????????.json"))
    assert [(item.run_id, item.kind) for item in registry.list_runs()] == [
        (formal.run_id, "formal"),
    ]

    assert registry.prune_smoke(keep=0) == []
    assert [
        path.read_text(encoding="utf-8")
        for path in tmp_path.rglob("foreign.marker")
    ] == ["formal-child"]


@pytest.mark.skipif(os.name == "nt", reason="POSIX dirfd race")
def test_posix_bound_prune_rejects_child_replacement_across_retries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = RunRegistry(tmp_path / "runs")
    smoke = _write(
        registry,
        "20260715T010203000000Z-smoke-rule",
        kind="smoke",
        change_id="rule",
    )
    formal = _write(
        registry,
        "20260715T010204000000Z-day_1",
        kind="formal",
    )
    victim = smoke.run_dir / "victim.marker"
    victim.write_text("smoke-child", encoding="utf-8")
    formal_marker = formal.run_dir / "formal.marker"
    formal_marker.write_text("formal-child", encoding="utf-8")
    original_rename = registry_module.os.rename
    raced = False

    def racing_rename(
        source: object,
        destination: object,
        *args: object,
        **kwargs: object,
    ) -> None:
        nonlocal raced
        if not raced and source == victim.name:
            raced = True
            [tombstone] = list(
                (registry.runs_root / ".run-trash").glob(
                    "tomb-????????????????????????????????"
                )
            )
            holding = formal.run_dir / ".child-holding"
            os.replace(tombstone / victim.name, holding)
            os.replace(formal_marker, tombstone / victim.name)
            os.replace(holding, formal_marker)
        original_rename(source, destination, *args, **kwargs)

    monkeypatch.setattr(registry_module.os, "rename", racing_rename)

    assert registry.prune_smoke(keep=0) == []
    assert raced
    assert registry.prune_smoke(keep=0) == []
    assert sorted(
        path.read_text(encoding="utf-8") for path in tmp_path.rglob("*.marker")
    ) == [
        "formal-child",
        "smoke-child",
    ]
    assert [(item.run_id, item.kind) for item in registry.list_runs()] == [
        (formal.run_id, "formal"),
    ]


@pytest.mark.skipif(os.name != "nt", reason="Windows handle race")
def test_windows_retry_routes_a_swapped_foreign_run_directory_without_deleting_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = RunRegistry(tmp_path / "runs")
    smoke = _write(
        registry,
        "20260715T010203000000Z-smoke-rule",
        kind="smoke",
        change_id="rule",
    )
    formal = _write(
        registry,
        "20260715T010204000000Z-day_1",
        kind="formal",
    )
    victim = smoke.run_dir / "victim-run"
    victim.mkdir()
    (victim / "smoke.marker").write_text("smoke-child", encoding="utf-8")
    formal_marker = formal.run_dir / "formal.marker"
    formal_marker.write_text("formal-child", encoding="utf-8")
    original_delete = registry_module._windows_delete_entry
    raced = False

    def racing_delete(path: Path, *args: object, **kwargs: object) -> bool:
        nonlocal raced
        if not raced and path.name == victim.name:
            raced = True
            holding = registry.runs_root / ".foreign-holding"
            os.replace(path, holding)
            os.replace(formal.run_dir, path)
        return original_delete(path, *args, **kwargs)

    monkeypatch.setattr(registry_module, "_windows_delete_entry", racing_delete)

    assert registry.prune_smoke(keep=0) == []
    assert raced
    assert registry.prune_smoke(keep=0) == []
    assert [(item.run_id, item.kind) for item in registry.list_runs()] == [
        (formal.run_id, "formal"),
    ]
    assert (formal.run_dir / formal_marker.name).read_text(encoding="utf-8") == (
        "formal-child"
    )
    trash = registry.runs_root / ".run-trash"
    assert list(trash.glob("tomb-????????????????????????????????"))
    assert list(trash.glob("tomb-????????????????????????????????.json"))


@pytest.mark.skipif(os.name == "nt", reason="POSIX dirfd race")
def test_posix_retry_routes_a_swapped_foreign_run_directory_without_deleting_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = RunRegistry(tmp_path / "runs")
    smoke = _write(
        registry,
        "20260715T010203000000Z-smoke-rule",
        kind="smoke",
        change_id="rule",
    )
    formal = _write(
        registry,
        "20260715T010204000000Z-day_1",
        kind="formal",
    )
    victim = smoke.run_dir / "victim-run"
    victim.mkdir()
    (victim / "smoke.marker").write_text("smoke-child", encoding="utf-8")
    formal_marker = formal.run_dir / "formal.marker"
    formal_marker.write_text("formal-child", encoding="utf-8")
    original_open = registry_module.os.open
    raced = False

    def racing_open(
        path: object,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal raced
        trash = registry.runs_root / ".run-trash"
        manifest_exists = bool(
            list(trash.glob("tomb-????????????????????????????????.json"))
        )
        if (
            not raced
            and manifest_exists
            and path == victim.name
            and dir_fd is not None
        ):
            raced = True
            [tombstone] = list(
                trash.glob(
                    "tomb-????????????????????????????????"
                )
            )
            holding = registry.runs_root / ".foreign-holding"
            os.replace(tombstone / victim.name, holding)
            os.replace(formal.run_dir, tombstone / victim.name)
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(registry_module.os, "open", racing_open)

    assert registry.prune_smoke(keep=0) == []
    assert raced
    assert registry.prune_smoke(keep=0) == []
    assert [(item.run_id, item.kind) for item in registry.list_runs()] == [
        (formal.run_id, "formal"),
    ]
    assert (formal.run_dir / formal_marker.name).read_text(encoding="utf-8") == (
        "formal-child"
    )
    trash = registry.runs_root / ".run-trash"
    assert list(trash.glob("tomb-????????????????????????????????"))
    assert list(trash.glob("tomb-????????????????????????????????.json"))


@pytest.mark.skipif(os.name != "nt", reason="Windows short-path alias")
def test_windows_short_path_alias_can_prune_verified_tombstone(tmp_path: Path) -> None:
    import ctypes

    long_root = tmp_path / "Run Registry Alias Project"
    registry = RunRegistry(long_root / "runs")
    smoke = _write(
        registry,
        "20260715T010203000000Z-smoke-rule",
        kind="smoke",
        change_id="rule",
    )
    buffer = ctypes.create_unicode_buffer(32768)
    length = ctypes.windll.kernel32.GetShortPathNameW(
        str(registry.runs_root),
        buffer,
        len(buffer),
    )
    if not length or length >= len(buffer):
        pytest.skip("8.3 short paths are unavailable")
    short_root = Path(buffer.value)
    if os.path.normcase(str(short_root)) == os.path.normcase(str(registry.runs_root)):
        pytest.skip("filesystem did not provide a distinct 8.3 alias")

    aliased = RunRegistry(short_root)

    assert aliased.prune_smoke(keep=0) == [smoke.run_id]
    assert not smoke.run_dir.exists()


def test_unsupported_bound_delete_retains_retryable_tombstone_without_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = RunRegistry(tmp_path / "runs")
    smoke = _write(
        registry,
        "20260715T010203000000Z-smoke-rule",
        kind="smoke",
        change_id="rule",
    )
    original_delete = registry_module._delete_bound_tombstone
    monkeypatch.setattr(
        registry_module,
        "_delete_bound_tombstone",
        lambda *_args, **_kwargs: False,
    )

    assert registry.prune_smoke(keep=0) == []
    tombstones = list(
        (registry.runs_root / ".run-trash").glob(
            "tomb-????????????????????????????????"
        )
    )
    assert len(tombstones) == 1
    assert not smoke.run_dir.exists()

    monkeypatch.setattr(registry_module, "_delete_bound_tombstone", original_delete)
    assert registry.prune_smoke(keep=0) == [smoke.run_id]
    assert not tombstones[0].exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows partial handle deletion")
def test_partial_tombstone_delete_retries_from_manifest_after_status_is_gone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = RunRegistry(tmp_path / "runs")
    smoke = _write(
        registry,
        "20260715T010203000000Z-smoke-rule",
        kind="smoke",
        change_id="rule",
    )
    (smoke.run_dir / "z-fail.marker").write_text("retry", encoding="utf-8")
    original_delete = registry_module._windows_delete_entry
    failed = False

    def failing_after_status(
        path: Path,
        expected_identity: os.stat_result,
        *args: object,
        **kwargs: object,
    ) -> bool:
        nonlocal failed
        if path.name == "z-fail.marker" and not failed:
            failed = True
            return False
        return original_delete(path, expected_identity, *args, **kwargs)

    monkeypatch.setattr(registry_module, "_windows_delete_entry", failing_after_status)

    assert registry.prune_smoke(keep=0) == []
    trash = registry.runs_root / ".run-trash"
    [tombstone] = list(trash.glob("tomb-????????????????????????????????"))
    assert failed
    assert not (tombstone / "run_status.json").exists()
    manifest_path = trash / f"{tombstone.name}.json"
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["version"] == 2
    assert [entry["path"] for entry in manifest["entries"]] == [
        "run_status.json",
        "z-fail.marker",
    ]
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", manifest["entries_sha256"])

    monkeypatch.setattr(registry_module, "_windows_delete_entry", original_delete)
    assert registry.prune_smoke(keep=0) == [smoke.run_id]
    assert not tombstone.exists()
    assert not manifest_path.exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX partial dirfd deletion")
def test_posix_partial_tombstone_delete_retries_from_allowlist_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = RunRegistry(tmp_path / "runs")
    smoke = _write(
        registry,
        "20260715T010203000000Z-smoke-rule",
        kind="smoke",
        change_id="rule",
    )
    (smoke.run_dir / "z-fail.marker").write_text("retry", encoding="utf-8")
    original_rename = registry_module.os.rename
    failed = False

    def failing_after_status(
        source: object,
        destination: object,
        *args: object,
        **kwargs: object,
    ) -> None:
        nonlocal failed
        if source == "z-fail.marker" and not failed:
            failed = True
            raise OSError("injected child deletion failure")
        original_rename(source, destination, *args, **kwargs)

    monkeypatch.setattr(registry_module.os, "rename", failing_after_status)

    assert registry.prune_smoke(keep=0) == []
    trash = registry.runs_root / ".run-trash"
    [tombstone] = list(trash.glob("tomb-????????????????????????????????"))
    manifest_path = trash / f"{tombstone.name}.json"
    assert failed
    assert not (tombstone / "run_status.json").exists()
    assert manifest_path.is_file()

    monkeypatch.setattr(registry_module.os, "rename", original_rename)
    assert registry.prune_smoke(keep=0) == [smoke.run_id]
    assert not tombstone.exists()
    assert not manifest_path.exists()


def test_next_prune_recovers_crash_tombstones_and_ignores_unsafe_trash(
    tmp_path: Path,
) -> None:
    registry = RunRegistry(tmp_path / "runs")
    smoke = _write(
        registry,
        "20260715T010203000000Z-smoke-rule",
        kind="smoke",
        change_id="rule",
    )
    formal = _write(
        registry,
        "20260715T010204000000Z-day_1",
        kind="formal",
    )
    advice = _write(
        registry,
        "20260715T010205000000Z-advice-day_1",
        kind="advice",
    )
    trash = registry.runs_root / ".run-trash"
    trash.mkdir()
    smoke_tomb = trash / ("tomb-" + "a" * 32)
    formal_tomb = trash / ("tomb-" + "b" * 32)
    advice_tomb = trash / ("tomb-" + "e" * 32)
    os.replace(smoke.run_dir, smoke_tomb)
    os.replace(formal.run_dir, formal_tomb)
    os.replace(advice.run_dir, advice_tomb)
    corrupt = trash / ("tomb-" + "c" * 32)
    corrupt.mkdir()
    (corrupt / "run_status.json").write_text("{", encoding="utf-8")
    corrupt_manifest = trash / f"{corrupt.name}.json"
    corrupt_manifest.write_text("{", encoding="utf-8")
    outside = tmp_path / "outside-trash-target"
    outside.mkdir()
    outside_marker = outside / "marker.txt"
    outside_marker.write_text("keep", encoding="utf-8")
    linked = trash / ("tomb-" + "d" * 32)
    try:
        linked.symlink_to(outside, target_is_directory=True)
        linked_manifest = trash / f"{linked.name}.json"
        linked_manifest.symlink_to(outside_marker)
    except OSError as error:
        pytest.skip(f"directory links unavailable: {error}")

    deleted = registry.prune_smoke(keep=0)

    assert deleted == [smoke.run_id]
    assert [(item.run_id, item.kind) for item in registry.list_runs()] == [
        (formal.run_id, "formal"),
        (advice.run_id, "advice"),
    ]
    assert not smoke_tomb.exists()
    assert not formal_tomb.exists()
    assert not advice_tomb.exists()
    assert corrupt.exists()
    assert corrupt_manifest.exists()
    assert linked.is_symlink()
    assert linked_manifest.is_symlink()
    assert outside_marker.read_text(encoding="utf-8") == "keep"


def test_prune_smoke_rejects_negative_retention(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="non-negative"):
        RunRegistry(tmp_path / "runs").prune_smoke(keep=-1)
