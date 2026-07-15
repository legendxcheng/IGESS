from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path

import pytest

import igess.authoring.change_records as change_records_module
from igess.authoring.change import ModelChange
from igess.authoring.change_records import ChangeRecordStore, ChangeRecordWarning
from igess.authoring.probe import EligibilityFinding
from igess.authoring.response import AuthoringError
from igess.authoring.status import ModelStatus


UTC_INSTANT = datetime(2026, 7, 15, 4, 5, 6, 789012, tzinfo=timezone.utc)
PRE_DIGEST = "sha256:" + "1" * 64
POST_DIGEST = "sha256:" + "2" * 64
MAX_RECORD_BYTES = 4 * 1024 * 1024


def _change(entity_id: str = "gold") -> ModelChange:
    return ModelChange(
        version=1,
        operation="upsert",
        entity="resource",
        id=entity_id,
        fields={"name": "Gold", "dimension": "currency"},
        if_model_digest=PRE_DIGEST,
    )


def _status() -> ModelStatus:
    return ModelStatus(
        model_digest=POST_DIGEST,
        structural_valid=True,
        smoke_eligible=False,
        state="incomplete",
        entity_counts={"resource": 1},
        missing_requirements=(
            EligibilityFinding("generator_missing", "Define a generator."),
        ),
        warnings=(EligibilityFinding("balance_note", "Review the curve."),),
    )


def _store(tmp_path: Path, instant: datetime = UTC_INSTANT) -> ChangeRecordStore:
    changes = tmp_path / "changes"
    changes.mkdir()
    return ChangeRecordStore(changes, clock=lambda: instant)


def _stage_path(tmp_path: Path, name: str = "change.json") -> Path:
    path = tmp_path / "transaction" / "staged_artifacts" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _publish(staged: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staged, destination)


def _published_success(tmp_path: Path) -> tuple[ChangeRecordStore, Path]:
    store = _store(tmp_path)
    staged = _stage_path(tmp_path)
    destination = store.stage_success(
        staged,
        change_id="valid",
        change=_change(),
        pre_digest=PRE_DIGEST,
        post_digest=POST_DIGEST,
        affected_files=[],
        status=_status(),
    )
    _publish(staged, destination)
    return store, destination


def _rewrite_payload(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def test_stage_success_writes_exact_schema_without_touching_final_registry(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    staged = _stage_path(tmp_path)

    destination = store.stage_success(
        staged,
        change_id="change-7",
        change=_change(),
        pre_digest=PRE_DIGEST,
        post_digest=POST_DIGEST,
        affected_files=["luban_exports", "Datas/resources.xlsx", "economy.yaml"],
        status=_status(),
        warnings=[
            {"message": "Recovered an old transaction.", "code": "recovered"}
        ],
        run_id="20260715T040506789012Z-smoke-change-7",
    )

    assert destination == (
        tmp_path / "changes" / "20260715T040506789012Z-change-7.json"
    )
    assert staged.is_file()
    assert not destination.exists()
    assert list((tmp_path / "changes").iterdir()) == []
    assert json.loads(staged.read_text(encoding="utf-8")) == {
        "version": 1,
        "outcome": "success",
        "timestamp": "2026-07-15T04:05:06.789012Z",
        "change": _change().to_payload(),
        "pre_digest": PRE_DIGEST,
        "post_digest": POST_DIGEST,
        "affected_files": [
            "Datas/resources.xlsx",
            "economy.yaml",
            "luban_exports",
        ],
        "status": _status().to_payload(),
        "warnings": [
            {"code": "recovered", "message": "Recovered an old transaction."}
        ],
        "run_id": "20260715T040506789012Z-smoke-change-7",
    }


def test_write_failure_uses_failed_registry_and_error_envelope(tmp_path: Path) -> None:
    store = _store(tmp_path)
    error = AuthoringError(
        "model_invalid",
        "Candidate validation failed",
        {"entity": "resource", "id": "gold"},
        {"status": "failed"},
    )

    path = store.write_failure(
        change_id="change-8",
        change=_change(),
        pre_digest=PRE_DIGEST,
        affected_files=["economy.yaml", "economy.yaml"],
        error=error,
        warnings=(EligibilityFinding("lint_warning", "Check the lint output."),),
        run_id=None,
    )

    assert path == (
        tmp_path
        / "changes"
        / "failed"
        / "20260715T040506789012Z-change-8.json"
    )
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "version": 1,
        "outcome": "failure",
        "timestamp": "2026-07-15T04:05:06.789012Z",
        "change": _change().to_payload(),
        "pre_digest": PRE_DIGEST,
        "post_digest": None,
        "affected_files": ["economy.yaml"],
        "error": {
            "code": "model_invalid",
            "message": "Candidate validation failed",
            "details": {"entity": "resource", "id": "gold"},
            "result": {"status": "failed"},
        },
        "warnings": [
            {"code": "lint_warning", "message": "Check the lint output."}
        ],
        "run_id": None,
    }


@pytest.mark.parametrize("method", ["success", "failure"])
def test_record_writes_are_atomic_and_leave_no_temporary_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
) -> None:
    store = _store(tmp_path)
    real_replace = os.replace
    replacements: list[tuple[Path, Path]] = []

    def observing_replace(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
        source_path = Path(source)
        target_path = Path(target)
        assert source_path.is_file()
        replacements.append((source_path, target_path))
        real_replace(source_path, target_path)

    monkeypatch.setattr("igess.authoring.change_records.os.replace", observing_replace)
    if method == "success":
        final = _stage_path(tmp_path)
        store.stage_success(
            final,
            change_id="atomic",
            change=_change(),
            pre_digest=PRE_DIGEST,
            post_digest=POST_DIGEST,
            affected_files=[],
            status=_status(),
        )
    else:
        final = store.write_failure(
            change_id="atomic",
            change=_change(),
            pre_digest=PRE_DIGEST,
            affected_files=[],
            error=AuthoringError("smoke_failed", "Smoke failed"),
        )

    assert replacements[-1][1] == final
    assert not list(final.parent.glob(f".{final.name}.*.tmp"))


def test_list_records_skips_malformed_records_with_a_warning(tmp_path: Path) -> None:
    store = _store(tmp_path)
    staged = _stage_path(tmp_path)
    destination = store.stage_success(
        staged,
        change_id="valid",
        change=_change(),
        pre_digest=PRE_DIGEST,
        post_digest=POST_DIGEST,
        affected_files=[],
        status=_status(),
    )
    _publish(staged, destination)
    (tmp_path / "changes" / "20260715T040506789013Z-broken.json").write_text(
        "{not-json", encoding="utf-8"
    )

    with pytest.warns(ChangeRecordWarning, match="broken.json"):
        records = store.list_records()

    assert [record["change"]["id"] for record in records] == ["gold"]


def test_latest_is_newest_and_equal_timestamps_have_stable_filename_order(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    destinations: list[Path] = []
    for change_id, entity_id in (("change-b", "bronze"), ("change-a", "amber")):
        staged = _stage_path(tmp_path, f"{change_id}.json")
        destination = store.stage_success(
            staged,
            change_id=change_id,
            change=_change(entity_id),
            pre_digest=PRE_DIGEST,
            post_digest=POST_DIGEST,
            affected_files=[],
            status=_status(),
        )
        _publish(staged, destination)
        destinations.append(destination)

    ordered = store.list_records()

    assert [record["change"]["id"] for record in ordered] == ["amber", "bronze"]
    assert store.latest() == ordered[-1]
    assert store.latest()["change"]["id"] == "bronze"


def test_timestamp_is_normalized_to_utc_for_field_and_filename(tmp_path: Path) -> None:
    local_time = datetime(
        2026, 7, 15, 12, 5, 6, 789012, tzinfo=timezone(timedelta(hours=8))
    )
    store = _store(tmp_path, local_time)
    staged = _stage_path(tmp_path)

    destination = store.stage_success(
        staged,
        change_id="utc",
        change=_change(),
        pre_digest=PRE_DIGEST,
        post_digest=POST_DIGEST,
        affected_files=[],
        status=_status(),
    )

    assert destination.name == "20260715T040506789012Z-utc.json"
    assert json.loads(staged.read_text(encoding="utf-8"))["timestamp"] == (
        "2026-07-15T04:05:06.789012Z"
    )


@pytest.mark.parametrize("change_id", ["", ".", "..", "../escape", "a/b", "a\\b"])
def test_unsafe_change_ids_are_rejected_without_writing(
    tmp_path: Path,
    change_id: str,
) -> None:
    store = _store(tmp_path)
    staged = _stage_path(tmp_path)

    with pytest.raises((TypeError, ValueError)):
        store.stage_success(
            staged,
            change_id=change_id,
            change=_change(),
            pre_digest=PRE_DIGEST,
            post_digest=POST_DIGEST,
            affected_files=[],
            status=_status(),
        )

    assert not staged.exists()
    assert list((tmp_path / "changes").iterdir()) == []


def test_latest_is_none_when_registry_has_no_valid_success_record(tmp_path: Path) -> None:
    store = _store(tmp_path)

    assert store.latest() is None


@pytest.mark.parametrize(
    "corrupt",
    [
        lambda payload: payload.__setitem__("change", {}),
        lambda payload: payload["change"].__setitem__("unknown", "value"),
        lambda payload: payload["change"].__setitem__("version", "1"),
        lambda payload: payload.__setitem__("status", {}),
        lambda payload: payload["status"].__setitem__("structural_valid", "yes"),
        lambda payload: payload["status"].__setitem__("state", "ready"),
        lambda payload: payload["status"]["missing_requirements"].append(None),
        lambda payload: payload.__setitem__("warnings", [None]),
        lambda payload: payload.__setitem__(
            "warnings", [{"code": "", "message": "bad"}]
        ),
        lambda payload: payload.__setitem__(
            "warnings", [{"code": "bad", "message": "bad", "unknown": True}]
        ),
        lambda payload: payload.__setitem__("affected_files", ["../escape"]),
        lambda payload: payload.__setitem__("post_digest", PRE_DIGEST),
    ],
    ids=[
        "empty-change",
        "unknown-change-field",
        "wrong-change-type",
        "empty-status",
        "wrong-status-type",
        "invalid-status-invariant",
        "invalid-status-finding",
        "null-record-warning",
        "empty-record-warning-code",
        "unknown-record-warning-field",
        "unsafe-affected-file",
        "status-digest-disagrees-with-post-digest",
    ],
)
def test_list_and_latest_skip_invalid_nested_success_payloads_without_raising(
    tmp_path: Path,
    corrupt: object,
) -> None:
    store, path = _published_success(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert callable(corrupt)
    corrupt(payload)
    _rewrite_payload(path, payload)

    with pytest.warns(ChangeRecordWarning, match=r"Skipped malformed change record .*ValueError"):
        assert store.list_records() == []
    with pytest.warns(ChangeRecordWarning, match=r"Skipped malformed change record .*ValueError"):
        assert store.latest() is None


@pytest.mark.parametrize(
    "corrupt",
    [
        lambda payload: payload.__setitem__("error", {}),
        lambda payload: payload["error"].__setitem__("details", []),
        lambda payload: payload["error"].__setitem__("result", None),
        lambda payload: payload["error"].__setitem__("code", ""),
        lambda payload: payload["error"].__setitem__("message", 7),
        lambda payload: payload.__setitem__("post_digest", POST_DIGEST),
        lambda payload: (
            payload.__setitem__("outcome", "success"),
            payload.__setitem__("status", _status().to_payload()),
        ),
    ],
    ids=[
        "empty-error",
        "wrong-error-details-type",
        "wrong-error-result-type",
        "empty-error-code",
        "wrong-error-message-type",
        "failure-post-digest",
        "mutually-exclusive-outcome-branches",
    ],
)
def test_list_and_latest_skip_invalid_failure_payloads_without_raising(
    tmp_path: Path,
    corrupt: object,
) -> None:
    store = _store(tmp_path)
    path = store.write_failure(
        change_id="failed",
        change=_change(),
        pre_digest=PRE_DIGEST,
        affected_files=[],
        error=AuthoringError("model_invalid", "Candidate validation failed"),
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert callable(corrupt)
    corrupt(payload)
    _rewrite_payload(path, payload)

    with pytest.warns(ChangeRecordWarning, match=r"Skipped malformed change record .*ValueError"):
        assert store.list_records(include_failed=True) == []
    with pytest.warns(ChangeRecordWarning, match=r"Skipped malformed change record .*ValueError"):
        assert store.latest(include_failed=True) is None


def test_stage_success_rejects_status_digest_that_disagrees_with_post_digest(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    staged = _stage_path(tmp_path)
    mismatched = ModelStatus(
        model_digest=PRE_DIGEST,
        structural_valid=True,
        smoke_eligible=False,
        state="incomplete",
    )

    with pytest.raises(ValueError, match="status model_digest"):
        store.stage_success(
            staged,
            change_id="mismatched",
            change=_change(),
            pre_digest=PRE_DIGEST,
            post_digest=POST_DIGEST,
            affected_files=[],
            status=mismatched,
        )

    assert not staged.exists()


def test_stage_success_rejects_warning_fields_outside_the_record_schema(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    staged = _stage_path(tmp_path)

    with pytest.raises(ValueError, match="warning keys"):
        store.stage_success(
            staged,
            change_id="bad-warning",
            change=_change(),
            pre_digest=PRE_DIGEST,
            post_digest=POST_DIGEST,
            affected_files=[],
            status=_status(),
            warnings=[{"code": "note", "message": "Note", "unknown": True}],
        )

    assert not staged.exists()


def test_write_failure_rejects_an_invalid_error_envelope_before_persistence(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)

    with pytest.raises(ValueError, match="error code"):
        store.write_failure(
            change_id="bad-error",
            change=_change(),
            pre_digest=PRE_DIGEST,
            affected_files=[],
            error=AuthoringError("", "Candidate validation failed"),
        )

    assert not (tmp_path / "changes" / "failed").exists()


def test_list_and_latest_skip_excessively_deep_json_without_recursion_escape(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    path = tmp_path / "changes" / "20260715T040506789012Z-deep.json"
    path.write_text("[" * 10_000 + "0" + "]" * 10_000, encoding="utf-8")

    with pytest.warns(ChangeRecordWarning, match=r"deep.json.*ValueError"):
        assert store.list_records() == []
    with pytest.warns(ChangeRecordWarning, match=r"deep.json.*ValueError"):
        assert store.latest() is None


def test_list_and_latest_skip_record_larger_than_four_mibibytes_boundedly(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    path = tmp_path / "changes" / "20260715T040506789012Z-oversized.json"
    with path.open("wb") as handle:
        handle.seek(4 * 1024 * 1024)
        handle.write(b"}")

    with pytest.warns(ChangeRecordWarning, match=r"oversized.json.*ValueError"):
        assert store.list_records() == []
    with pytest.warns(ChangeRecordWarning, match=r"oversized.json.*ValueError"):
        assert store.latest() is None


def test_stage_success_accepts_exact_size_limit_and_atomically_rejects_one_byte_more(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    baseline = _stage_path(tmp_path, "baseline.json")
    store.stage_success(
        baseline,
        change_id="baseline",
        change=_change(),
        pre_digest=PRE_DIGEST,
        post_digest=POST_DIGEST,
        affected_files=[],
        status=_status(),
        warnings=[{"code": "padding", "message": "x"}],
    )
    padding_length = 1 + MAX_RECORD_BYTES - baseline.stat().st_size
    baseline.unlink()
    assert padding_length > 1

    exact_stage = _stage_path(tmp_path, "exact.json")
    exact_destination = store.stage_success(
        exact_stage,
        change_id="exact",
        change=_change(),
        pre_digest=PRE_DIGEST,
        post_digest=POST_DIGEST,
        affected_files=[],
        status=_status(),
        warnings=[{"code": "padding", "message": "x" * padding_length}],
    )
    assert exact_stage.stat().st_size == MAX_RECORD_BYTES
    _publish(exact_stage, exact_destination)
    assert store.latest() is not None

    oversized_stage = _stage_path(tmp_path, "oversized-stage.json")
    with pytest.raises(AuthoringError) as caught:
        store.stage_success(
            oversized_stage,
            change_id="too-large",
            change=_change(),
            pre_digest=PRE_DIGEST,
            post_digest=POST_DIGEST,
            affected_files=[],
            status=_status(),
            warnings=[
                {"code": "padding", "message": "x" * (padding_length + 1)}
            ],
        )

    assert caught.value.code == "audit_failed"
    assert caught.value.details["path"] == str(oversized_stage)
    assert not oversized_stage.exists()
    assert not (
        tmp_path / "changes" / "20260715T040506789012Z-too-large.json"
    ).exists()
    assert not list(oversized_stage.parent.glob(f".{oversized_stage.name}.*.tmp"))


def test_write_failure_accepts_exact_size_limit_and_atomically_rejects_one_byte_more(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    baseline = store.write_failure(
        change_id="baseline",
        change=_change(),
        pre_digest=PRE_DIGEST,
        affected_files=[],
        error=AuthoringError(
            "model_invalid",
            "Candidate validation failed",
            {"padding": ""},
        ),
    )
    padding_length = MAX_RECORD_BYTES - baseline.stat().st_size
    baseline.unlink()
    assert padding_length > 0

    exact = store.write_failure(
        change_id="exact",
        change=_change(),
        pre_digest=PRE_DIGEST,
        affected_files=[],
        error=AuthoringError(
            "model_invalid",
            "Candidate validation failed",
            {"padding": "x" * padding_length},
        ),
    )
    assert exact.stat().st_size == MAX_RECORD_BYTES
    assert store.latest(include_failed=True) is not None

    oversized = (
        tmp_path
        / "changes"
        / "failed"
        / "20260715T040506789012Z-too-large.json"
    )
    with pytest.raises(AuthoringError) as caught:
        store.write_failure(
            change_id="too-large",
            change=_change(),
            pre_digest=PRE_DIGEST,
            affected_files=[],
            error=AuthoringError(
                "model_invalid",
                "Candidate validation failed",
                {"padding": "x" * (padding_length + 1)},
            ),
        )

    assert caught.value.code == "audit_failed"
    assert caught.value.details["path"] == str(oversized)
    assert not oversized.exists()
    assert not list(oversized.parent.glob(f".{oversized.name}.*.tmp"))


def _directory_symlink(target: Path, link: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"directory symlinks are unavailable: {error}")


def test_registry_root_symlink_is_rejected_before_read_or_write(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_store = ChangeRecordStore(outside, clock=lambda: UTC_INSTANT)
    outside_stage = _stage_path(tmp_path, "outside.json")
    outside_destination = outside_store.stage_success(
        outside_stage,
        change_id="outside",
        change=_change(),
        pre_digest=PRE_DIGEST,
        post_digest=POST_DIGEST,
        affected_files=[],
        status=_status(),
    )
    _publish(outside_stage, outside_destination)

    project = tmp_path / "project"
    project.mkdir()
    linked_changes = project / "changes"
    _directory_symlink(outside, linked_changes)
    store = ChangeRecordStore(linked_changes, clock=lambda: UTC_INSTANT)

    with pytest.raises(AuthoringError) as list_error:
        store.list_records()
    assert list_error.value.code == "audit_failed"
    with pytest.raises(AuthoringError) as latest_error:
        store.latest()
    assert latest_error.value.code == "audit_failed"

    staged = _stage_path(tmp_path, "linked-root.json")
    with pytest.raises(AuthoringError) as stage_error:
        store.stage_success(
            staged,
            change_id="must-not-stage",
            change=_change(),
            pre_digest=PRE_DIGEST,
            post_digest=POST_DIGEST,
            affected_files=[],
            status=_status(),
        )
    assert stage_error.value.code == "audit_failed"
    assert not staged.exists()

    with pytest.raises(AuthoringError) as failure_error:
        store.write_failure(
            change_id="must-not-fail",
            change=_change(),
            pre_digest=PRE_DIGEST,
            affected_files=[],
            error=AuthoringError("model_invalid", "Candidate validation failed"),
        )
    assert failure_error.value.code == "audit_failed"
    assert not (outside / "failed" / "20260715T040506789012Z-must-not-fail.json").exists()


def test_failed_registry_symlink_is_rejected_before_enumeration(tmp_path: Path) -> None:
    changes = tmp_path / "changes"
    changes.mkdir()
    outside_failed = tmp_path / "outside-failed"
    outside_failed.mkdir()
    failed_link = changes / "failed"
    _directory_symlink(outside_failed, failed_link)
    store = ChangeRecordStore(changes, clock=lambda: UTC_INSTANT)

    with pytest.raises(AuthoringError) as caught:
        store.list_records(include_failed=True)

    assert caught.value.code == "audit_failed"


def test_same_inode_same_length_rewrite_during_read_is_skipped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, path = _published_success(tmp_path)
    real_read = os.read
    mutated = False

    def mutating_read(descriptor: int, count: int) -> bytes:
        nonlocal mutated
        content = real_read(descriptor, count)
        if not mutated:
            before = path.read_bytes()
            after = before.replace(b"Review", b"Beware", 1)
            assert after != before and len(after) == len(before)
            path.write_bytes(after)
            mutated = True
        return content

    monkeypatch.setattr(change_records_module.os, "read", mutating_read)

    with pytest.warns(ChangeRecordWarning, match=r"valid.json.*ValueError"):
        assert store.list_records() == []
    assert mutated


def test_rename_then_symlink_back_to_original_inode_during_read_is_skipped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, path = _published_success(tmp_path)
    original = tmp_path / "original-record.json"
    real_read = os.read
    retargeted = False

    def retargeting_read(descriptor: int, count: int) -> bytes:
        nonlocal retargeted
        content = real_read(descriptor, count)
        if not retargeted:
            try:
                path.replace(original)
                path.symlink_to(original)
            except OSError as error:
                pytest.skip(f"open-file retargeting is unavailable: {error}")
            retargeted = True
        return content

    monkeypatch.setattr(change_records_module.os, "read", retargeting_read)

    with pytest.warns(ChangeRecordWarning, match=r"valid.json.*ValueError"):
        assert store.list_records() == []
    assert retargeted


@pytest.mark.parametrize(
    "unsafe_path",
    [
        "C:/outside/file.json",
        "C:\\outside\\file.json",
        "\\\\server\\share\\file.json",
        "\\rooted\\file.json",
        "/rooted/file.json",
    ],
)
def test_stage_success_rejects_windows_and_posix_absolute_affected_files(
    tmp_path: Path,
    unsafe_path: str,
) -> None:
    store = _store(tmp_path)
    staged = _stage_path(tmp_path)

    with pytest.raises(ValueError, match="project-relative"):
        store.stage_success(
            staged,
            change_id="unsafe-path",
            change=_change(),
            pre_digest=PRE_DIGEST,
            post_digest=POST_DIGEST,
            affected_files=[unsafe_path],
            status=_status(),
        )

    assert not staged.exists()


def test_reader_skips_windows_drive_affected_file_path(tmp_path: Path) -> None:
    store, path = _published_success(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["affected_files"] = ["C:/outside/file.json"]
    _rewrite_payload(path, payload)

    with pytest.warns(ChangeRecordWarning, match=r"valid.json.*ValueError"):
        assert store.list_records() == []


@pytest.mark.parametrize(
    "corrupt",
    [
        lambda payload: payload.__setitem__("version", True),
        lambda payload: payload["change"].__setitem__("version", True),
        lambda payload: payload["status"]["entity_counts"].__setitem__(
            "resource", True
        ),
    ],
    ids=["record-version", "change-version", "status-count"],
)
def test_reader_rejects_bool_values_in_integer_fields(
    tmp_path: Path,
    corrupt: object,
) -> None:
    store, path = _published_success(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert callable(corrupt)
    corrupt(payload)
    _rewrite_payload(path, payload)

    with pytest.warns(ChangeRecordWarning, match=r"valid.json.*ValueError"):
        assert store.list_records() == []
