import json

from igess.run_registry import RunRegistry
from igess.workflows import WorkflowService


CONFIG = "examples/shelldiver_v0/economy.yaml"
TABLES = "examples/shelldiver_v0/luban_exports"


def test_workflow_service_lints_runs_reports_and_lists_history(tmp_path):
    service = WorkflowService(project_root=".", runs_root=tmp_path / "runs")

    lint = service.lint(CONFIG, TABLES)
    record = service.run_scenario(CONFIG, TABLES, "day_1_progression")
    history = RunRegistry(tmp_path / "runs").list_runs()

    assert lint.ok
    assert record.status == "success"
    assert record.scenario_id == "day_1_progression"
    assert record.report_index.exists()
    assert record.output_dir.joinpath("timeline.json").exists()
    status = json.loads(record.status_path.read_text(encoding="utf-8"))
    assert status["status"] == "success"
    assert status["scenario_id"] == "day_1_progression"
    assert status["report_index"] == str(record.report_index)
    assert [item.run_id for item in history] == [record.run_id]


def test_workflow_service_records_failed_run_status(tmp_path):
    service = WorkflowService(project_root=".", runs_root=tmp_path / "runs")

    record = service.run_scenario(CONFIG, TABLES, "missing_scenario")

    assert record.status == "failed"
    assert "missing_scenario" in record.message
    status = json.loads(record.status_path.read_text(encoding="utf-8"))
    assert status["status"] == "failed"
    assert "missing_scenario" in status["message"]
