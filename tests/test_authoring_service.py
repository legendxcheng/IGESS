from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import replace
import json
from pathlib import Path
from typing import Any

import pytest

from igess.authoring.change import ModelChange
from igess.authoring.change_records import ChangeRecordStore
from igess.authoring.response import AuthoringError
from igess.authoring.service import AuthoringService
from igess.authoring.probe import EligibilityFinding, TenTickProbeResult, run_ten_tick_probe
from igess.authoring.status import derive_status
from igess.authoring.templates import initialize_authoring_project
from igess.authoring.transactions import Transaction
from igess.outputs import OutputWriter
from igess.run_registry import RunRegistry


FIXED_NOW = datetime(2026, 7, 16, 8, 9, 10, tzinfo=timezone.utc)


def _service(root: Path, ids: list[str] | None = None, **overrides: object) -> AuthoringService:
    values = iter(ids or ["change-1", "change-2", "change-3", "change-4"])
    return AuthoringService(
        root,
        clock=lambda: FIXED_NOW,
        id_factory=lambda: next(values),
        **overrides,
    )


def _change(entity: str, entity_id: str, fields: dict[str, object], digest: str | None = None) -> ModelChange:
    return ModelChange(1, "upsert", entity, entity_id, fields, digest)


def _resource(digest: str | None = None) -> ModelChange:
    return _change("resource", "gold", {"name": "Gold", "dimension": "currency"}, digest)


def _add_runnable_activity(service: AuthoringService) -> None:
    assert service.apply(_resource()).ok
    assert service.apply(
        _change(
            "activity",
            "gather",
            {"name": "Gather", "source_type": "active", "unlock_condition": "always"},
        )
    ).ok
    assert service.apply(
        _change(
            "activity_output",
            "gather_gold",
            {
                "activity_id": "gather",
                "output_resource": "gold",
                "amount_per_second": "1",
            },
        )
    ).ok
    assert service.apply(
        _change(
            "player_profile",
            "default",
            {
                "source_efficiency": {
                    "active": "1",
                    "generator": "1",
                    "offline": "1",
                    "milestone": "1",
                    "prestige": "1",
                },
                "behavior_policy": "cheap_unlock_first",
                "session_pattern": "authoring_default",
                "prestige_policy": "conservative",
                "activity_weights": {"gather": "1"},
                "luck": "1",
            },
        )
    ).ok


def _formal_bytes(root: Path) -> dict[str, bytes]:
    paths = [root / "economy.yaml", *(root / "Datas").glob("*.xlsx")]
    paths.extend(path for path in (root / "luban_exports").rglob("*") if path.is_file())
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(paths, key=lambda item: item.as_posix())
    }


class _CountingStore:
    def __init__(
        self,
        project_root: Path,
        *,
        stage_failure: Exception | None = None,
        failed_failure: Exception | None = None,
    ) -> None:
        self.delegate = ChangeRecordStore(project_root / "changes", clock=lambda: FIXED_NOW)
        self.stage_failure = stage_failure
        self.failed_failure = failed_failure
        self.failure_calls = 0

    def stage_success(self, *args: object, **kwargs: object) -> Path:
        if self.stage_failure is not None:
            raise self.stage_failure
        return self.delegate.stage_success(*args, **kwargs)  # type: ignore[arg-type]

    def write_failure(self, **kwargs: object) -> Path:
        self.failure_calls += 1
        if self.failed_failure is not None:
            raise self.failed_failure
        return self.delegate.write_failure(**kwargs)  # type: ignore[arg-type]


def _counting_store_factory(
    root: Path,
    stores: list[_CountingStore],
    *,
    stage_failure: Exception | None = None,
    failed_failure: Exception | None = None,
):
    def factory(_project: object, _clock: object) -> _CountingStore:
        store = _CountingStore(
            root,
            stage_failure=stage_failure,
            failed_failure=failed_failure,
        )
        stores.append(store)
        return store

    return factory


def test_init_and_status_return_exact_typed_contracts(tmp_path: Path) -> None:
    root = tmp_path / "my model"
    service = AuthoringService(clock=lambda: FIXED_NOW, id_factory=lambda: "unused")

    initialized = service.init(root)

    assert initialized.ok is True
    assert initialized.code == "initialized"
    assert initialized.result == {
        "project": str(root),
        "model_id": "my_model",
        "config": str(root / "economy.yaml"),
        "datas": str(root / "Datas"),
        "tables": str(root / "Datas" / "__tables__.xlsx"),
        "readme": str(root / "README.md"),
        "run_script": str(root / "run.ps1"),
    }

    status = _service(root).status()
    assert status.ok is True
    assert status.code == "status"
    assert set(status.result) == {
        "model_digest",
        "structural_valid",
        "smoke_eligible",
        "state",
        "entity_counts",
        "missing_requirements",
        "warnings",
        "available_scenarios",
        "latest_smoke_run_id",
    }
    assert status.result["state"] == "incomplete"
    assert status.result["structural_valid"] is True
    assert status.result["smoke_eligible"] is False


def test_incomplete_apply_commits_sources_exports_and_success_audit_without_run(tmp_path: Path) -> None:
    root = initialize_authoring_project(tmp_path / "model", "service_test")
    service = _service(root)

    response = service.apply(_resource())
    result = response.to_payload()["result"]

    assert response.ok is True
    assert response.code == "applied"
    assert set(result) == {
        "change_id",
        "entity",
        "id",
        "changed_files",
        "status",
        "smoke",
    }
    assert result["change_id"] == "change-1"
    assert result["entity"] == "resource"
    assert result["id"] == "gold"
    assert result["changed_files"] == ["Datas/resources.xlsx", "luban_exports"]
    assert result["status"]["state"] == "incomplete"
    assert result["smoke"] == {
        "status": "not_run",
        "run_id": None,
        "findings": [],
    }
    assert not list((root / "runs").iterdir())
    records = list((root / "changes").glob("*.json"))
    assert len(records) == 1
    assert json.loads(records[0].read_text(encoding="utf-8"))["outcome"] == "success"
    assert list((root / "luban_exports").glob("*.json"))


def test_automatic_smoke_is_correlated_attributable_and_pruned_only_after_apply(tmp_path: Path) -> None:
    root = initialize_authoring_project(tmp_path / "model", "service_test")
    service = _service(root)
    _add_runnable_activity(service)

    response = service.status()
    assert response.result["state"] == "runnable"
    run_id = response.result["latest_smoke_run_id"]
    assert isinstance(run_id, str) and run_id.endswith("-smoke-change-4")
    run_dir = root / "runs" / run_id
    status = json.loads((run_dir / "run_status.json").read_text(encoding="utf-8"))
    manifest = json.loads((run_dir / "output" / "run_manifest.json").read_text(encoding="utf-8"))
    report = json.loads((run_dir / "report" / "report_data.json").read_text(encoding="utf-8"))
    assert status["kind"] == "smoke"
    assert status["change_id"] == "change-4"
    assert status["model_digest"] == response.result["model_digest"]
    assert manifest["model_digest"] == response.result["model_digest"]
    assert report["scenario"]["model_digest"] == response.result["model_digest"]


def test_manual_simulate_uses_ephemeral_exports_and_is_always_formal(tmp_path: Path) -> None:
    root = initialize_authoring_project(tmp_path / "model", "service_test")
    service = _service(root)
    _add_runnable_activity(service)
    committed_before = {
        path.name: path.read_bytes() for path in (root / "luban_exports").glob("*.json")
    }

    response = service.simulate()

    assert response.ok is True
    assert set(response.result) == {
        "run_id",
        "kind",
        "scenario_id",
        "status",
        "output_dir",
        "report_index",
        "change_id",
    }
    assert response.result["kind"] == "formal"
    assert response.result["scenario_id"] == "smoke"
    assert response.result["change_id"] is None
    assert "-smoke-change-" not in response.result["run_id"]
    assert {
        path.name: path.read_bytes() for path in (root / "luban_exports").glob("*.json")
    } == committed_before


def test_eligible_no_state_change_commits_probe_and_keeps_incomplete_status(tmp_path: Path) -> None:
    root = initialize_authoring_project(tmp_path / "model", "service_test")
    initial = _service(root, ids=["setup-1", "setup-2", "setup-3", "setup-4"])
    _add_runnable_activity(initial)
    finding = EligibilityFinding(
        "smoke_no_state_change",
        "The ten-tick smoke probe completed without an observable state change.",
    )

    def incomplete_status(project: object, latest: object):
        status = derive_status(project, latest)  # type: ignore[arg-type]
        return replace(
            status,
            state="incomplete",
            missing_requirements=(*status.missing_requirements, finding),
        )

    def no_change_probe(*args: object) -> TenTickProbeResult:
        probe = run_ten_tick_probe(*args)  # type: ignore[arg-type]
        return TenTickProbeResult(False, (finding,), probe.artifacts, probe.report_index)

    response = _service(
        root,
        ids=["no-change"],
        status_deriver=incomplete_status,
        probe_runner=no_change_probe,
    ).apply(_resource())
    result = response.to_payload()["result"]

    assert response.ok is True
    assert result["status"]["state"] == "incomplete"
    assert result["status"]["missing_requirements"][-1]["code"] == "smoke_no_state_change"
    assert result["smoke"]["findings"] == [finding.to_payload()]
    assert (root / "runs" / result["smoke"]["run_id"] / "run_status.json").is_file()


def test_explicit_scenario_simulate_is_formal_and_manual_runs_never_prune(tmp_path: Path) -> None:
    root = initialize_authoring_project(tmp_path / "model", "service_test")
    initial = _service(
        root,
        ids=["setup-1", "setup-2", "setup-3", "setup-4", "setup-5"],
    )
    _add_runnable_activity(initial)
    assert initial.apply(
        _change(
            "scenario",
            "formal_day",
            {
                "duration_hours": "0.002777777777777778",
                "time_mode": "tick",
                "profiles": ["default"],
                "start_state": "new_player",
                "record_interval_seconds": 1,
                "outputs": ["resource_curve"],
            },
        )
    ).ok

    class TrackingRegistry(RunRegistry):
        prune_calls = 0

        def prune_smoke(self, keep: int = 20) -> list[str]:
            self.prune_calls += 1
            return super().prune_smoke(keep)

    registry = TrackingRegistry(root / "runs")
    response = _service(root, registry_factory=lambda _project: registry).simulate("formal_day")

    assert response.ok is True
    assert response.result["scenario_id"] == "formal_day"
    assert response.result["kind"] == "formal"
    assert response.result["change_id"] is None
    assert response.result["run_id"].endswith("-formal_day")
    assert registry.prune_calls == 0


def test_failed_manual_simulation_is_attributable_and_recovery_warning_is_returned(tmp_path: Path) -> None:
    root = initialize_authoring_project(tmp_path / "model", "service_test")
    initial = _service(root, ids=["setup-1", "setup-2", "setup-3", "setup-4"])
    _add_runnable_activity(initial)

    class BrokenSimulator:
        def run_scenario(self, _scenario_id: str) -> None:
            raise RuntimeError("engine failed")

    response = _service(
        root,
        simulator_factory=lambda _model: BrokenSimulator(),
        recoverer=lambda _project: [
            {"code": "recovered_transaction", "message": "Recovered old change"}
        ],
    ).simulate()

    assert response.ok is False
    assert response.code == "simulation_failed"
    result = response.to_payload()["result"]
    assert result["kind"] == "formal"
    assert result["status"] == "failed"
    assert result["change_id"] is None
    stored = json.loads(
        (root / "runs" / result["run_id"] / "run_status.json").read_text(encoding="utf-8")
    )
    assert stored["model_digest"].startswith("sha256:")
    assert response.to_payload()["details"]["warnings"][0]["code"] == "recovered_transaction"


def test_invalid_proposal_before_change_identity_has_no_failed_audit(tmp_path: Path) -> None:
    root = initialize_authoring_project(tmp_path / "model", "service_test")
    service = _service(root)

    response = service.apply(object())  # type: ignore[arg-type]

    assert response.ok is False
    assert response.code == "invalid_change"
    assert not (root / "changes" / "failed").exists()


def test_apply_accepts_strict_text_and_merges_partial_existing_entity_under_lock(
    tmp_path: Path,
) -> None:
    root = initialize_authoring_project(tmp_path / "model", "service_test")
    service = _service(root, ids=["create", "update"])
    assert service.apply(_resource()).ok

    response = service.apply(
        """version: 1
operation: upsert
entity: resource
id: gold
fields:
  name: Golden coins
"""
    )

    assert response.ok is True
    assert response.result["id"] == "gold"
    assert response.result["changed_files"] == (
        "Datas/resources.xlsx",
        "luban_exports",
    )
    exported = json.loads(
        (root / "luban_exports" / "resources.json").read_text(encoding="utf-8")
    )
    assert len(exported) == 1
    assert {key: exported[0][key] for key in ("dimension", "id", "name")} == {
        "dimension": "currency",
        "id": "gold",
        "name": "Golden coins",
    }


def test_invalid_text_before_change_identity_has_no_failed_audit(tmp_path: Path) -> None:
    root = initialize_authoring_project(tmp_path / "model", "service_test")
    response = _service(root).apply("version: [")

    assert response.ok is False
    assert response.code == "invalid_change"
    assert not (root / "changes" / "failed").exists()


def test_output_writer_omits_legacy_digest_and_writes_exact_authoring_digest(tmp_path: Path) -> None:
    from igess.builder import ModelBuilder
    from igess.loader import ConfigLoader
    from igess.simulator import Simulator

    model = ModelBuilder.build(
        ConfigLoader.load("examples/shelldiver_v0/economy.yaml", "examples/shelldiver_v0/luban_exports")
    )
    result = Simulator(model).run_scenario("analytic_smoke")
    legacy = tmp_path / "legacy"
    authoring = tmp_path / "authoring"
    digest = "sha256:" + "a" * 64

    OutputWriter.write_all(result, legacy, model)
    OutputWriter.write_all(result, authoring, model, model_digest=digest)

    assert "model_digest" not in json.loads((legacy / "run_manifest.json").read_text(encoding="utf-8"))
    assert json.loads((authoring / "run_manifest.json").read_text(encoding="utf-8"))["model_digest"] == digest


@pytest.mark.parametrize(
    ("override", "expected_code"),
    [
        ({"candidate_mapper": lambda *_: (_ for _ in ()).throw(RuntimeError("mapping"))}, "invalid_change"),
        ({"candidate_exporter": lambda *_: (_ for _ in ()).throw(RuntimeError("export"))}, "export_failed"),
        ({"loader": lambda *_: (_ for _ in ()).throw(RuntimeError("load"))}, "model_invalid"),
        ({"linter": lambda *_: (_ for _ in ()).throw(RuntimeError("lint"))}, "model_invalid"),
        ({"builder": lambda *_: (_ for _ in ()).throw(RuntimeError("build"))}, "model_invalid"),
        ({"status_deriver": lambda *_: (_ for _ in ()).throw(RuntimeError("status"))}, "model_invalid"),
    ],
    ids=["mapping", "export", "load", "lint", "build", "status-probe"],
)
def test_precommit_phase_failure_restores_formal_state_and_writes_one_failed_audit(
    tmp_path: Path,
    override: dict[str, Any],
    expected_code: str,
) -> None:
    root = initialize_authoring_project(tmp_path / "model", "failure_test")
    before = _formal_bytes(root)
    stores: list[_CountingStore] = []
    service = _service(
        root,
        record_store_factory=_counting_store_factory(root, stores),
        **override,
    )

    response = service.apply(_resource())

    assert response.ok is False
    assert response.code == expected_code
    assert _formal_bytes(root) == before
    assert len(stores) == 1
    assert stores[0].failure_calls == 1
    assert len(list((root / "changes" / "failed").glob("*.json"))) == 1
    assert not list((root / ".igess" / "transactions").glob("change-1"))


@pytest.mark.parametrize("phase", ["execution", "artifact"])
def test_smoke_failure_restores_formal_state_and_is_audited_once(
    tmp_path: Path,
    phase: str,
) -> None:
    root = initialize_authoring_project(tmp_path / "model", "failure_test")
    initial = _service(root, ids=["setup-1", "setup-2", "setup-3", "setup-4"])
    _add_runnable_activity(initial)
    before = _formal_bytes(root)
    runs_before = {path.name for path in (root / "runs").iterdir()}
    stores: list[_CountingStore] = []

    def fail_probe(*_args: object) -> None:
        raise AuthoringError(
            "smoke_failed",
            f"Smoke failed during {phase}",
            {"phase": phase},
        )

    overrides: dict[str, object] = {
        "record_store_factory": _counting_store_factory(root, stores)
    }
    if phase == "execution":
        overrides["probe_runner"] = fail_probe
    else:
        overrides["report_writer"] = lambda *_: (_ for _ in ()).throw(
            OSError("artifact media failed")
        )
    service = _service(root, ids=["failed-smoke"], **overrides)
    response = service.apply(_resource())

    assert response.ok is False
    assert response.code == "smoke_failed"
    assert response.details["phase"] == phase
    assert _formal_bytes(root) == before
    assert {path.name for path in (root / "runs").iterdir()} == runs_before
    assert stores[0].failure_calls == 1


def test_success_audit_stage_failure_rolls_back_then_writes_failure_record(tmp_path: Path) -> None:
    root = initialize_authoring_project(tmp_path / "model", "failure_test")
    before = _formal_bytes(root)
    stores: list[_CountingStore] = []
    service = _service(
        root,
        record_store_factory=_counting_store_factory(
            root,
            stores,
            stage_failure=OSError("success audit media failed"),
        ),
    )

    response = service.apply(_resource())

    assert response.ok is False
    assert response.code == "audit_failed"
    assert _formal_bytes(root) == before
    assert stores[0].failure_calls == 1
    assert len(list((root / "changes" / "failed").glob("*.json"))) == 1


def test_persistent_failed_audit_media_failure_keeps_rollback_and_reports_unwritten_path(
    tmp_path: Path,
) -> None:
    root = initialize_authoring_project(tmp_path / "model", "failure_test")
    before = _formal_bytes(root)
    stores: list[_CountingStore] = []
    unwritten = root / "changes" / "failed" / "unwritten.json"
    service = _service(
        root,
        record_store_factory=_counting_store_factory(
            root,
            stores,
            stage_failure=OSError("success audit media failed"),
            failed_failure=AuthoringError(
                "audit_failed",
                "failed audit media failed",
                {"path": str(unwritten)},
            ),
        ),
    )

    response = service.apply(_resource())

    assert response.ok is False
    assert response.code == "audit_failed"
    assert response.details["unwritten_audit_path"] == str(unwritten)
    assert response.details["original_code"] == "audit_failed"
    assert _formal_bytes(root) == before
    assert stores[0].failure_calls == 1


def test_proposal_and_precommit_digest_staleness_share_stable_code_and_one_audit(
    tmp_path: Path,
) -> None:
    for case in ("proposal", "precommit"):
        root = initialize_authoring_project(tmp_path / case, "stale_test")
        before = _formal_bytes(root)
        stores: list[_CountingStore] = []
        overrides: dict[str, object] = {
            "record_store_factory": _counting_store_factory(root, stores)
        }
        change = _resource("sha256:" + "0" * 64) if case == "proposal" else _resource()
        if case == "precommit":
            overrides["transaction_factory"] = lambda project, change_id, digest: Transaction(
                project,
                change_id,
                digest,
                digest_reader=lambda: "sha256:" + "f" * 64,
            )
        response = _service(root, **overrides).apply(change)

        assert response.ok is False
        assert response.code == "stale_model"
        assert _formal_bytes(root) == before
        assert stores[0].failure_calls == 1


@pytest.mark.parametrize(
    "checkpoint",
    [
        "stale_digest_recheck",
        "journal_committing",
        "target:0:Datas/resources.xlsx",
        "target:1:luban_exports",
        "staged_change",
    ],
)
def test_each_incomplete_transaction_commit_checkpoint_failure_restores_and_audits(
    tmp_path: Path,
    checkpoint: str,
) -> None:
    root = initialize_authoring_project(tmp_path / checkpoint.replace(":", "_"), "commit_test")
    before = _formal_bytes(root)
    stores: list[_CountingStore] = []

    def transaction_factory(project: object, change_id: str, digest: str) -> Transaction:
        def fail(name: str) -> None:
            if name == checkpoint:
                raise OSError(checkpoint)

        return Transaction(project, change_id, digest, checkpoint=fail)  # type: ignore[arg-type]

    response = _service(
        root,
        transaction_factory=transaction_factory,
        record_store_factory=_counting_store_factory(root, stores),
    ).apply(_resource())

    assert response.ok is False
    assert response.code == "commit_failed"
    assert _formal_bytes(root) == before
    assert stores[0].failure_calls == 1
    assert not list((root / "changes").glob("*.json"))


def test_staged_smoke_move_commit_failure_restores_sources_exports_and_run(tmp_path: Path) -> None:
    root = initialize_authoring_project(tmp_path / "model", "commit_test")
    initial = _service(root, ids=["setup-1", "setup-2", "setup-3", "setup-4"])
    _add_runnable_activity(initial)
    before = _formal_bytes(root)
    runs_before = {path.name for path in (root / "runs").iterdir()}
    stores: list[_CountingStore] = []

    def transaction_factory(project: object, change_id: str, digest: str) -> Transaction:
        def fail(name: str) -> None:
            if name == "staged_run":
                raise OSError(name)

        return Transaction(project, change_id, digest, checkpoint=fail)  # type: ignore[arg-type]

    response = _service(
        root,
        ids=["failed-smoke"],
        transaction_factory=transaction_factory,
        record_store_factory=_counting_store_factory(root, stores),
    ).apply(_resource())

    assert response.ok is False
    assert response.code == "commit_failed"
    assert _formal_bytes(root) == before
    assert {path.name for path in (root / "runs").iterdir()} == runs_before
    assert stores[0].failure_calls == 1


def test_status_failure_is_full_typed_and_recovery_warnings_are_merged(tmp_path: Path) -> None:
    root = initialize_authoring_project(tmp_path / "model", "status_test")
    failed = _service(
        root,
        status_deriver=lambda *_: (_ for _ in ()).throw(RuntimeError("status failed")),
    ).status()

    assert failed.ok is False
    assert failed.code == "model_invalid"
    assert set(failed.to_payload()["result"]) == {
        "model_digest",
        "structural_valid",
        "smoke_eligible",
        "state",
        "entity_counts",
        "missing_requirements",
        "warnings",
        "available_scenarios",
        "latest_smoke_run_id",
    }
    assert failed.result["state"] == "failed"

    recovered = _service(
        root,
        recoverer=lambda _project: [
            {
                "code": "recovered_transaction",
                "message": "Recovered interrupted change",
                "change_id": "old-change",
            }
        ],
    ).status()
    assert recovered.ok is True
    assert recovered.to_payload()["result"]["warnings"][-1] == {
        "code": "recovered_transaction",
        "message": "Recovered interrupted change",
        "id": "old-change",
    }
