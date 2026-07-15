from __future__ import annotations

import json
from pathlib import Path
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
) -> Transaction:
    transaction = Transaction(
        project,
        "change-1",
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
