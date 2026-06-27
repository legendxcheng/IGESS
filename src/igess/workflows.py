from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .advice import run_advise
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
    def __init__(self, project_root: str | Path, runs_root: str | Path | None = None):
        self.project_root = Path(project_root)
        self.registry = RunRegistry(runs_root or self.project_root / ".igess" / "runs")

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

    def run_advice(self, config: str | Path, tables: str | Path, scenario_id: str) -> RunRecord:
        run_dir = self.registry.new_run_dir(f"advice_{scenario_id}")
        advice_dir = run_dir / "advice"
        output_dir = advice_dir / "run"
        report_dir = advice_dir / "report"
        report_index = report_dir / "index.html"
        self.registry.write_status(
            run_dir,
            status="running",
            scenario_id=scenario_id,
            message="Running Agent Analyst",
            output_dir=output_dir,
            report_dir=report_dir,
            report_index=report_index,
        )
        try:
            advice = run_advise(
                self._path(config),
                self._path(tables),
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

    def latest_advice(self) -> dict | None:
        candidates = sorted(self.registry.runs_root.glob("*/advice/advice.json"))
        if not candidates:
            return None
        import json

        return json.loads(candidates[-1].read_text(encoding="utf-8"))

    def list_runs(self) -> list[RunRecord]:
        return self.registry.list_runs()

    def _path(self, value: str | Path) -> Path:
        path = Path(value)
        if path.is_absolute():
            return path
        return self.project_root / path
