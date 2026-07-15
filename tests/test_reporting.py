import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from igess.builder import ModelBuilder
from igess.loader import ConfigLoader
from igess.outputs import OutputWriter
from igess.reporting.loader import ReportLoadError, load_report_data
from igess.reporting.static import generate_static_report
from igess.simulator import Simulator


CONFIG = "examples/shelldiver_v0/economy.yaml"
TABLES = "examples/shelldiver_v0/luban_exports"
NODE = shutil.which("node")


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
    assert 'data-overview-kpis' in html
    assert 'class="kpi-grid"' in html
    assert "fisherman" in html
    assert (report_dir / "report_data.json").exists()
    assert (report_dir / "assets" / "echarts.min.js").exists()
    assert (report_dir / "assets" / "report.css").exists()
    assert (report_dir / "assets" / "report.js").exists()
    assert 'src="assets/echarts.min.js"' in html
    assert 'src="assets/report.js"' in html
    assert 'data-report-src="report_data.json"' in html
    assert '<script id="igess-report-data" type="application/json">' in html


def test_generate_static_report_writes_chart_rendering_asset(tmp_path):
    run_dir = _write_sample_run(tmp_path)
    report_dir = tmp_path / "report"

    generate_static_report(run_dir, report_dir)

    script = (report_dir / "assets" / "report.js").read_text(encoding="utf-8")
    assert "echarts.init" in script
    assert "renderResourceChart" in script
    assert "renderCpsChart" in script
    assert "renderEventChart" in script
    assert "renderPaybackChart" in script
    assert "renderOverview" in script
    assert "report.overview" in script
    assert "display_value" in script
    assert "exact_value" in script
    assert "exact-value" in script
    assert "escapeHtml" in script


@pytest.mark.skipif(NODE is None, reason="Node.js is required to execute the report renderer")
def test_report_overview_renders_accessible_escaped_kpis():
    point = {
        "exact_value": '\"><script>alert("exact")</script>',
        "display_value": "<display>",
        "chart_value": None,
    }
    report = {
        "scenario": {"id": "<scenario>"},
        "overview": {
            "duration_seconds": point,
            "profiles": ["<profile>"],
            "purchase_count": point,
            "first_key_unlock": {
                "time_seconds": point,
                "profile_id": "<profile>",
                "kind": "unlock_activity",
                "item_id": "</p><script>alert('item')</script>",
            },
            "prestige_reset_count": point,
            "worst_payback": {
                "payback_seconds": point,
                "profile_id": "<profile>",
                "kind": "upgrade",
                "item_id": "<upgrade>",
            },
            "never_purchased_count": point,
            "never_unlocked_count": point,
            "warning_category_count": point,
            "final_resources": {"<profile>": {"<resource>": point}},
        },
    }
    script_path = Path("src/igess/reporting/assets/report.js").resolve()
    harness = r"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
const context = { console };
vm.createContext(context);
vm.runInContext(source, context);
const scenario = { textContent: '' };
const container = { innerHTML: '' };
context.document = {
  querySelector(selector) {
    if (selector === '[data-scenario]') return scenario;
    if (selector === '[data-overview-kpis]') return container;
    return null;
  },
};
context.renderOverview(JSON.parse(process.argv[2]));
process.stdout.write(JSON.stringify({ scenario: scenario.textContent, html: container.innerHTML }));
"""

    completed = subprocess.run(
        [NODE, "-e", harness, str(script_path), json.dumps(report)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    rendered = json.loads(completed.stdout)
    html = rendered["html"]
    assert rendered["scenario"] == "<scenario>"
    assert html.count('role="listitem"') == 9
    assert '<details class="exact-values">' in html
    assert 'data-exact-value=' in html
    assert "&lt;profile&gt;" in html
    assert "&lt;resource&gt;" in html
    assert "&lt;display&gt;" in html
    assert "<script>" not in html


def test_generate_static_report_embeds_parseable_json_payload(tmp_path):
    run_dir = _write_sample_run(tmp_path)
    report_dir = tmp_path / "report"

    generated = generate_static_report(run_dir, report_dir)

    html = generated.read_text(encoding="utf-8")
    marker = '<script id="igess-report-data" type="application/json">'
    start = html.index(marker) + len(marker)
    end = html.index("</script>", start)
    inline_payload = json.loads(html[start:end])
    file_payload = json.loads((report_dir / "report_data.json").read_text(encoding="utf-8"))
    assert inline_payload == file_payload
    assert inline_payload["schema_version"] == 2
    assert inline_payload["series"]["resources"]
    assert set(inline_payload["overview"]["duration_seconds"]) == {
        "exact_value",
        "display_value",
        "chart_value",
    }
    assert "&quot;" not in html[start:end]


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
