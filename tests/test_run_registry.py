from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from igess.authoring import AuthoringProject
from igess.authoring.templates import initialize_authoring_project
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


def test_prune_smoke_rejects_negative_retention(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="non-negative"):
        RunRegistry(tmp_path / "runs").prune_smoke(keep=-1)
