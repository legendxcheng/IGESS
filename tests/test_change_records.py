from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path

import pytest

from igess.authoring.change import ModelChange
from igess.authoring.change_records import ChangeRecordStore, ChangeRecordWarning
from igess.authoring.probe import EligibilityFinding
from igess.authoring.response import AuthoringError
from igess.authoring.status import ModelStatus


UTC_INSTANT = datetime(2026, 7, 15, 4, 5, 6, 789012, tzinfo=timezone.utc)
PRE_DIGEST = "sha256:" + "1" * 64
POST_DIGEST = "sha256:" + "2" * 64


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

