from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from igess.advice import run_advise
from igess.cli import main
from igess.development_diagnostics import DevelopmentDiagnostics
from igess.engines import EngineRegistry
from igess.run_registry import RunRegistry
from igess.scan import run_scan
from igess.workflows import WorkflowService


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "examples/shelldiver_v0/economy.yaml"
TABLES = ROOT / "examples/shelldiver_v0/luban_exports"


@pytest.mark.parametrize("engine_id", ["fish", "unsupported"])
@pytest.mark.parametrize("command", ["run", "scan", "advise"])
def test_legacy_commands_reject_fish_before_writing_artifacts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], command: str, engine_id: str,
) -> None:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    config["model"]["engine_id"] = engine_id
    path = tmp_path / "economy.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    output = tmp_path / "output"

    if command == "run":
        assert main([
            "run", "--config", str(path), "--tables", str(TABLES),
            "--scenario", "analytic_smoke", "--out", str(output),
        ]) == 1
        message = capsys.readouterr().err
        assert "only supports" in message
        assert "model simulate" in message
    else:
        with pytest.raises(ValueError, match="only supports.*generic"):
            if command == "scan":
                run_scan(path, TABLES, "analytic_smoke", "generators.fisherman.cost_growth=1.14..1.15:0.01", output)
            else:
                run_advise(path, TABLES, "analytic_smoke", output)
    assert not output.exists()


def test_workflow_report_failure_keeps_outputs_and_records_diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken_report(*_args: object) -> None:
        raise RuntimeError("report render failed")

    monkeypatch.setattr("igess.workflows.generate_static_report", broken_report)
    workflow = WorkflowService(tmp_path, authoring=False)
    record = workflow.run_scenario(CONFIG, TABLES, "analytic_smoke")

    assert record.status == "failed"
    assert (record.output_dir / "timeline.json").is_file()
    assert (record.output_dir / "run_manifest.json").is_file()
    diagnostic = tmp_path / ".igess/diagnostics" / f"{record.run_id}.json"
    assert str(diagnostic) in record.message
    payload = json.loads(diagnostic.read_text(encoding="utf-8"))
    assert payload["phase"] == "report"
    assert payload["context"]["run_id"] == record.run_id
    assert "report render failed" in payload["primary_error"]["traceback"]
    assert not list(record.report_dir.rglob("*diagnostic*"))


def test_workflow_preserves_engine_failure_when_status_write_also_fails(
    tmp_path: Path,
) -> None:
    class BrokenSimulator:
        def run_scenario(self, _scenario: str) -> None:
            try:
                raise ValueError("invalid source value")
            except ValueError as error:
                raise RuntimeError("engine execution failed") from error

    class BrokenFinalStatus(RunRegistry):
        def write_status(self, *args, **kwargs):
            if kwargs["status"] != "running":
                raise OSError("status disk unavailable")
            return super().write_status(*args, **kwargs)

    workflow = WorkflowService(
        tmp_path, authoring=False,
        engine_registry=EngineRegistry.standard(simulator_factory=lambda _model: BrokenSimulator()),
    )
    workflow.registry = BrokenFinalStatus(tmp_path / "runs")
    record = workflow.run_scenario(CONFIG, TABLES, "analytic_smoke")

    assert record.status == "failed"
    assert "engine execution failed" in record.message
    assert "status could not be saved" in record.message
    payload = json.loads((tmp_path / ".igess/diagnostics" / f"{record.run_id}.json").read_text())
    assert payload["phase"] == "simulate"
    assert payload["primary_error"]["error_type"] == "RuntimeError"
    assert "invalid source value" in payload["primary_error"]["traceback"]
    assert "engine execution failed" in payload["primary_error"]["traceback"]
    assert payload["secondary_errors"][0]["stage"] == "run_status"
    assert payload["secondary_errors"][0]["message"] == "status disk unavailable"


def test_diagnostic_write_failure_does_not_replace_report_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken_report(*_args: object) -> None:
        raise RuntimeError("report render failed")

    def broken_diagnostics(*_args: object) -> None:
        raise OSError("diagnostic disk unavailable")

    monkeypatch.setattr("igess.workflows.generate_static_report", broken_report)
    monkeypatch.setattr(DevelopmentDiagnostics, "__call__", broken_diagnostics)
    record = WorkflowService(tmp_path, authoring=False).run_scenario(CONFIG, TABLES, "analytic_smoke")

    assert record.status == "failed"
    assert "report render failed" in record.message
    assert "Development diagnostic could not be saved" in record.message
    assert "diagnostic disk unavailable" not in record.message
    assert (record.output_dir / "timeline.json").is_file()
