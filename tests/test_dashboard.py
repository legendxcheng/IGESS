import json
import subprocess
import sys
from http import HTTPStatus

from igess import dashboard
from igess.dashboard import render_dashboard_home
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


def test_render_dashboard_home_lists_actions_and_history(tmp_path):
    service = WorkflowService(project_root=".", runs_root=tmp_path / "runs")
    record = service.run_scenario(CONFIG, TABLES, "day_1_progression")

    html = render_dashboard_home(service, CONFIG, TABLES)

    assert "IGESS Dashboard" in html
    assert "day_1_progression" in html
    assert record.run_id in html
    assert "Run Scenario" in html
    assert "Diagnostics" in html
    assert "Agent Analyst" in html
    assert "Latest advice" in html


def test_send_report_file_response_blocks_path_traversal(tmp_path):
    service = WorkflowService(project_root=".", runs_root=tmp_path / "runs")
    record = service.run_scenario(CONFIG, TABLES, "day_1_progression")
    secret = tmp_path / "runs" / "secret.txt"
    secret.write_text("outside-report", encoding="utf-8")

    status, content_type, body = dashboard.send_report_file_response(
        service,
        f"{record.run_id}/../secret.txt",
    )

    assert status == HTTPStatus.NOT_FOUND
    assert content_type == "text/plain; charset=utf-8"
    assert body == b"Not found"


def test_dashboard_serves_shared_report_assets(tmp_path):
    service = WorkflowService(project_root=".", runs_root=tmp_path / "runs")
    record = service.run_scenario(CONFIG, TABLES, "day_1_progression")

    for relative in [
        f"{record.run_id}/report_data.json",
        f"{record.run_id}/assets/report.js",
        f"{record.run_id}/assets/echarts.min.js",
    ]:
        status, content_type, body = dashboard.send_report_file_response(service, relative)
        assert status == HTTPStatus.OK
        assert content_type
        assert body


def test_cli_dashboard_help_exposes_local_server_options():
    result = subprocess.run(
        [sys.executable, "-m", "igess.cli", "dashboard", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "--project" in result.stdout
    assert "--host" in result.stdout
    assert "--port" in result.stdout
