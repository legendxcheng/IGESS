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

    generated = generate_static_report(run_dir, report_dir, title="首日经济报告")

    assert generated == report_dir / "index.html"
    html = generated.read_text(encoding="utf-8")
    assert "首日经济报告" in html
    assert "运行总览" in html
    assert "资源曲线" in html
    assert "摸鱼经济对称性总览" in html
    assert "fish-acquisition-rate-chart" in html
    assert "fish-cumulative-output-chart" in html
    assert "data-weekly-progression-charts" in html
    assert "data-daily-progression-charts" in html
    assert "事件时间线" in html
    assert "回本压力" in html
    assert "分析预警" in html
    assert "Resource Curves" not in html
    assert "Analysis Warnings" not in html
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
    assert "renderFishAcquisitionRateChart" in script
    assert "renderFishCumulativeOutputChart" in script
    assert "每秒获得的资源量与金钱量（5分钟窗口）" in script
    assert "resource_per_second" in script
    assert "trash_per_second" not in script
    assert "renderDailyProgressionCharts" in script
    assert "renderWeeklyProgressionCharts" in script
    assert "progressionCategoryColor" in script
    assert "report.overview" in script
    assert "display_value" in script
    assert "exact_value" in script
    assert "exact-value" in script
    assert "escapeHtml" in script


@pytest.mark.parametrize("asset_name", ["report.js", "report.min.js"])
def test_report_frontend_assets_use_chinese_user_facing_copy(asset_name):
    script = Path(
        "src/igess/reporting/assets",
        asset_name,
    ).read_text(encoding="utf-8")

    for expected in (
        "模拟时长",
        "首次关键解锁",
        "永久成长次数",
        "总产出速率",
        "成长瓶颈",
        "公式计算过程",
        "没有可展示的数据",
    ):
        assert expected in script
    for removed in (
        "First key unlock",
        "Persistent gains",
        "Total CPS",
        "Formula traces",
        "No data available",
    ):
        assert removed not in script


@pytest.mark.skipif(NODE is None, reason="Node.js is required to execute the report renderer")
def test_daily_progression_categories_keep_the_same_color_across_days():
    script_path = Path("src/igess/reporting/assets/report.js").resolve()
    harness = r"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
const context = { console };
vm.createContext(context);
vm.runInContext(source, context);

const target = { innerHTML: '' };
const options = {};
context.document = {
  querySelector(selector) {
    return selector === '[data-daily-progression-charts]' ? target : null;
  },
  getElementById(id) { return { id, innerHTML: '' }; },
};
context.echarts = {
  init(element) {
    return {
      setOption(option) { options[element.id] = option; },
      dispose() {},
      resize() {},
    };
  },
};

const row = (category, time) => ({
  progression_category: category,
  day_active_time_seconds: time,
  active_time_seconds: time,
});
context.renderDailyProgressionCharts({
  default: {
    days: [
      { day_index: 1, duration_seconds: { chart_value: 7200 }, rows: [
        row('best_hall_fish', 60),
        row('torpedo', 120),
        row('torpedo', 240),
      ] },
      { day_index: 2, duration_seconds: { chart_value: 7200 }, rows: [
        row('torpedo', 180),
      ] },
    ],
  },
});

const firstDayTorpedo = options['daily-progression-chart-0'].series
  .find(series => series.name === '鱼雷 / 垃圾幸运值');
const secondDayTorpedo = options['daily-progression-chart-1'].series
  .find(series => series.name === '鱼雷 / 垃圾幸运值');
process.stdout.write(JSON.stringify({
  first: firstDayTorpedo.itemStyle.color,
  second: secondDayTorpedo.itemStyle.color,
  firstCard: target.innerHTML.split('</article>')[0],
  secondCard: target.innerHTML.split('</article>')[1],
}));
"""

    result = subprocess.run(
        [NODE, "-e", harness, str(script_path)],
        capture_output=True,
        text=True,
        check=True,
    )

    colors = json.loads(result.stdout)
    assert colors["first"] == "#73c0de"
    assert colors["second"] == "#73c0de"
    assert 'data-progression-category="best_hall_fish"' in colors["firstCard"]
    assert 'data-progression-category="torpedo"' in colors["firstCard"]
    assert "鱼雷 / 垃圾幸运值 <strong>2</strong>" in colors["firstCard"]
    assert 'data-progression-category="barbell"' not in colors["firstCard"]
    assert "鱼雷 / 垃圾幸运值 <strong>1</strong>" in colors["secondCard"]


@pytest.mark.skipif(NODE is None, reason="Node.js is required to execute the report renderer")
def test_weekly_progression_charts_use_week_local_online_time():
    script_path = Path("src/igess/reporting/assets/report.js").resolve()
    harness = r"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
const context = { console };
vm.createContext(context);
vm.runInContext(source, context);

const target = { innerHTML: '' };
const options = {};
context.document = {
  querySelector(selector) {
    return selector === '[data-weekly-progression-charts]' ? target : null;
  },
  getElementById(id) { return { id, innerHTML: '' }; },
};
context.echarts = {
  init(element) {
    return {
      setOption(option) { options[element.id] = option; },
      dispose() {},
      resize() {},
    };
  },
};

context.renderWeeklyProgressionCharts({
  default: {
    weeks: [
      { week_index: 1, duration_seconds: { chart_value: 50400 }, rows: [
        {
          progression_category: 'torpedo',
          week_active_time_seconds: 14500,
          active_time_seconds: 14500,
        },
        {
          progression_category: 'torpedo',
          week_active_time_seconds: 18000,
          active_time_seconds: 18000,
        },
      ] },
      { week_index: 2, duration_seconds: { chart_value: 7200 }, rows: [
        {
          progression_category: 'barbell',
          week_active_time_seconds: 900,
          active_time_seconds: 51300,
        },
      ] },
    ],
  },
});

const first = options['weekly-progression-chart-0'];
const second = options['weekly-progression-chart-1'];
process.stdout.write(JSON.stringify({
  html: target.innerHTML,
  firstX: first.series[0].data[0].value[0],
  firstMax: first.xAxis.max,
  secondX: second.series[0].data[0].value[0],
  secondMax: second.xAxis.max,
  firstCard: target.innerHTML.split('</article>')[0],
  secondCard: target.innerHTML.split('</article>')[1],
}));
"""

    result = subprocess.run(
        [NODE, "-e", harness, str(script_path)],
        capture_output=True,
        text=True,
        check=True,
    )

    rendered = json.loads(result.stdout)
    assert "第 1 周" in rendered["html"]
    assert "第 2 周" in rendered["html"]
    assert rendered["firstX"] == 14500
    assert rendered["firstMax"] == 50400
    assert rendered["secondX"] == 900
    assert rendered["secondMax"] == 7200
    assert "鱼雷 / 垃圾幸运值 <strong>2</strong>" in rendered["firstCard"]
    assert 'data-progression-category="barbell"' not in rendered["firstCard"]
    assert "杠铃 <strong>1</strong>" in rendered["secondCard"]


@pytest.mark.skipif(NODE is None, reason="Node.js is required to execute the report renderer")
def test_progression_category_counts_handle_empty_and_escaped_categories():
    script_path = Path("src/igess/reporting/assets/report.js").resolve()
    harness = r"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
const context = { console };
vm.createContext(context);
vm.runInContext(source, context);
process.stdout.write(JSON.stringify({
  empty: context.progressionCategoryCountsMarkup([]),
  escaped: context.progressionCategoryCountsMarkup([
    { progression_category: '<script>alert(1)</script>' },
  ]),
}));
"""

    result = subprocess.run(
        [NODE, "-e", harness, str(script_path)],
        capture_output=True,
        text=True,
        check=True,
    )

    markup = json.loads(result.stdout)
    assert "暂无分类成长点" in markup["empty"]
    assert "<script>" not in markup["escaped"]
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in markup["escaped"]


@pytest.mark.skipif(NODE is None, reason="Node.js is required to execute the report renderer")
def test_report_renderers_escape_content_and_expose_exact_numeric_values():
    point = {
        "exact_value": '\"><script>alert("exact")</script>',
        "display_value": "<display>",
        "chart_value": None,
    }
    metric = {
        "exact_value": "123.456789",
        "display_value": "123.457",
        "chart_value": 123.456789,
    }
    time_point = {
        "exact_value": "0.0000123456789",
        "display_value": "1.23457e-5",
        "chart_value": 0.0000123456789,
    }
    gap_count = {"exact_value": "2", "display_value": "2", "chart_value": 2.0}
    report = {
        "scenario": {"id": "<scenario>", "profiles": ["<profile>"]},
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
        "series": {
            "resources": [
                {
                    "time_seconds": time_point["chart_value"],
                    "time": time_point,
                    "profile_id": "<profile>",
                    "resource_id": "<resource>",
                    **metric,
                }
            ],
            "total_cps": [
                {
                    "time_seconds": time_point["chart_value"],
                    "time": time_point,
                    "profile_id": "<profile>",
                    **metric,
                }
            ],
            "events": [
                {
                    "time_seconds": time_point["chart_value"],
                    "time": time_point,
                    "profile_id": "<profile>",
                    "kind": "<event-kind>",
                    "item_id": "</p><script>alert('event')</script>",
                }
            ],
        },
        "diagnostics": {
            "invalid_content": {"never_purchased": ["<never>"], "never_unlocked": []},
            "overpowered_content": [{"item_id": "<overpowered>"}],
            "bottlenecks": {"<gap-profile>": [{}, {}]},
            "bottleneck_gap_counts": {"<gap-profile>": gap_count},
            "payback": [
                {
                    "profile_id": "<pay-profile>",
                    "kind": "<pay-kind>",
                    "item_id": "<pay-item>",
                    "payback_seconds": metric,
                    "cost": metric,
                    "delta_cps": metric,
                    "source_ref": "</p><script>alert('source')</script>",
                }
            ],
        },
        "evidence": {
            "traces": [
                {
                    "profile_id": "<trace-profile>",
                    "time": time_point,
                    "kind": "<trace-kind>",
                    "item_id": "<trace-item>",
                    "formula_trace": "</li><script>alert('trace')</script>",
                }
            ],
            "source_refs": [],
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
const targets = {
  overview: { innerHTML: '' },
  diagnostics: { innerHTML: '' },
  evidence: { innerHTML: '' },
};
const chartElements = Object.fromEntries(
  ['resource-chart', 'cps-chart', 'event-chart', 'payback-chart'].map(id => [id, { id, innerHTML: '' }])
);
const options = {};
context.document = {
  querySelector(selector) {
    if (selector === '[data-scenario]') return scenario;
    if (selector === '[data-overview-kpis]') return targets.overview;
    if (selector === '[data-diagnostics]') return targets.diagnostics;
    if (selector === '[data-evidence]') return targets.evidence;
    return null;
  },
  getElementById(id) {
    return chartElements[id] || null;
  },
};
context.echarts = {
  init(element) {
    return {
      setOption(option) { options[element.id] = option; },
      dispose() {},
      resize() {},
    };
  },
};
const report = JSON.parse(process.argv[2]);
context.renderOverview(report);
context.renderDiagnostics(report);
context.renderEvidence(report);
context.renderResourceChart(report, '<resource>');
context.renderCpsChart(report);
context.renderEventChart(report);
context.renderPaybackChart(report);
function lineTooltip(id) {
  const option = options[id];
  const datum = option.series[0].data[0];
  return option.tooltip.formatter([{ seriesName: '<series>', data: datum }]);
}
const eventOption = options['event-chart'];
const eventDatum = eventOption.series[0].data[0];
const paybackOption = options['payback-chart'];
const paybackDatum = paybackOption.series[0].data[0];
process.stdout.write(JSON.stringify({
  scenario: scenario.textContent,
  overview: targets.overview.innerHTML,
  diagnostics: targets.diagnostics.innerHTML,
  evidence: targets.evidence.innerHTML,
  resourceTooltip: lineTooltip('resource-chart'),
  cpsTooltip: lineTooltip('cps-chart'),
  eventTooltip: eventOption.tooltip.formatter({ data: eventDatum }),
  paybackTooltip: paybackOption.tooltip.formatter({ data: paybackDatum }),
}));
"""

    completed = subprocess.run(
        [NODE, "-e", harness, str(script_path), json.dumps(report)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    rendered = json.loads(completed.stdout)
    html = rendered["overview"]
    assert rendered["scenario"] == "<scenario>"
    assert html.count('role="listitem"') == 9
    assert '<details class="exact-values">' in html
    assert 'data-exact-value=' in html
    assert "&lt;profile&gt;" in html
    assert "&lt;resource&gt;" in html
    assert "&lt;display&gt;" in html
    duration_card = html.split("<h3>模拟时长</h3>", 1)[1].split("</article>", 1)[0]
    purchases_card = html.split("<h3>购买次数</h3>", 1)[1].split("</article>", 1)[0]
    assert '<details class="exact-value">' in duration_card
    assert '<details class="exact-value">' in purchases_card
    assert "<summary>精确值</summary>" in duration_card
    assert "<code>&quot;&gt;&lt;script&gt;" in duration_card
    assert "&lt;gap-profile&gt;" in rendered["diagnostics"]
    assert 'title="精确值：2"' in rendered["diagnostics"]
    assert "2</span> 个空窗" in rendered["diagnostics"]
    assert "&lt;trace-profile&gt;" in rendered["evidence"]
    assert "1.23457e-5秒" in rendered["evidence"]
    assert 'title="精确值：0.0000123456789"' in rendered["evidence"]

    assert "&lt;series&gt;" in rendered["resourceTooltip"]
    assert 'title="精确值：123.456789"' in rendered["resourceTooltip"]
    assert 'title="精确值：0.0000123456789"' in rendered["resourceTooltip"]
    assert 'title="精确值：123.456789"' in rendered["cpsTooltip"]
    assert "&lt;event-kind&gt;" in rendered["eventTooltip"]
    assert 'title="精确值：0.0000123456789"' in rendered["eventTooltip"]
    assert "&lt;pay-profile&gt;" in rendered["paybackTooltip"]
    assert 'title="精确值：123.456789"' in rendered["paybackTooltip"]

    for value in rendered.values():
        assert "<script>" not in value


def test_report_script_bootstraps_inline_payload_without_unhandled_rejection():
    assert NODE is not None, "Node.js is required for report UI bootstrap verification"
    point = {"exact_value": "2", "display_value": "2", "chart_value": 2.0}
    time_point = {"exact_value": "1", "display_value": "1", "chart_value": 1.0}
    report = {
        "scenario": {"id": "bootstrap", "profiles": ["player"]},
        "overview": {
            "resource_ids": ["gold"],
            "duration_seconds": point,
            "profiles": ["player"],
            "purchase_count": point,
            "first_key_unlock": None,
            "prestige_reset_count": point,
            "worst_payback": None,
            "never_purchased_count": point,
            "never_unlocked_count": point,
            "warning_category_count": point,
            "final_resources": {"player": {"gold": point}},
        },
        "series": {
            "resources": [
                {
                    "time_seconds": 1,
                    "time": time_point,
                    "profile_id": "player",
                    "resource_id": "gold",
                    **point,
                }
            ],
            "total_cps": [
                {
                    "time_seconds": 1,
                    "time": time_point,
                    "profile_id": "player",
                    **point,
                }
            ],
            "events": [
                {
                    "time_seconds": 1,
                    "time": time_point,
                    "profile_id": "player",
                    "kind": "buy_generator",
                    "item_id": "mine",
                }
            ],
        },
        "diagnostics": {
            "invalid_content": {},
            "overpowered_content": [],
            "bottleneck_gap_counts": {"player": point},
            "payback": [
                {
                    "profile_id": "player",
                    "kind": "generator",
                    "item_id": "mine",
                    "payback_seconds": point,
                    "cost": point,
                    "delta_cps": point,
                    "source_ref": "generators:mine",
                }
            ],
        },
        "evidence": {
            "traces": [
                {
                    "profile_id": "player",
                    "time": time_point,
                    "kind": "buy_generator",
                    "item_id": "mine",
                    "formula_trace": "base_output * owned",
                }
            ],
            "source_refs": [],
        },
    }
    script_path = Path("src/igess/reporting/assets/report.js").resolve()
    harness = r"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
const inline = { textContent: process.argv[2] };
const scenario = { textContent: '' };
const targets = {
  overview: { innerHTML: '' },
  controls: { innerHTML: '', querySelectorAll() { return []; } },
  diagnostics: { innerHTML: '' },
  evidence: { innerHTML: '' },
};
const chartElements = Object.fromEntries(
  ['resource-chart', 'cps-chart', 'event-chart', 'payback-chart'].map(id => [id, { id, innerHTML: '' }])
);
const options = {};
const resizeEvents = [];
let unhandled = '';
process.once('unhandledRejection', reason => {
  unhandled = String(reason && (reason.stack || reason));
});
const documentStub = {
  getElementById(id) {
    if (id === 'igess-report-data') return inline;
    return chartElements[id] || null;
  },
  querySelector(selector) {
    if (selector === '[data-scenario]') return scenario;
    if (selector === '[data-overview-kpis]') return targets.overview;
    if (selector === '[data-resource-controls]') return targets.controls;
    if (selector === '[data-diagnostics]') return targets.diagnostics;
    if (selector === '[data-evidence]') return targets.evidence;
    return null;
  },
};
const context = {
  console,
  document: documentStub,
  window: { addEventListener(name) { resizeEvents.push(name); } },
  echarts: {
    init(element) {
      return {
        setOption(option) { options[element.id] = option; },
        dispose() {},
        resize() {},
      };
    },
  },
};
vm.createContext(context);
vm.runInContext(source, context);
setImmediate(() => {
  process.stdout.write(JSON.stringify({
    unhandled,
    scenario: scenario.textContent,
    overview: targets.overview.innerHTML,
    controls: targets.controls.innerHTML,
    diagnostics: targets.diagnostics.innerHTML,
    evidence: targets.evidence.innerHTML,
    charts: Object.keys(options).sort(),
    resizeEvents,
  }));
});
"""

    completed = subprocess.run(
        [NODE, "-e", harness, str(script_path), json.dumps(report)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    rendered = json.loads(completed.stdout)
    assert rendered["unhandled"] == ""
    assert rendered["scenario"] == "bootstrap"
    assert '<details class="exact-value">' in rendered["overview"]
    assert 'data-resource="gold"' in rendered["controls"]
    assert rendered["charts"] == [
        "cps-chart",
        "event-chart",
        "payback-chart",
        "resource-chart",
    ]
    assert rendered["diagnostics"]
    assert rendered["evidence"]
    assert rendered["resizeEvents"] == ["resize"]


def test_generate_static_report_embeds_parseable_json_payload(tmp_path):
    run_dir = _write_sample_run(tmp_path)
    report_dir = tmp_path / "report"

    generated = generate_static_report(run_dir, report_dir)

    html = generated.read_text(encoding="utf-8")
    assert "IGESS 调优报告 - 首日成长" in html
    marker = '<script id="igess-report-data" type="application/json">'
    start = html.index(marker) + len(marker)
    end = html.index("</script>", start)
    inline_payload = json.loads(html[start:end])
    file_payload = json.loads((report_dir / "report_data.json").read_text(encoding="utf-8"))
    assert inline_payload == file_payload
    assert inline_payload["schema_version"] == 5
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
