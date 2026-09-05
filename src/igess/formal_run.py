"""Execute a prepared, registered run without owning its input or response policy."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from .engines import DomainEngineAdapter, PreparedEngine
from .outputs import OutputWriter
from .reporting.static import generate_static_report
from .run_registry import RunRecord, RunRegistry


@dataclass
class RunFailure:
    stage: str
    error: Exception
    secondary_errors: list[tuple[str, Exception]] = field(default_factory=list)
    diagnostic: dict[str, str] = field(default_factory=dict)

    @property
    def status_error(self) -> Exception | None:
        return next((error for stage, error in self.secondary_errors if stage == "run_status"), None)

    def details(self) -> dict[str, Any]:
        result: dict[str, Any] = {"execution_stage": self.stage, **self.diagnostic}
        if self.secondary_errors:
            result["primary_error_type"] = type(self.error).__name__
            result["secondary_errors"] = [
                {"stage": stage, "error_type": type(error).__name__}
                for stage, error in self.secondary_errors
            ]
        return result

    def message(self, base: str) -> str:
        if self.stage == "report":
            base = "[report] " + base
        if "diagnostic_path" in self.diagnostic:
            base += f"\nDiagnostic: {self.diagnostic['diagnostic_path']}"
        if any(stage == "diagnostic" for stage, _ in self.secondary_errors):
            base += "\nDevelopment diagnostic could not be saved."
        return base


DiagnosticWriter = Callable[[RunFailure, Mapping[str, Any]], Mapping[str, str]]


def record_diagnostic(
    failure: RunFailure,
    context: Mapping[str, Any],
    writer: DiagnosticWriter | None,
) -> None:
    """A failed diagnostic must never replace the failure it was meant to explain."""
    if writer is None:
        return
    try:
        failure.diagnostic.update(writer(failure, context))
    except Exception as error:
        failure.secondary_errors.append(("diagnostic", error))


def legacy_failure_phase(stage: str) -> str:
    if stage in {"checkpoint", "artifacts", "report"}:
        return "simulation_artifact"
    if stage == "snapshot_cleanup":
        return "run_status"
    if stage == "prepare":
        return "simulate"
    return stage


@dataclass(frozen=True)
class PreparedRun:
    prepared: PreparedEngine
    adapter: DomainEngineAdapter
    record: RunRecord
    checkpoint_input: str | Path | None = None
    overrides: tuple[str, ...] = ()
    success_message: str = "Run complete"
    source_context: Mapping[str, Any] = field(default_factory=dict)

    def diagnostic_context(self) -> dict[str, Any]:
        model = self.prepared.model
        scenario = model.scenarios.get(self.record.scenario_id)
        return {
            **self.source_context,
            "run_id": self.record.run_id,
            "engine_id": self.prepared.engine_id,
            "scenario_id": self.record.scenario_id,
            "model_digest": self.prepared.model_digest,
            "profiles": list(scenario.profiles) if scenario is not None else [],
            "random_seed": model.config.random_seed,
            "checkpoint_input": str(self.checkpoint_input) if self.checkpoint_input is not None else None,
            "overrides": list(self.overrides),
            "manifest_metadata": dict(self.prepared.manifest_metadata),
            "output_dir": str(self.record.output_dir),
            "report_dir": str(self.record.report_dir),
            "simulated_time_seconds": None,
            "active_behavior": None,
        }


@dataclass(frozen=True)
class RunOutcome:
    record: RunRecord
    failure: RunFailure | None = None
    status_persisted: bool = True


class FormalRunExecutor:
    def __init__(
        self,
        registry: RunRegistry,
        *,
        output_writer: Callable[..., None] = OutputWriter.write_all,
        report_writer: Callable[..., Path] = generate_static_report,
        failure_message: Callable[[Exception, str], str] = lambda error, _stage: str(error),
        diagnostics: DiagnosticWriter | None = None,
    ) -> None:
        self._registry = registry
        self._output_writer = output_writer
        self._report_writer = report_writer
        self._failure_message = failure_message
        self._diagnostics = diagnostics

    def execute(self, run: PreparedRun) -> RunOutcome:
        stage = "simulate"
        try:
            execution = run.adapter.run_scenario(
                run.prepared,
                run.record.scenario_id,
                checkpoint_input=run.checkpoint_input,
            )
            stage = "checkpoint"
            checkpoint_name = "final_checkpoint.json"
            checkpoint = run.adapter.write_checkpoint(
                execution,
                run.record.output_dir / checkpoint_name,
                model_digest=run.prepared.model_digest,
            )
            stage = "artifacts"
            self._output_writer(
                execution.result,
                run.record.output_dir,
                run.prepared.model,
                overrides=list(run.overrides),
                model_digest=run.record.model_digest,
                manifest_metadata=run.prepared.manifest_metadata,
                extra_artifacts=(checkpoint_name,) if checkpoint else (),
                domain_model=run.prepared.domain_model,
            )
            stage = "report"
            self._report_writer(run.record.output_dir, run.record.report_dir)
            stage = "run_status"
            record = self._write_status(run.record, "success", run.success_message)
            return RunOutcome(record)
        except Exception as error:
            failure = RunFailure(stage, error)

        context: Mapping[str, Any] = {"run_id": run.record.run_id}
        if self._diagnostics is not None:
            try:
                context = run.diagnostic_context()
            except Exception as error:
                failure.secondary_errors.append(("diagnostic_context", error))
        record_diagnostic(failure, context, self._diagnostics)
        message = failure.message(self._failure_message(failure.error, stage))
        try:
            record = self._write_status(run.record, "failed", message)
        except Exception as error:
            failure.secondary_errors.append(("run_status", error))
            record_diagnostic(failure, context, self._diagnostics)
            # Do not return a stale success/running record as the outcome of a failure.
            record = replace(
                run.record,
                status="failed",
                message=failure.message(self._failure_message(failure.error, stage))
                + "\nFailed run status could not be saved.",
            )
            return RunOutcome(record, failure, status_persisted=False)
        return RunOutcome(record, failure)

    def _write_status(self, record: RunRecord, status: str, message: str) -> RunRecord:
        return self._registry.write_status(
            record.run_dir,
            status=status,
            scenario_id=record.scenario_id,
            message=message,
            output_dir=record.output_dir,
            report_dir=record.report_dir,
            report_index=record.report_index,
            kind=record.kind if record.version is not None else None,
            change_id=record.change_id,
            model_digest=record.model_digest,
            engine_id=record.engine_id,
        )
