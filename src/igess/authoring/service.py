"""Agent-facing orchestration for incremental model authoring."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import stat
from typing import Any
import uuid

import yaml

from ..builder import ModelBuilder
from ..linter import ConfigLinter
from ..loader import ConfigLoader
from ..outputs import OutputWriter
from ..reporting.static import generate_static_report
from ..run_registry import RunRecord, RunRegistry
from ..simulator import Simulator
from .change import ModelChange, parse_change_text
from .change_records import ChangeRecordStore
from .entity_schema import ENTITY_SCHEMAS, get_entity_schema
from .exports import (
    EphemeralExport,
    ExportResult,
    StagedSources,
    apply_to_candidate,
    ephemeral_export,
    export_candidate,
    stage_sources,
)
from .locking import project_lock
from .probe import EligibilityFinding, TenTickProbeResult, run_ten_tick_probe
from .project import AuthoringProject
from .response import AuthoringError, CommandResponse
from .status import ModelStatus, derive_status
from .templates import initialize_authoring_project
from .transactions import Transaction, recover_transactions
from .workbook_source import inspect_table
from .yaml_source import read_yaml_entity


_CHANGE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_RUN_ID_ATTEMPTS = 16


class RecoveryProjectContext(AuthoringProject):
    """A source-independent, safety-validated project view used only for recovery."""

    __slots__ = ()

    def __init__(self, root: str | os.PathLike[str]) -> None:
        if not isinstance(root, (str, os.PathLike)):
            raise TypeError("Recovery project root must be path-like")
        path = Path(root).expanduser()
        try:
            direct = path.lstat()
        except FileNotFoundError:
            raise AuthoringError(
                "project_root_missing",
                f"Authoring project root is missing: {path}",
                {"path": str(path), "reason": "missing"},
            ) from None
        except (OSError, ValueError) as error:
            raise AuthoringError(
                "project_root_inaccessible",
                f"Authoring project root could not be inspected: {path}",
                {
                    "error_type": type(error).__name__,
                    "path": str(path),
                    "reason": "access_error",
                },
            ) from None
        if _is_path_indirection(direct):
            raise AuthoringError(
                "project_root_unsafe",
                f"Authoring project root must not be a link or reparse point: {path}",
                {"path": str(path), "reason": "indirection"},
            )
        if not stat.S_ISDIR(direct.st_mode):
            raise AuthoringError(
                "project_root_wrong_type",
                f"Authoring project root is not a directory: {path}",
                {"path": str(path), "reason": "wrong_type"},
            )
        try:
            canonical = path.resolve(strict=True)
            canonical_identity = canonical.lstat()
        except (OSError, RuntimeError, ValueError) as error:
            raise AuthoringError(
                "project_root_inaccessible",
                f"Authoring project root could not be resolved: {path}",
                {
                    "error_type": type(error).__name__,
                    "path": str(path),
                    "reason": "resolve_error",
                },
            ) from None
        if _is_path_indirection(canonical_identity) or not stat.S_ISDIR(
            canonical_identity.st_mode
        ):
            raise AuthoringError(
                "project_root_unsafe",
                f"Authoring project root is not a stable real directory: {path}",
                {"path": str(path), "reason": "canonical_indirection"},
            )

        metadata = canonical / ".igess"
        object.__setattr__(self, "root", canonical)
        object.__setattr__(self, "config", canonical / "economy.yaml")
        object.__setattr__(self, "datas", canonical / "Datas")
        object.__setattr__(self, "exports", canonical / "luban_exports")
        object.__setattr__(self, "runs", canonical / "runs")
        object.__setattr__(self, "legacy_runs", metadata / "runs")
        object.__setattr__(self, "reports", canonical / "reports")
        object.__setattr__(self, "changes", canonical / "changes")
        object.__setattr__(self, "transactions", metadata / "transactions")
        object.__setattr__(self, "lock", metadata / "model.lock")


@contextmanager
def _shared_project_snapshot(
    project: AuthoringProject,
    recovery_result: object,
):
    with project_lock(project, exclusive=False):
        yield recovery_result


def _default_registry(project: AuthoringProject) -> RunRegistry:
    return RunRegistry(project.runs, read_roots=project.read_run_roots())


def _default_record_store(
    project: AuthoringProject,
    clock: Callable[[], datetime],
) -> ChangeRecordStore:
    return ChangeRecordStore(project.changes, clock=clock)


class AuthoringService:
    """Coordinate project locks, candidates, transactions, audits, and runs.

    All phase collaborators are constructor dependencies.  Production callers
    normally provide only ``project_root``; tests and alternate front ends can
    replace a single phase without patching module globals.
    """

    def __init__(
        self,
        project_root: str | os.PathLike[str] | None = None,
        *,
        project_factory: Callable[[str | os.PathLike[str]], AuthoringProject] = AuthoringProject.discover,
        initializer: Callable[[str | os.PathLike[str], str | None], Path] = initialize_authoring_project,
        transaction_factory: Callable[..., Transaction] = Transaction,
        status_deriver: Callable[[AuthoringProject, Callable[[], object | None]], ModelStatus] = derive_status,
        registry_factory: Callable[[AuthoringProject], RunRegistry] = _default_registry,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
        recoverer: Callable[[AuthoringProject], list[dict[str, str]]] = recover_transactions,
        lock_factory: Callable[[AuthoringProject, bool], AbstractContextManager[None]] = project_lock,
        shared_snapshot_factory: Callable[
            [AuthoringProject, object], AbstractContextManager[object]
        ] = _shared_project_snapshot,
        source_stager: Callable[[AuthoringProject, str | os.PathLike[str]], StagedSources] = stage_sources,
        candidate_mapper: Callable[[StagedSources, ModelChange], tuple[str, ...]] = apply_to_candidate,
        candidate_exporter: Callable[[StagedSources, str | os.PathLike[str]], ExportResult] = export_candidate,
        ephemeral_exporter: Callable[[AuthoringProject], AbstractContextManager[EphemeralExport]] = ephemeral_export,
        loader: Callable[[str | Path, str | Path], object] = ConfigLoader.load,
        linter: Callable[[object], None] = ConfigLinter.validate,
        builder: Callable[[object], object] = ModelBuilder.build,
        probe_runner: Callable[..., TenTickProbeResult] = run_ten_tick_probe,
        simulator_factory: Callable[[object], object] = Simulator,
        output_writer: Callable[..., None] = OutputWriter.write_all,
        report_writer: Callable[..., Path] = generate_static_report,
        record_store_factory: Callable[
            [AuthoringProject, Callable[[], datetime]], ChangeRecordStore
        ] = _default_record_store,
    ) -> None:
        self.project_root = Path(project_root) if project_root is not None else None
        self._project_factory = project_factory
        self._initializer = initializer
        self._transaction_factory = transaction_factory
        self._status_deriver = status_deriver
        self._registry_factory = registry_factory
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self._recoverer = recoverer
        self._lock_factory = lock_factory
        self._shared_snapshot_factory = shared_snapshot_factory
        self._source_stager = source_stager
        self._candidate_mapper = candidate_mapper
        self._candidate_exporter = candidate_exporter
        self._ephemeral_exporter = ephemeral_exporter
        self._loader = loader
        self._linter = linter
        self._builder = builder
        self._probe_runner = probe_runner
        self._simulator_factory = simulator_factory
        self._output_writer = output_writer
        self._report_writer = report_writer
        self._record_store_factory = record_store_factory

    def init(
        self,
        out: str | os.PathLike[str],
        model_id: str | None = None,
    ) -> CommandResponse:
        """Create a blank authoring project and return its canonical paths."""

        recovery: tuple[Mapping[str, object], ...] = ()
        phase = "init"
        try:
            target = Path(out).expanduser()
            if _should_recover_existing_init(target):
                existing_context = RecoveryProjectContext(target)
                phase = "recovery"
                with self._lock_factory(existing_context, True):
                    recovery = _warning_sequence(
                        self._recoverer(existing_context)
                    )
                    self._project_factory(existing_context.root)
                phase = "init"
            created = Path(self._initializer(out, model_id)).absolute()
            created_context = RecoveryProjectContext(created)
            phase = "recovery"
            with self._lock_factory(created_context, True):
                post_init_recovery = _warning_sequence(
                    self._recoverer(created_context)
                )
                self._project_factory(created_context.root)
            recovery = (*recovery, *post_init_recovery)
            phase = "init"
            payload = yaml.safe_load((created / "economy.yaml").read_text(encoding="utf-8"))
            actual_model_id = payload["model"]["id"]
            result = {
                "project": str(created),
                "model_id": str(actual_model_id),
                "config": str(created / "economy.yaml"),
                "datas": str(created / "Datas"),
                "tables": str(created / "Datas" / "__tables__.xlsx"),
                "readme": str(created / "README.md"),
                "run_script": str(created / "run.ps1"),
            }
            return CommandResponse(
                "model.init",
                True,
                "initialized",
                f"Initialized model project at {created}",
                details=_details_with_warnings({}, recovery),
                result=result,
            )
        except Exception as exc:
            error = _phase_error(exc, phase)
            return _error_response(
                "model.init",
                error,
                details=_details_with_warnings(error.details, recovery),
            )

    def status(
        self,
        project_root: str | os.PathLike[str] | None = None,
    ) -> CommandResponse:
        """Return a complete typed status, including on validation failure."""

        recovery: Sequence[Mapping[str, object]] = ()
        phase = "recovery"
        try:
            recovery_context = self._recovery_context(project_root)
            with self._lock_factory(recovery_context, True):
                recovery = _warning_sequence(
                    self._recoverer(recovery_context)
                )
            phase = "project"
            project = self._project_factory(recovery_context.root)
            phase = "recovery"
            with self._shared_snapshot_factory(project, recovery):
                phase = "status"
                registry = self._registry_factory(project)
                status = self._status_deriver(project, registry.latest_smoke)
                phase = "recovery"
                status = _merge_status_warnings(status, recovery)
        except Exception as exc:
            error = _phase_error(exc, phase)
            return _status_error(error, _failed_status(error, warnings=recovery))

        if status.state == "failed":
            return CommandResponse(
                "model.status",
                False,
                "model_invalid",
                "Model validation failed",
                result=status.to_payload(),
            )
        messages = {
            "incomplete": "Model is valid but incomplete",
            "runnable": "Model is runnable",
            "ready": "Model is ready",
        }
        return CommandResponse(
            "model.status",
            True,
            "status",
            messages[status.state],
            result=status.to_payload(),
        )

    def apply(
        self,
        change: ModelChange | str,
        project_root: str | os.PathLike[str] | None = None,
        *,
        format_name: str = "yaml",
    ) -> CommandResponse:
        """Apply exactly one validated model change as a recoverable transaction."""

        recovered: Sequence[Mapping[str, object]] = ()
        phase = "recovery"
        try:
            recovery_context = self._recovery_context(project_root)
            with self._lock_factory(recovery_context, True):
                recovered = _warning_sequence(
                    self._recoverer(recovery_context)
                )
                phase = "project"
                project = self._project_factory(recovery_context.root)
                phase = "apply"
                if isinstance(change, str):
                    try:
                        parsed = _parse_change_against_current(
                            project,
                            change,
                            format_name,
                        )
                    except Exception as exc:
                        error = _phase_error(exc, "mapping")
                        response = _error_response(
                            "model.apply",
                            error,
                            details=_details_with_warnings(error.details, recovered),
                        )
                        phase = "recovery"
                        return response
                elif isinstance(change, ModelChange):
                    parsed = change
                else:
                    error = AuthoringError(
                        "invalid_change",
                        "Apply requires one change document or validated ModelChange",
                        {"value_type": type(change).__name__},
                    )
                    response = _error_response(
                        "model.apply",
                        error,
                        details=_details_with_warnings(error.details, recovered),
                    )
                    phase = "recovery"
                    return response
                response = self._apply_locked(project, parsed, recovered)
                phase = "recovery"
                return response
        except Exception as exc:
            error = _phase_error(exc, phase)
            return _error_response(
                "model.apply",
                error,
                details=_details_with_warnings(error.details, recovered),
            )

    def simulate(
        self,
        scenario_id: str = "smoke",
        project_root: str | os.PathLike[str] | None = None,
    ) -> CommandResponse:
        """Run one manual/formal scenario from a source-consistent snapshot."""

        warnings: Sequence[Mapping[str, object]] = ()
        phase = "recovery"
        try:
            recovery_context = self._recovery_context(project_root)
            with self._lock_factory(recovery_context, True):
                warnings = _warning_sequence(
                    self._recoverer(recovery_context)
                )
            phase = "project"
            project = self._project_factory(recovery_context.root)
            phase = "recovery"
            with self._shared_snapshot_factory(project, warnings):
                response = self._simulate_shared(project, scenario_id, warnings)
                phase = "recovery"
                return response
        except Exception as exc:
            error = _phase_error(exc, phase)
            return _error_response(
                "model.simulate",
                error,
                details=_details_with_warnings(error.details, warnings),
            )

    def _discover(
        self,
        override: str | os.PathLike[str] | None,
    ) -> AuthoringProject:
        root = Path(override) if override is not None else self.project_root
        if root is None:
            root = Path.cwd()
        return self._project_factory(root)

    def _recovery_context(
        self,
        override: str | os.PathLike[str] | None,
    ) -> RecoveryProjectContext:
        root = Path(override) if override is not None else self.project_root
        if root is None:
            root = Path.cwd()
        return RecoveryProjectContext(root)

    def _apply_locked(
        self,
        project: AuthoringProject,
        change: ModelChange,
        recovered: Sequence[Mapping[str, object]],
    ) -> CommandResponse:
        registry = self._registry_factory(project)
        record_store = self._record_store_factory(project, self._clock)
        try:
            pre_digest = project.model_digest()
        except Exception as exc:
            error = _phase_error(exc, "source_digest")
            return _error_response(
                "model.apply",
                error,
                details=_details_with_warnings(error.details, recovered),
            )

        change_id = self._id_factory()
        if not isinstance(change_id, str) or _CHANGE_ID.fullmatch(change_id) is None:
            error = AuthoringError(
                "invalid_change_id",
                "The change id factory returned an invalid id",
                {"change_id": change_id},
            )
            return _error_response(
                "model.apply",
                error,
                details=_details_with_warnings(error.details, recovered),
            )

        transaction: Transaction | None = None
        commit_started = False
        affected_files: list[str] = []
        run_id: str | None = None
        change_destination: Path | None = None
        phase = "stale"
        try:
            if change.if_model_digest is not None and change.if_model_digest != pre_digest:
                raise AuthoringError(
                    "stale_model",
                    "The proposal targets an older model state",
                    {
                        "actual": pre_digest,
                        "change_id": change_id,
                        "expected": change.if_model_digest,
                    },
                )

            phase = "transaction"
            transaction = self._transaction_factory(project, change_id, pre_digest)
            phase = "mapping"
            candidate = self._source_stager(project, transaction.root)
            source_files = list(self._candidate_mapper(candidate, change))
            affected_files = _ordered_files((*source_files, "luban_exports"))
            phase = "export"
            self._candidate_exporter(candidate, candidate.exports)

            phase = "load"
            raw = self._loader(candidate.config, candidate.exports)
            phase = "lint"
            self._linter(raw)
            phase = "build"
            model = self._builder(raw)
            candidate_project = self._project_factory(candidate.root)
            phase = "status"
            status = self._status_deriver(candidate_project, registry.latest_smoke)
            status = _merge_status_warnings(status, recovered)
            if status.state == "failed":
                raise AuthoringError(
                    "model_invalid",
                    "The candidate model is invalid; no model files changed",
                    {"status": status.to_payload()},
                    {"status": status.to_payload()},
                )
            post_digest = candidate_project.model_digest()
            if status.model_digest != post_digest:
                raise AuthoringError(
                    "model_invalid",
                    "Candidate status digest does not match its source snapshot",
                    {
                        "actual": status.model_digest,
                        "expected": post_digest,
                        "phase": "status",
                    },
                )

            smoke = {"status": "not_run", "run_id": None, "findings": []}
            run_destination: Path | None = None
            if status.smoke_eligible:
                phase = "reservation"
                run_destination = _select_available_run_dir(
                    registry,
                    "smoke",
                    kind="smoke",
                    change_id=change_id,
                )
                run_id = run_destination.name
                phase = "smoke"
                probe = self._probe_runner(model, "smoke", transaction.staged_run_dir)
                phase = "artifact"
                self._stage_smoke_record(
                    transaction,
                    run_destination,
                    change_id,
                    post_digest,
                )
                status = replace(status, latest_smoke_run_id=run_id)
                smoke = {
                    "status": "success",
                    "run_id": run_id,
                    "findings": [finding.to_payload() for finding in probe.findings],
                }

            phase = "audit"
            change_destination = record_store.stage_success(
                transaction.staged_change_path,
                change_id=change_id,
                change=change,
                pre_digest=pre_digest,
                post_digest=post_digest,
                affected_files=affected_files,
                status=status,
                warnings=recovered,
                run_id=run_id,
            )
            phase = "commit"
            transaction.prepare(
                targets=affected_files,
                run_destination=run_destination,
                change_destination=change_destination,
            )
            commit_started = True
            commit_warnings = transaction.commit()
            all_warnings = (*recovered, *commit_warnings)
            if commit_warnings:
                status = _merge_status_warnings(status, commit_warnings)

            if run_id is not None:
                try:
                    registry.prune_smoke(keep=20)
                except Exception:
                    prune_warning = {
                        "code": "smoke_prune_failed",
                        "message": "Old smoke runs could not be pruned.",
                    }
                    all_warnings = (*all_warnings, prune_warning)
                    status = _merge_status_warnings(status, (prune_warning,))

            result = {
                "change_id": change_id,
                "entity": change.entity,
                "id": change.id,
                "changed_files": affected_files,
                "status": status.to_payload(),
                "smoke": smoke,
            }
            return CommandResponse(
                "model.apply",
                True,
                "applied",
                f"Applied {change.entity}:{change.id}; model is {status.state}",
                details={"warnings": list(all_warnings)} if all_warnings else {},
                result=result,
            )
        except Exception as exc:
            error = _phase_error(exc, phase)
            if commit_started and error.code == "commit_in_doubt":
                return self._commit_in_doubt_response(
                    project,
                    error=error,
                    change_id=change_id,
                    change=change,
                    affected_files=affected_files,
                    change_destination=change_destination,
                    warnings=recovered,
                    run_id=run_id,
                )
            if transaction is not None and not commit_started:
                try:
                    transaction.abort()
                except Exception as abort_error:
                    error = _phase_error(abort_error, "recovery")
            return self._failed_apply_response(
                record_store,
                change_id=change_id,
                change=change,
                pre_digest=pre_digest,
                affected_files=affected_files,
                error=error,
                warnings=recovered,
                run_id=run_id,
            )

    def _commit_in_doubt_response(
        self,
        project: AuthoringProject,
        *,
        error: AuthoringError,
        change_id: str,
        change: ModelChange,
        affected_files: Sequence[str],
        change_destination: Path | None,
        warnings: Sequence[Mapping[str, object]],
        run_id: str | None,
    ) -> CommandResponse:
        recovery_warnings: Sequence[Mapping[str, object]] = ()
        recovery_error: AuthoringError | None = None
        try:
            recovery_context = RecoveryProjectContext(project.root)
            recovery_warnings = _warning_sequence(
                self._recoverer(recovery_context)
            )
        except Exception as exc:
            recovery_error = _phase_error(exc, "recovery")

        success_audit_present = bool(
            change_destination is not None
            and change_destination.is_file()
        )
        details = dict(error.details)
        details.update(
            {
                "change_id": change_id,
                "formal_state": "committed_or_recoverable",
                "recovery_attempted": True,
                "success_audit_present": success_audit_present,
            }
        )
        if change_destination is not None:
            details["success_audit_path"] = str(change_destination)
        if recovery_error is not None:
            details["recovery_error"] = {
                "code": recovery_error.code,
                "message": recovery_error.message,
                "details": dict(recovery_error.details),
            }
        all_warnings = (*warnings, *recovery_warnings)
        result = {
            "change_id": change_id,
            "entity": change.entity,
            "id": change.id,
            "changed_files": list(affected_files),
            "run_id": run_id,
        }
        return _error_response(
            "model.apply",
            error,
            result=result,
            details=_details_with_warnings(details, all_warnings),
        )

    def _stage_smoke_record(
        self,
        transaction: Transaction,
        destination: Path,
        change_id: str,
        model_digest: str,
    ) -> None:
        staged = transaction.staged_run_dir
        probe_output = staged / "run"
        output = staged / "output"
        report = staged / "report"
        if not probe_output.is_dir() or not report.is_dir():
            raise AuthoringError(
                "smoke_failed",
                "The smoke probe did not produce complete artifacts",
                {"phase": "artifact", "path": str(staged)},
            )
        os.replace(probe_output, output)
        manifest_path = output / "run_manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(manifest, dict):
                raise TypeError("manifest is not an object")
            manifest["model_digest"] = model_digest
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            self._report_writer(output, report)
            status_payload = {
                "run_id": destination.name,
                "status": "success",
                "scenario_id": "smoke",
                "message": "Probe complete",
                "output_dir": str(destination / "output"),
                "report_dir": str(destination / "report"),
                "report_index": str(destination / "report" / "index.html"),
                "version": 1,
                "kind": "smoke",
                "change_id": change_id,
                "model_digest": model_digest,
            }
            (staged / "run_status.json").write_text(
                json.dumps(
                    status_payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
        except AuthoringError:
            raise
        except Exception as exc:
            raise AuthoringError(
                "smoke_failed",
                "The smoke probe artifacts could not be finalized",
                {
                    "error_type": type(exc).__name__,
                    "phase": "artifact",
                    "path": str(staged),
                },
            ) from None

    def _failed_apply_response(
        self,
        store: ChangeRecordStore,
        *,
        change_id: str,
        change: ModelChange,
        pre_digest: str,
        affected_files: Sequence[str],
        error: AuthoringError,
        warnings: Sequence[Mapping[str, object]],
        run_id: str | None,
    ) -> CommandResponse:
        try:
            store.write_failure(
                change_id=change_id,
                change=change,
                pre_digest=pre_digest,
                affected_files=affected_files,
                error=error,
                warnings=warnings,
                run_id=run_id,
            )
        except Exception as audit_exc:
            audit = _phase_error(audit_exc, "audit")
            details = dict(audit.details)
            details["original_code"] = error.code
            path = details.get("path")
            if isinstance(path, str):
                details["unwritten_audit_path"] = path
            audit = AuthoringError(
                "audit_failed",
                "The failed change was rolled back but its audit could not be written",
                details,
            )
            return _error_response(
                "model.apply",
                audit,
                details=_details_with_warnings(audit.details, warnings),
            )
        return _error_response(
            "model.apply",
            error,
            details=_details_with_warnings(error.details, warnings),
        )

    def _simulate_shared(
        self,
        project: AuthoringProject,
        scenario_id: str,
        recovered: Sequence[Mapping[str, object]],
    ) -> CommandResponse:
        registry = self._registry_factory(project)
        record: RunRecord | None = None
        reserved_run_dir: Path | None = None
        phase = "simulate"
        try:
            if not isinstance(scenario_id, str) or not scenario_id:
                raise AuthoringError(
                    "unknown_scenario",
                    "Scenario id must be a non-empty string",
                    {"scenario_id": scenario_id},
                )
            with self._ephemeral_exporter(project) as exported:
                digest = exported.source_digest
                raw = self._loader(exported.candidate_config, exported.export_root)
                self._linter(raw)
                model = self._builder(raw)
                scenarios = getattr(model, "scenarios", {})
                if scenario_id not in scenarios:
                    raise AuthoringError(
                        "unknown_scenario",
                        f"Unknown scenario: {scenario_id}",
                        {
                            "available_scenarios": sorted(scenarios),
                            "scenario_id": scenario_id,
                        },
                    )
                phase = "reservation"
                run_dir = _reserve_manual_run_dir(
                    registry,
                    scenario_id,
                )
                reserved_run_dir = run_dir
                paths = _run_paths(run_dir)
                phase = "run_status"
                record = registry.write_status(
                    run_dir,
                    status="running",
                    scenario_id=scenario_id,
                    message="Running simulation",
                    kind="formal",
                    change_id=None,
                    model_digest=digest,
                    **paths,
                )
                phase = "simulate"
                result = self._simulator_factory(model).run_scenario(scenario_id)
                phase = "simulation_artifact"
                self._output_writer(
                    result,
                    paths["output_dir"],
                    model,
                    model_digest=digest,
                )
                self._report_writer(paths["output_dir"], paths["report_dir"])
                phase = "run_status"
                record = registry.write_status(
                    run_dir,
                    status="success",
                    scenario_id=scenario_id,
                    message="Run complete",
                    kind="formal",
                    change_id=None,
                    model_digest=digest,
                    **paths,
                )
        except Exception as exc:
            error = _phase_error(exc, phase)
            if record is None and reserved_run_dir is not None:
                _remove_empty_reservation(reserved_run_dir)
            if record is not None:
                try:
                    record = registry.write_status(
                        record.run_dir,
                        status="failed",
                        scenario_id=record.scenario_id,
                        message=error.message,
                        kind="formal",
                        change_id=None,
                        model_digest=record.model_digest,
                        output_dir=record.output_dir,
                        report_dir=record.report_dir,
                        report_index=record.report_index,
                    )
                except Exception as status_exc:
                    error = _phase_error(status_exc, "run_status")
            return _error_response(
                "model.simulate",
                error,
                result=_run_result(record) if record is not None else {},
                details=_details_with_warnings(error.details, recovered),
            )

        assert record is not None
        return CommandResponse(
            "model.simulate",
            True,
            "simulated",
            f"Simulation complete: {scenario_id}",
            details={"warnings": list(recovered)} if recovered else {},
            result=_run_result(record),
        )


def _parse_change_against_current(
    project: AuthoringProject,
    text: str,
    format_name: str,
) -> ModelChange:
    """Strictly parse a create or merge-patch against the current entity."""

    try:
        return parse_change_text(text, format_name)
    except AuthoringError as initial:
        entity = initial.details.get("entity")
        entity_id = initial.details.get("id")
        if not isinstance(entity, str) or not isinstance(entity_id, str):
            raise
        try:
            schema = get_entity_schema(entity)
        except AuthoringError:
            raise initial from None
        if schema.storage_kind == "yaml":
            current = read_yaml_entity(project.config, entity, entity_id)
        else:
            inspected = inspect_table(project.datas / schema.storage_name)
            selected = [
                record for record in inspected.records if record.entity_id == entity_id
            ]
            if len(selected) > 1:
                raise AuthoringError(
                    "model_invalid",
                    "The current entity id is duplicated",
                    {"entity": entity, "id": entity_id},
                )
            current = dict(selected[0].fields) if selected else None
        if current is None:
            raise initial from None
        return parse_change_text(text, format_name, current=current)


def _should_recover_existing_init(path: Path) -> bool:
    """Avoid polluting an allowed empty target while detecting recovery state."""

    return (path / ".igess" / "transactions").exists() or any(
        (path / name).exists()
        for name in ("economy.yaml", "Datas", "luban_exports")
    )


def _is_path_indirection(identity: os.stat_result) -> bool:
    attributes = getattr(identity, "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(identity.st_mode) or bool(attributes & reparse)


def _reserve_manual_run_dir(registry: RunRegistry, scenario_id: str) -> Path:
    runs_root = Path(registry.runs_root)
    try:
        runs_root.mkdir(parents=True, exist_ok=True)
        root_identity = runs_root.lstat()
        resolved_root = runs_root.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as error:
        raise AuthoringError(
            "run_reservation_failed",
            "The run registry could not be prepared safely",
            {"error_type": type(error).__name__, "path": str(runs_root)},
        ) from None
    if _is_path_indirection(root_identity) or not stat.S_ISDIR(root_identity.st_mode):
        raise AuthoringError(
            "run_reservation_failed",
            "The run registry must be a real directory",
            {"path": str(runs_root), "reason": "indirection_or_wrong_type"},
        )

    for _attempt in range(_RUN_ID_ATTEMPTS):
        candidate = Path(registry.new_run_dir(scenario_id, kind="formal"))
        try:
            if candidate.parent.resolve(strict=True) != resolved_root:
                raise AuthoringError(
                    "run_reservation_failed",
                    "The run id factory returned a path outside the registry",
                    {"path": str(candidate)},
                )
            candidate.mkdir(exist_ok=False)
            identity = candidate.lstat()
        except FileExistsError:
            continue
        except AuthoringError:
            raise
        except (OSError, RuntimeError, ValueError) as error:
            raise AuthoringError(
                "run_reservation_failed",
                "A run directory could not be reserved",
                {"error_type": type(error).__name__, "path": str(candidate)},
            ) from None
        if _is_path_indirection(identity) or not stat.S_ISDIR(identity.st_mode):
            _remove_empty_reservation(candidate)
            raise AuthoringError(
                "run_reservation_failed",
                "The reserved run path is not a real directory",
                {"path": str(candidate)},
            )
        return candidate
    raise AuthoringError(
        "run_id_collision",
        "Could not reserve a unique run id after repeated collisions",
        {"attempts": _RUN_ID_ATTEMPTS, "scenario_id": scenario_id},
    )


def _select_available_run_dir(
    registry: RunRegistry,
    scenario_id: str,
    *,
    kind: str,
    change_id: str,
) -> Path:
    runs_root = Path(registry.runs_root)
    try:
        runs_root.mkdir(parents=True, exist_ok=True)
        resolved_root = runs_root.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as error:
        raise AuthoringError(
            "run_reservation_failed",
            "The smoke run registry could not be prepared",
            {"error_type": type(error).__name__, "path": str(runs_root)},
        ) from None
    for _attempt in range(_RUN_ID_ATTEMPTS):
        candidate = Path(
            registry.new_run_dir(
                scenario_id,
                kind=kind,
                change_id=change_id,
            )
        )
        try:
            if candidate.parent.resolve(strict=True) != resolved_root:
                raise AuthoringError(
                    "run_reservation_failed",
                    "The smoke run id is outside the registry",
                    {"path": str(candidate)},
                )
        except (OSError, RuntimeError, ValueError) as error:
            raise AuthoringError(
                "run_reservation_failed",
                "The smoke run id could not be inspected",
                {"error_type": type(error).__name__, "path": str(candidate)},
            ) from None
        if not os.path.lexists(candidate):
            return candidate
    raise AuthoringError(
        "run_id_collision",
        "Could not select a unique automatic smoke run id",
        {
            "attempts": _RUN_ID_ATTEMPTS,
            "change_id": change_id,
            "scenario_id": scenario_id,
        },
    )


def _remove_empty_reservation(path: Path) -> None:
    try:
        path.rmdir()
    except OSError:
        pass


def _details_with_warnings(
    details: Mapping[str, object],
    warnings: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Append recovery warnings without discarding structured error context."""

    merged = dict(details)
    combined: list[dict[str, object]] = []
    existing = merged.pop("warnings", None)
    if isinstance(existing, Sequence) and not isinstance(
        existing,
        (str, bytes, bytearray),
    ):
        combined.extend(dict(item) for item in existing if isinstance(item, Mapping))
    elif existing is not None:
        merged["original_warnings"] = existing
    combined.extend(dict(item) for item in warnings)
    if combined:
        merged["warnings"] = combined
    return merged


def _run_paths(run_dir: Path) -> dict[str, Path]:
    return {
        "output_dir": run_dir / "output",
        "report_dir": run_dir / "report",
        "report_index": run_dir / "report" / "index.html",
    }


def _run_result(record: RunRecord) -> dict[str, object]:
    return {
        "run_id": record.run_id,
        "kind": record.kind,
        "scenario_id": record.scenario_id,
        "status": record.status,
        "output_dir": str(record.output_dir),
        "report_index": str(record.report_index),
        "change_id": record.change_id,
    }


def _warning_sequence(value: object) -> tuple[Mapping[str, object], ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TypeError("recovery warnings must be a sequence")
    warnings: list[Mapping[str, object]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise TypeError("recovery warnings must be mappings")
        warnings.append(dict(item))
    return tuple(warnings)


def _warning_finding(value: Mapping[str, object]) -> EligibilityFinding:
    code = value.get("code")
    message = value.get("message")
    if not isinstance(code, str) or not code or not isinstance(message, str) or not message:
        raise TypeError("warning must contain code and message strings")
    entity = value.get("entity")
    entity_id = value.get("id", value.get("change_id"))
    return EligibilityFinding(
        code,
        message,
        entity if isinstance(entity, str) and entity else None,
        entity_id if isinstance(entity_id, str) and entity_id else None,
    )


def _merge_status_warnings(
    status: ModelStatus,
    warnings: Sequence[Mapping[str, object]],
) -> ModelStatus:
    if not warnings:
        return status
    additions = tuple(_warning_finding(item) for item in warnings)
    return replace(status, warnings=(*status.warnings, *additions))


def _failed_status(
    error: AuthoringError,
    *,
    warnings: Sequence[Mapping[str, object]] = (),
) -> ModelStatus:
    return ModelStatus(
        model_digest="unavailable",
        structural_valid=False,
        smoke_eligible=False,
        state="failed",
        entity_counts={name: 0 for name in ENTITY_SCHEMAS},
        missing_requirements=(EligibilityFinding(error.code, error.message),),
        warnings=tuple(_warning_finding(item) for item in warnings),
        available_scenarios=(),
        latest_smoke_run_id=None,
    )


def _status_error(error: AuthoringError, status: ModelStatus) -> CommandResponse:
    return CommandResponse(
        "model.status",
        False,
        error.code,
        error.message,
        details=error.details,
        result=status.to_payload(),
    )


def _error_response(
    command: str,
    error: AuthoringError,
    *,
    result: Mapping[str, object] | None = None,
    details: Mapping[str, object] | None = None,
) -> CommandResponse:
    return CommandResponse(
        command,
        False,
        error.code,
        error.message,
        details=error.details if details is None else details,
        result=error.result if result is None else result,
    )


def _ordered_files(values: Sequence[str]) -> list[str]:
    return sorted(dict.fromkeys(values))


def _phase_error(exc: Exception, phase: str) -> AuthoringError:
    if isinstance(exc, AuthoringError):
        return exc
    codes = {
        "init": "init_failed",
        "project": "project_invalid",
        "recovery": "recovery_failed",
        "source_digest": "model_invalid",
        "stale": "stale_model",
        "transaction": "commit_failed",
        "load": "model_invalid",
        "status": "model_invalid",
        "mapping": "invalid_change",
        "export": "export_failed",
        "lint": "model_invalid",
        "build": "model_invalid",
        "smoke": "smoke_failed",
        "artifact": "smoke_failed",
        "audit": "audit_failed",
        "commit": "commit_failed",
        "run_status": "run_status_failed",
        "reservation": "run_reservation_failed",
        "simulate": "simulation_failed",
        "simulation_artifact": "simulation_failed",
        "apply": "commit_failed",
    }
    code = codes.get(phase, "authoring_failed")
    return AuthoringError(
        code,
        f"Authoring operation failed during {phase}",
        {"error_type": type(exc).__name__, "phase": phase},
    )
