import json
import subprocess
import sys

import pytest

from igess.builder import ModelBuilder
from igess.loader import ConfigLoader
from igess.outputs import OutputWriter
from igess.reporting.loader import ReportLoadError, load_report_data
from igess.reporting.static import generate_static_report
from igess.simulator import Simulator


CONFIG = "examples/shelldiver_v0/economy.yaml"
TABLES = "examples/shelldiver_v0/luban_exports"


def _write_sample_run(tmp_path):
    model = ModelBuilder.build(ConfigLoader.load(CONFIG, TABLES))
    result = Simulator(model).run_scenario("day_1_progression")
    run_dir = tmp_path / "run"
    OutputWriter.write_all(result, run_dir, model)
    return run_dir


def test_load_report_data_reads_run_artifacts(tmp_path):
    run_dir = _write_sample_run(tmp_path)

    data = load_report_data(run_dir)

    assert data.run_dir == run_dir
    assert data.manifest["schema_version"] == 1
    assert data.scenario_id == "day_1_progression"
    assert data.profiles == ["casual", "explorer", "optimizer"]
    assert data.timeline
    assert data.events
    assert data.analysis["payback_report"]
    assert any(row["item_id"] == "fisherman" for row in data.payback_rows)


def test_load_report_data_allows_missing_optional_payback(tmp_path):
    run_dir = _write_sample_run(tmp_path)
    (run_dir / "payback.csv").unlink()

    data = load_report_data(run_dir)

    assert data.payback_rows == []
    assert "payback.csv" in data.missing_artifacts


def test_load_report_data_reports_malformed_json(tmp_path):
    run_dir = _write_sample_run(tmp_path)
    (run_dir / "analysis.json").write_text("{not-json", encoding="utf-8")

    with pytest.raises(ReportLoadError) as excinfo:
        load_report_data(run_dir)

    assert "analysis.json" in str(excinfo.value)


def test_generate_static_report_writes_html_and_assets(tmp_path):
    run_dir = _write_sample_run(tmp_path)
    report_dir = tmp_path / "report"

    generated = generate_static_report(run_dir, report_dir, title="Day 1 Economy")

    assert generated == report_dir / "index.html"
    html = generated.read_text(encoding="utf-8")
    assert "Day 1 Economy" in html
    assert "Resource Curves" in html
    assert "Event Timeline" in html
    assert "Payback" in html
    assert "Analysis Warnings" in html
    assert "fisherman" in html
    assert (report_dir / "assets" / "report.css").exists()
    assert (report_dir / "assets" / "report.js").exists()


def test_cli_report_generates_static_report(tmp_path):
    run_dir = _write_sample_run(tmp_path)
    report_dir = tmp_path / "cli-report"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "igess.cli",
            "report",
            "--run",
            str(run_dir),
            "--out",
            str(report_dir),
            "--title",
            "CLI Report",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "Wrote static report" in result.stdout
    assert "CLI Report" in (report_dir / "index.html").read_text(encoding="utf-8")
