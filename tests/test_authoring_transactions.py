from __future__ import annotations

import errno
import json
from pathlib import Path
import shutil
from typing import NoReturn

from openpyxl import Workbook
import pytest

from igess.authoring.project import AuthoringProject
from igess.authoring.response import AuthoringError
from igess.authoring import transactions as transaction_module
from igess.authoring.transactions import Transaction, recover_transactions


class _HardCrash(BaseException):
    pass


def _make_project(root: Path) -> AuthoringProject:
    root.mkdir()
    (root / "economy.yaml").write_bytes(b"version: 1\nold: config\n")
    datas = root / "Datas"
    datas.mkdir()

    registry = Workbook()
    sheet = registry.active
    sheet.append(["##var", "table", "path"])
    sheet.append(["##", None, None])
    sheet.append(["##type", "string", "string"])
    sheet.append([None, "resources", "resources.xlsx"])
    registry.save(datas / "__tables__.xlsx")
    registry.close()
    (datas / "resources.xlsx").write_bytes(b"old workbook bytes")

    exports = root / "luban_exports"
    exports.mkdir()
    (exports / "resources.json").write_bytes(b'{"old":true}\n')
    return AuthoringProject.discover(root)


def _tree_bytes(root: Path, relative: str) -> dict[str, bytes]:
    path = root / relative
    if path.is_file():
        return {relative: path.read_bytes()}
    return {
        item.relative_to(root).as_posix(): item.read_bytes()
        for item in sorted(path.rglob("*"))
        if item.is_file()
    }


def _formal_snapshot(project: AuthoringProject) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    for relative in ("economy.yaml", "Datas", "luban_exports"):
        result.update(_tree_bytes(project.root, relative))
    return result


def _stage_transaction(
    project: AuthoringProject,
    *,
    checkpoint=lambda _name: None,
    digest_reader=None,
    change_id: str = "change-1",
) -> Transaction:
    transaction = Transaction(
        project,
        change_id,
        project.model_digest(),
        checkpoint=checkpoint,
        digest_reader=digest_reader,
    )
    candidate = transaction.candidate_dir
    (candidate / "Datas").mkdir(parents=True)
    (candidate / "economy.yaml").write_bytes(b"version: 1\nnew: config\n")
    (candidate / "Datas" / "resources.xlsx").write_bytes(b"new workbook bytes")
    (candidate / "luban_exports").mkdir()
    (candidate / "luban_exports" / "resources.json").write_bytes(
        b'{"new":true}\n'
    )

    transaction.staged_run_dir.mkdir()
    (transaction.staged_run_dir / "run_status.json").write_text(
        '{"status":"success"}\n', encoding="utf-8"
    )
    transaction.staged_change_path.write_text(
        '{"outcome":"success"}\n', encoding="utf-8"
    )
    transaction.prepare(
        targets=("economy.yaml", "Datas/resources.xlsx", "luban_exports"),
        run_destination=project.runs / "run-1",
        change_destination=project.changes / "record-1.json",
    )
    return transaction


def _assert_pre_transaction_state(
    project: AuthoringProject,
    snapshot: dict[str, bytes],
) -> None:
    assert _formal_snapshot(project) == snapshot
    assert not (project.runs / "run-1").exists()
    assert not (project.changes / "record-1.json").exists()


def _assert_post_transaction_state(project: AuthoringProject) -> None:
    assert project.config.read_bytes() == b"version: 1\nnew: config\n"
    assert (project.datas / "resources.xlsx").read_bytes() == b"new workbook bytes"
    assert (project.exports / "resources.json").read_bytes() == b'{"new":true}\n'
    assert (project.runs / "run-1" / "run_status.json").is_file()
    assert (project.changes / "record-1.json").is_file()


def test_prepare_writes_exact_schema_one_disk_contract(tmp_path: Path) -> None:
    project = _make_project(tmp_path / "model")
    transaction = _stage_transaction(project)

    assert transaction.root == project.transactions / "change-1"
    assert transaction.candidate_dir.is_dir()
    assert transaction.backups_dir.is_dir()
    assert transaction.staged_artifacts_dir.is_dir()
    assert json.loads(transaction.journal_path.read_text(encoding="utf-8")) == {
        "schema_version": 1,
        "change_id": "change-1",
        "phase": "prepared",
        "pre_digest": transaction.pre_digest,
        "targets": [
            {
                "live": "economy.yaml",
                "candidate": "candidate/economy.yaml",
                "backup": "backups/economy.yaml",
                "live_existed": True,
            },
            {
                "live": "Datas/resources.xlsx",
                "candidate": "candidate/Datas/resources.xlsx",
                "backup": "backups/Datas/resources.xlsx",
                "live_existed": True,
            },
            {
                "live": "luban_exports",
                "candidate": "candidate/luban_exports",
                "backup": "backups/luban_exports",
                "live_existed": True,
            },
        ],
        "staged_run": {
            "staged": "staged_artifacts/run",
            "destination": "runs/run-1",
        },
        "staged_change": {
            "staged": "staged_artifacts/change.json",
            "destination": "changes/record-1.json",
        },
        "last_completed_checkpoint": "prepared",
    }
    assert list(transaction.journal_path.parent.glob(".journal.json.*.tmp")) == []


def test_recovery_cleans_transaction_that_crashed_during_staging(
    tmp_path: Path,
) -> None:
    project = _make_project(tmp_path / "model")
    before = _formal_snapshot(project)
    transaction = Transaction(project, "change-1", project.model_digest())
    transaction.candidate_dir.mkdir()
    (transaction.candidate_dir / "partial.tmp").write_bytes(b"partial")

    journal = json.loads(transaction.journal_path.read_text(encoding="utf-8"))
    assert journal["phase"] == "staging"
    assert journal["staged_change"] is None

    assert recover_transactions(project) == [
        {
            "code": "recovered_transaction",
            "message": "Recovered interrupted transaction change-1",
            "change_id": "change-1",
        }
    ]
    assert _formal_snapshot(project) == before
    assert not transaction.root.exists()


def test_abort_removes_unprepared_staging_transaction(tmp_path: Path) -> None:
    project = _make_project(tmp_path / "model")
    transaction = Transaction(project, "change-1", project.model_digest())
    transaction.candidate_dir.mkdir()

    transaction.abort()

    assert not transaction.root.exists()
    assert recover_transactions(project) == []


def test_cleanup_prefixed_change_id_remains_a_normal_recoverable_transaction(
    tmp_path: Path,
) -> None:
    project = _make_project(tmp_path / "model")
    before = _formal_snapshot(project)

    def crash(name: str) -> NoReturn | None:
        if name == "target:0:economy.yaml":
            raise _HardCrash(name)
        return None

    transaction = _stage_transaction(
        project,
        checkpoint=crash,
        change_id=".cleanup-legitimate-change",
    )
    with pytest.raises(_HardCrash):
        transaction.commit()

    assert recover_transactions(project) == [
        {
            "code": "recovered_transaction",
            "message": (
                "Recovered interrupted transaction .cleanup-legitimate-change"
            ),
            "change_id": ".cleanup-legitimate-change",
        }
    ]
    _assert_pre_transaction_state(project, before)


@pytest.mark.parametrize("change_id", ["../transactions-trash", "bad/name", "bad\\name"])
def test_change_id_cannot_escape_transaction_namespace(
    tmp_path: Path,
    change_id: str,
) -> None:
    project = _make_project(tmp_path / "model")

    with pytest.raises((TypeError, ValueError)):
        Transaction(project, change_id, project.model_digest())

    assert not (project.root / ".igess" / "transactions-trash").exists()


@pytest.mark.parametrize(
    "destination",
    [
        "changes",
        "changes/nested/record.json",
    ],
)
def test_change_destination_must_be_one_safe_registry_child(
    tmp_path: Path,
    destination: str,
) -> None:
    project = _make_project(tmp_path / "model")
    transaction = Transaction(project, "change-1", project.model_digest())
    transaction.candidate_dir.mkdir()
    (transaction.candidate_dir / "economy.yaml").write_bytes(b"candidate")
    transaction.staged_change_path.write_bytes(b"audit")

    with pytest.raises(AuthoringError) as caught:
        transaction.prepare(
            targets=("economy.yaml",),
            run_destination=None,
            change_destination=destination,
        )

    assert caught.value.code == "transaction_artifact_destination_unsafe"


def _directory_symlink_or_skip(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"directory symlinks unavailable: {error}")


def test_commit_rejects_candidate_ancestor_symlink_without_touching_external_tree(
    tmp_path: Path,
) -> None:
    project = _make_project(tmp_path / "model")
    before = _formal_snapshot(project)
    transaction = _stage_transaction(project)
    external = tmp_path / "external-candidate"
    external.mkdir()
    external_source = external / "resources.xlsx"
    external_source.write_bytes(b"external bytes must remain")
    shutil.rmtree(transaction.candidate_dir / "Datas")
    _directory_symlink_or_skip(transaction.candidate_dir / "Datas", external)

    with pytest.raises(AuthoringError) as caught:
        transaction.commit()

    assert caught.value.code == "commit_failed"
    assert external_source.read_bytes() == b"external bytes must remain"
    _assert_pre_transaction_state(project, before)


def test_commit_rejects_run_registry_symlink_without_publishing_outside_project(
    tmp_path: Path,
) -> None:
    project = _make_project(tmp_path / "model")
    before = _formal_snapshot(project)
    transaction = _stage_transaction(project)
    external = tmp_path / "external-runs"
    external.mkdir()
    _directory_symlink_or_skip(project.runs, external)

    with pytest.raises(AuthoringError) as caught:
        transaction.commit()

    assert caught.value.code in {"commit_failed", "recovery_required"}
    assert list(external.iterdir()) == []
    assert _formal_snapshot(project) == before


def test_commit_rejects_backup_ancestor_symlink_without_writing_external_tree(
    tmp_path: Path,
) -> None:
    project = _make_project(tmp_path / "model")
    before = _formal_snapshot(project)
    transaction = _stage_transaction(project)
    external = tmp_path / "external-backups"
    external.mkdir()
    _directory_symlink_or_skip(transaction.backups_dir / "Datas", external)

    with pytest.raises(AuthoringError) as caught:
        transaction.commit()

    assert caught.value.code in {"commit_failed", "recovery_required"}
    assert list(external.iterdir()) == []
    assert _formal_snapshot(project) == before


def test_commit_rechecks_current_digest_and_reports_stale_model(tmp_path: Path) -> None:
    project = _make_project(tmp_path / "model")
    before = _formal_snapshot(project)
    transaction = _stage_transaction(
        project,
        digest_reader=lambda: "sha256:stale",
    )

    with pytest.raises(AuthoringError) as caught:
        transaction.commit()

    assert caught.value.code == "stale_model"
    assert caught.value.details["expected"] == transaction.pre_digest
    assert caught.value.details["actual"] == "sha256:stale"
    _assert_pre_transaction_state(project, before)
    assert not transaction.root.exists()


@pytest.mark.parametrize(
    "failed_checkpoint",
    [
        "stale_digest_recheck",
        "target:0:economy.yaml",
        "target:1:Datas/resources.xlsx",
        "target:2:luban_exports",
        "staged_run",
        "staged_change",
    ],
)
def test_precommit_checkpoint_failures_restore_exact_formal_snapshot(
    tmp_path: Path,
    failed_checkpoint: str,
) -> None:
    project = _make_project(tmp_path / "model")
    before = _formal_snapshot(project)

    def fail(name: str) -> None:
        if name == failed_checkpoint:
            raise RuntimeError(f"fail {name}")

    transaction = _stage_transaction(project, checkpoint=fail)

    with pytest.raises(AuthoringError) as caught:
        transaction.commit()

    assert caught.value.code == "commit_failed"
    assert caught.value.details["checkpoint"] == failed_checkpoint
    _assert_pre_transaction_state(project, before)
    assert not transaction.root.exists()


def test_committed_journal_write_failure_rolls_back_every_target_and_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _make_project(tmp_path / "model")
    before = _formal_snapshot(project)
    transaction = _stage_transaction(project)
    real_writer = transaction_module._write_journal

    def fail_committed(path: Path, payload: dict[str, object]) -> None:
        if payload["phase"] == "committed":
            raise OSError("journal medium failed")
        real_writer(path, payload)

    monkeypatch.setattr(transaction_module, "_write_journal", fail_committed)

    with pytest.raises(AuthoringError) as caught:
        transaction.commit()

    assert caught.value.code == "commit_failed"
    assert caught.value.details["checkpoint"] == "journal_committed"
    _assert_pre_transaction_state(project, before)
    assert not transaction.root.exists()


def test_visible_committed_journal_fsync_failure_never_rolls_back_post_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _make_project(tmp_path / "model")
    transaction = _stage_transaction(project)
    real_replace = transaction_module.os.replace
    real_fsync_directory = transaction_module._fsync_directory
    real_rollback = transaction_module._rollback
    committed_published = False
    failed = False

    def observe_replace(source: str | Path, destination: str | Path) -> None:
        nonlocal committed_published
        real_replace(source, destination)
        destination_path = Path(destination)
        if destination_path == transaction.journal_path:
            payload = json.loads(destination_path.read_text(encoding="utf-8"))
            committed_published = payload["phase"] == "committed"

    def fail_committed_parent_fsync(path: Path) -> None:
        nonlocal failed
        if committed_published and path == transaction.root and not failed:
            failed = True
            raise OSError(errno.EIO, "committed directory fsync failed")
        real_fsync_directory(path)

    monkeypatch.setattr(transaction_module.os, "replace", observe_replace)
    monkeypatch.setattr(transaction_module, "_fsync_directory", fail_committed_parent_fsync)
    monkeypatch.setattr(
        transaction_module,
        "_journal_matches",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        transaction_module,
        "_rollback",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("committed-visible state must not roll back")
        ),
    )

    with pytest.raises(AuthoringError) as caught:
        transaction.commit()

    assert failed is True
    assert caught.value.code == "commit_in_doubt"
    assert caught.value.details["phase"] == "committed"
    _assert_post_transaction_state(project)
    assert transaction.root.exists()

    monkeypatch.setattr(transaction_module.os, "replace", real_replace)
    monkeypatch.setattr(transaction_module, "_fsync_directory", real_fsync_directory)
    monkeypatch.setattr(transaction_module, "_rollback", real_rollback)
    assert recover_transactions(project) == []
    _assert_post_transaction_state(project)
    assert not transaction.root.exists()


def test_rollback_failure_reports_recovery_required_and_keeps_journal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _make_project(tmp_path / "model")
    before = _formal_snapshot(project)

    def fail_after_first_target(name: str) -> None:
        if name == "target:0:economy.yaml":
            raise RuntimeError("primary commit failure")

    transaction = _stage_transaction(project, checkpoint=fail_after_first_target)
    real_rollback = transaction_module._rollback
    monkeypatch.setattr(
        transaction_module,
        "_rollback",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("rollback failed")),
    )

    with pytest.raises(AuthoringError) as caught:
        transaction.commit()

    assert caught.value.code == "recovery_required"
    assert "recovery" in caught.value.message.lower()
    assert caught.value.details["checkpoint"] == "target:0:economy.yaml"
    assert caught.value.details["rollback_error_type"] == "OSError"
    assert transaction.root.exists()
    assert project.config.read_bytes() == b"version: 1\nnew: config\n"
    assert _formal_snapshot(project) != before

    monkeypatch.setattr(transaction_module, "_rollback", real_rollback)
    assert recover_transactions(project)[0]["code"] == "recovered_transaction"
    _assert_pre_transaction_state(project, before)


@pytest.mark.parametrize(
    ("source_relative", "destination_relative"),
    [
        ("candidate/economy.yaml", "economy.yaml"),
        ("candidate/Datas/resources.xlsx", "Datas/resources.xlsx"),
        ("candidate/luban_exports", "luban_exports"),
        ("staged_artifacts/run", "runs/run-1"),
        ("staged_artifacts/change.json", "changes/record-1.json"),
    ],
)
def test_replace_operation_failures_restore_every_formal_byte(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_relative: str,
    destination_relative: str,
) -> None:
    project = _make_project(tmp_path / "model")
    before = _formal_snapshot(project)
    transaction = _stage_transaction(project)
    failed_source = transaction.root / source_relative
    failed_destination = project.root / destination_relative
    real_replace = transaction_module.os.replace

    def fail_selected(source: str | Path, destination: str | Path) -> None:
        if Path(source) == failed_source and Path(destination) == failed_destination:
            raise OSError("selected replace failed")
        real_replace(source, destination)

    monkeypatch.setattr(transaction_module.os, "replace", fail_selected)

    with pytest.raises(AuthoringError) as caught:
        transaction.commit()

    assert caught.value.code == "commit_failed"
    _assert_pre_transaction_state(project, before)
    assert not transaction.root.exists()


@pytest.mark.parametrize(
    "crash_checkpoint",
    [
        "stale_digest_recheck",
        "journal_committing",
        "target:0:economy.yaml",
        "target:1:Datas/resources.xlsx",
        "target:2:luban_exports",
        "staged_run",
        "staged_change",
        "journal_committed",
    ],
)
def test_next_recovery_repairs_hard_crash_after_every_commit_checkpoint(
    tmp_path: Path,
    crash_checkpoint: str,
) -> None:
    project = _make_project(tmp_path / "model")
    before = _formal_snapshot(project)

    def crash(name: str) -> NoReturn | None:
        if name == crash_checkpoint:
            raise _HardCrash(name)
        return None

    transaction = _stage_transaction(project, checkpoint=crash)
    with pytest.raises(_HardCrash):
        transaction.commit()

    warnings = recover_transactions(project)

    if crash_checkpoint == "journal_committed":
        _assert_post_transaction_state(project)
        assert warnings == []
    else:
        _assert_pre_transaction_state(project, before)
        assert warnings == [
            {
                "code": "recovered_transaction",
                "message": "Recovered interrupted transaction change-1",
                "change_id": "change-1",
            }
        ]
    assert not transaction.root.exists()


def test_cleanup_failure_after_durable_commit_keeps_post_change_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _make_project(tmp_path / "model")
    transaction = _stage_transaction(project)
    real_cleanup = transaction_module._cleanup_transaction
    calls = 0

    def fail_once(root: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("cleanup busy")
        real_cleanup(root)

    monkeypatch.setattr(transaction_module, "_cleanup_transaction", fail_once)

    warnings = transaction.commit()

    _assert_post_transaction_state(project)
    assert warnings == (
        {
            "code": "transaction_cleanup_pending",
            "message": "Committed transaction change-1 requires cleanup recovery",
            "change_id": "change-1",
        },
    )
    assert json.loads(transaction.journal_path.read_text(encoding="utf-8"))["phase"] == "committed"

    assert recover_transactions(project) == []
    _assert_post_transaction_state(project)
    assert not transaction.root.exists()


def test_cleanup_tombstone_survives_partial_delete_without_a_journal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _make_project(tmp_path / "model")
    transaction = _stage_transaction(project)
    real_delete = transaction_module._delete_tombstone

    def crash_after_partial_delete(tombstone: Path) -> NoReturn:
        (tombstone / "journal.json").unlink()
        candidate = tombstone / "candidate"
        if candidate.exists():
            shutil.rmtree(candidate)
        raise _HardCrash("cleanup interrupted")

    monkeypatch.setattr(transaction_module, "_delete_tombstone", crash_after_partial_delete)

    with pytest.raises(_HardCrash):
        transaction.commit()

    assert not transaction.root.exists()
    trash_root = project.root / ".igess" / "transactions-trash"
    tombstones = list(trash_root.glob("txn-*"))
    assert len(tombstones) == 1
    assert not (tombstones[0] / "journal.json").exists()
    _assert_post_transaction_state(project)

    monkeypatch.setattr(transaction_module, "_delete_tombstone", real_delete)
    assert recover_transactions(project) == []
    assert list(trash_root.glob("txn-*")) == []
    _assert_post_transaction_state(project)


def test_crash_before_first_staging_journal_leaves_recoverable_init_residue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _make_project(tmp_path / "model")
    before = _formal_snapshot(project)
    real_writer = transaction_module._write_journal

    def crash_before_journal(path: Path, payload: dict[str, object]) -> NoReturn:
        assert payload["phase"] == "staging"
        raise _HardCrash(f"journal absent at {path}")

    monkeypatch.setattr(transaction_module, "_write_journal", crash_before_journal)

    with pytest.raises(_HardCrash):
        Transaction(project, "change-1", project.model_digest())

    assert not (project.transactions / "change-1").exists()
    init_root = project.root / ".igess" / "transactions-init"
    assert len(list(init_root.glob("init-*"))) == 1

    monkeypatch.setattr(transaction_module, "_write_journal", real_writer)
    assert recover_transactions(project) == []
    assert list(init_root.glob("init-*")) == []
    assert _formal_snapshot(project) == before


def test_recovery_does_not_delete_unrecognized_init_namespace_content(
    tmp_path: Path,
) -> None:
    project = _make_project(tmp_path / "model")
    unknown = project.root / ".igess" / "transactions-init" / "user-content"
    unknown.mkdir(parents=True)
    (unknown / "keep.txt").write_text("keep", encoding="utf-8")

    assert recover_transactions(project) == []

    assert (unknown / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_publish_fsyncs_candidate_before_rename_and_both_rename_parents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _make_project(tmp_path / "model")
    transaction = _stage_transaction(project)
    events: list[tuple[str, Path, Path | None]] = []
    real_tree = transaction_module._fsync_tree
    real_directory = transaction_module._fsync_directory
    real_replace = transaction_module.os.replace

    def record_tree(path: Path) -> None:
        events.append(("tree", path, None))
        real_tree(path)

    def record_directory(path: Path) -> None:
        events.append(("directory", path, None))
        real_directory(path)

    def record_replace(source: str | Path, destination: str | Path) -> None:
        events.append(("replace", Path(source), Path(destination)))
        real_replace(source, destination)

    monkeypatch.setattr(transaction_module, "_fsync_tree", record_tree)
    monkeypatch.setattr(transaction_module, "_fsync_directory", record_directory)
    monkeypatch.setattr(transaction_module.os, "replace", record_replace)

    assert transaction.commit() == ()

    for relative in ("economy.yaml", "Datas/resources.xlsx", "luban_exports"):
        candidate = transaction.candidate_dir / relative
        live = project.root / relative
        replace_index = events.index(("replace", candidate, live))
        assert ("tree", candidate, None) in events[:replace_index]
        later = events[replace_index + 1 :]
        assert ("directory", candidate.parent, None) in later
        assert ("directory", live.parent, None) in later

    replace_indices = [
        index for index, event in enumerate(events) if event[0] == "replace"
    ]
    for position, replace_index in enumerate(replace_indices):
        _, source, destination = events[replace_index]
        assert destination is not None
        if source.parent == destination.parent:
            continue
        next_replace = (
            replace_indices[position + 1]
            if position + 1 < len(replace_indices)
            else len(events)
        )
        durable_events = events[replace_index + 1 : next_replace]
        assert ("directory", source.parent, None) in durable_events
        assert ("directory", destination.parent, None) in durable_events


def test_directory_fsync_propagates_non_unsupported_media_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(transaction_module.os, "open", lambda *_args: 91)
    monkeypatch.setattr(transaction_module.os, "close", lambda _descriptor: None)

    def fail_fsync(_descriptor: int) -> NoReturn:
        raise OSError(errno.EIO, "directory media failed")

    monkeypatch.setattr(transaction_module.os, "fsync", fail_fsync)

    with pytest.raises(OSError) as caught:
        transaction_module._fsync_directory(tmp_path)

    assert caught.value.errno == errno.EIO


def test_successful_commit_publishes_every_target_and_cleans_transaction(
    tmp_path: Path,
) -> None:
    project = _make_project(tmp_path / "model")
    transaction = _stage_transaction(project)

    assert transaction.commit() == ()

    _assert_post_transaction_state(project)
    assert not transaction.root.exists()


def test_recovery_rejects_malformed_journal_without_touching_project(
    tmp_path: Path,
) -> None:
    project = _make_project(tmp_path / "model")
    before = _formal_snapshot(project)
    bad = project.transactions / "bad"
    bad.mkdir(parents=True)
    (bad / "journal.json").write_text(
        '{"schema_version":1,"phase":"committing","targets":[{"live":"../escape"}]}',
        encoding="utf-8",
    )

    with pytest.raises(AuthoringError) as caught:
        recover_transactions(project)

    assert caught.value.code == "recovery_failed"
    assert _formal_snapshot(project) == before
    assert bad.exists()


@pytest.mark.parametrize("corruption", ["duplicate_target", "phase_checkpoint"])
def test_recovery_rejects_conflicting_targets_and_phase_checkpoint(
    tmp_path: Path,
    corruption: str,
) -> None:
    project = _make_project(tmp_path / "model")

    def crash(name: str) -> NoReturn | None:
        if name == "target:0:economy.yaml":
            raise _HardCrash(name)
        return None

    transaction = _stage_transaction(project, checkpoint=crash)
    with pytest.raises(_HardCrash):
        transaction.commit()
    journal = json.loads(transaction.journal_path.read_text(encoding="utf-8"))
    if corruption == "duplicate_target":
        duplicate = dict(journal["targets"][0])
        duplicate["live_existed"] = not duplicate["live_existed"]
        journal["targets"].append(duplicate)
    else:
        journal["phase"] = "committed"
    transaction.journal_path.write_text(json.dumps(journal), encoding="utf-8")
    before_recovery = _formal_snapshot(project)

    with pytest.raises(AuthoringError) as caught:
        recover_transactions(project)

    assert caught.value.code == "recovery_failed"
    assert _formal_snapshot(project) == before_recovery
    assert transaction.root.exists()
