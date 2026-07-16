from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .advice import run_advise
from .authoring.change_records import ChangeRecordStore
from .authoring.exports import ephemeral_export
from .authoring.project import AuthoringProject
from .authoring.response import CommandResponse
from .authoring.service import AuthoringService
from .builder import ModelBuilder
from .linter import ConfigLinter
from .loader import ConfigLoader
from .outputs import OutputWriter
from .reporting.static import generate_static_report
from .run_registry import RunRecord, RunRegistry
from .simulator import Simulator


@dataclass(frozen=True)
class WorkflowResult:
    ok: bool
    message: str


class WorkflowService:
    def __init__(
        self,
        project_root: str | Path,
        runs_root: str | Path | None = None,
        *,
        authoring: bool | None = None,
        authoring_project: AuthoringProject | None = None,
        authoring_service: AuthoringService | None = None,
        registry: RunRegistry | None = None,
        change_store: ChangeRecordStore | None = None,
    ):
        self.project_root = Path(project_root)
        self.authoring_project = self._discover_authoring_project(
            authoring,
            authoring_project,
        )
        self.is_authoring = self.authoring_project is not None
        self.authoring_service = (
            authoring_service
            if authoring_service is not None
            else AuthoringService(self.authoring_project.root)
            if self.authoring_project is not None
            else None
        )

        if registry is not None:
            self.registry = registry
        elif self.authoring_project is not None and runs_root is None:
            self.registry = RunRegistry(
                self.authoring_project.runs,
                read_roots=self.authoring_project.read_run_roots(),
            )
        else:
            self.registry = RunRegistry(runs_root or self.project_root / ".igess" / "runs")
        self.change_store = (
            change_store
            if change_store is not None
            else ChangeRecordStore(self.authoring_project.changes)
            if self.authoring_project is not None
            else None
        )

    def model_status(self) -> CommandResponse | None:
        """Return the canonical authoring status, when this is an authoring project."""

        if self.authoring_service is None:
            return None
        return self.authoring_service.status()

    def latest_change(self) -> dict[str, Any] | None:
        """Return the latest committed rule audit without scanning project files."""

        if self.change_store is None:
            return None
        return self.change_store.latest()

    def run_authoring_scenario(self, scenario_id: str) -> CommandResponse:
        """Run a manual scenario through authoring's source-consistent snapshot."""

        if self.authoring_service is None:
            raise ValueError("authoring scenario requires an authoring project")
        return self.authoring_service.simulate(scenario_id)

    def lint(self, config: str | Path, tables: str | Path) -> WorkflowResult:
        try:
            raw = ConfigLoader.load(self._path(config), self._path(tables))
            ConfigLinter.validate(raw)
            return WorkflowResult(True, "Config OK")
        except Exception as exc:  # noqa: BLE001 - service boundary returns messages.
            return WorkflowResult(False, str(exc))

    def run_scenario(self, config: str | Path, tables: str | Path, scenario_id: str) -> RunRecord:
        run_dir = self.registry.new_run_dir(scenario_id)
        output_dir = run_dir / "output"
        report_dir = run_dir / "report"
        report_index = report_dir / "index.html"
        self.registry.write_status(
            run_dir,
            status="running",
            scenario_id=scenario_id,
            message="Running simulation",
            output_dir=output_dir,
            report_dir=report_dir,
            report_index=report_index,
        )
        try:
            raw = ConfigLoader.load(self._path(config), self._path(tables))
            ConfigLinter.validate(raw)
            model = ModelBuilder.build(raw)
            result = Simulator(model).run_scenario(scenario_id)
            OutputWriter.write_all(result, output_dir, model)
            generate_static_report(output_dir, report_dir)
            return self.registry.write_status(
                run_dir,
                status="success",
                scenario_id=scenario_id,
                message="Run complete",
                output_dir=output_dir,
                report_dir=report_dir,
                report_index=report_index,
            )
        except Exception as exc:  # noqa: BLE001 - failure is persisted for dashboard history.
            return self.registry.write_status(
                run_dir,
                status="failed",
                scenario_id=scenario_id,
                message=str(exc),
                output_dir=output_dir,
                report_dir=report_dir,
                report_index=report_index,
            )

    def run_advice(
        self,
        config: str | Path | None,
        tables: str | Path | None,
        scenario_id: str,
    ) -> RunRecord:
        if self.authoring_project is not None and config is None and tables is None:
            with ephemeral_export(self.authoring_project) as exported:
                return self._run_advice(
                    exported.candidate_config,
                    exported.export_root,
                    scenario_id,
                    model_digest=exported.source_digest,
                )
        if config is None or tables is None:
            raise ValueError("legacy advice requires config and tables")
        return self._run_advice(
            self._path(config),
            self._path(tables),
            scenario_id,
            model_digest=None,
        )

    def _run_advice(
        self,
        config: Path,
        tables: Path,
        scenario_id: str,
        *,
        model_digest: str | None,
    ) -> RunRecord:
        run_dir = self.registry.new_run_dir(f"advice_{scenario_id}")
        advice_dir = run_dir / "advice"
        output_dir = advice_dir / "run"
        report_dir = advice_dir / "report"
        report_index = report_dir / "index.html"
        metadata = (
            {"kind": "advice", "model_digest": model_digest}
            if model_digest is not None
            else {}
        )
        self.registry.write_status(
            run_dir,
            status="running",
            scenario_id=scenario_id,
            message="Running Agent Analyst",
            output_dir=output_dir,
            report_dir=report_dir,
            report_index=report_index,
            **metadata,
        )
        try:
            advice = run_advise(
                config,
                tables,
                scenario_id,
                advice_dir,
            )
            return self.registry.write_status(
                run_dir,
                status=advice["status"],
                scenario_id=scenario_id,
                message=advice["summary"],
                output_dir=output_dir,
                report_dir=report_dir,
                report_index=report_index,
                **metadata,
            )
        except Exception as exc:  # noqa: BLE001 - failure is persisted for dashboard history.
            return self.registry.write_status(
                run_dir,
                status="failed",
                scenario_id=scenario_id,
                message=str(exc),
                output_dir=output_dir,
                report_dir=report_dir,
                report_index=report_index,
                **metadata,
            )

    def latest_advice(self) -> dict | None:
        import json

        for record in reversed(self.registry.list_runs()):
            candidate = record.run_dir / "advice" / "advice.json"
            try:
                if candidate.is_file():
                    return json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
                continue
        return None

    def list_runs(self) -> list[RunRecord]:
        return self.registry.list_runs()

    def _path(self, value: str | Path) -> Path:
        path = Path(value)
        if path.is_absolute():
            return path
        return self.project_root / path

    def _discover_authoring_project(
        self,
        authoring: bool | None,
        supplied: AuthoringProject | None,
    ) -> AuthoringProject | None:
        if authoring is False:
            return None
        if supplied is not None:
            return supplied
        try:
            return AuthoringProject.discover(self.project_root)
        except Exception:  # noqa: BLE001 - absence means legacy dashboard mode.
            if authoring:
                raise
            return None
