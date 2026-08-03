from __future__ import annotations

import html
import json
import shutil
from importlib.resources import files
from pathlib import Path
from typing import Any

from .loader import load_report_data
from .view_model import build_report_view_model


_SCENARIO_LABELS = {
    "smoke": "冒烟验证",
    "analytic_smoke": "解析式冒烟验证",
    "day_1_progression": "首日成长",
    "day_1_growth": "首日成长",
    "week_1_growth": "首周成长",
    "month_1_growth": "首月成长",
}


def generate_static_report(
    run_dir: str | Path, output_dir: str | Path, title: str | None = None
) -> Path:
    data = load_report_data(run_dir)
    output_dir = Path(output_dir)
    assets_dir = output_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    _copy_assets(assets_dir)
    report_payload = build_report_view_model(data)
    payload_json = json.dumps(report_payload, ensure_ascii=False, indent=2, sort_keys=True)
    inline_payload = _json_script_payload(report_payload)
    (output_dir / "report_data.json").write_text(
        payload_json + "\n",
        encoding="utf-8",
        newline="\n",
    )
    report_title = title or f"IGESS 调优报告 - {_scenario_label(data.scenario_id)}"
    index = output_dir / "index.html"
    index.write_text(
        _html(inline_payload, report_title),
        encoding="utf-8",
        newline="\n",
    )
    return index


def _copy_assets(assets_dir: Path) -> None:
    package_assets = files("igess.reporting").joinpath("assets")
    for name in ("report.css", "report.js", "echarts.min.js"):
        shutil.copyfile(package_assets.joinpath(name), assets_dir / name)


def _html(inline_payload: str, title: str) -> str:
    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="zh-CN">',
            "<head>",
            '  <meta charset="utf-8">',
            '  <meta name="viewport" content="width=device-width, initial-scale=1">',
            f"  <title>{_e(title)}</title>",
            '  <link rel="stylesheet" href="assets/report.css">',
            "</head>",
            '<body data-report-src="report_data.json">',
            "  <main>",
            f"    <h1>{_e(title)}</h1>",
            '    <section class="band">',
            "      <h2>运行总览</h2>",
            "      <p>场景：<code data-scenario></code></p>",
            '      <div data-overview-kpis class="kpi-grid" role="list" aria-label="模拟运行总览"></div>',
            "    </section>",
            '    <section class="band" data-fish-core-section hidden>',
            "      <h2>摸鱼经济对称性总览</h2>",
            '      <p class="section-note">三张图统一使用累计在线时间；速率按 5 分钟在线窗口计算，累计值为不受消费影响的在线毛产出。对数同轴用于直接比较数量级。</p>',
            '      <div data-fish-core-kpis class="kpi-grid" role="list" aria-label="核心力量成长"></div>',
            '      <div id="fish-acquisition-rate-chart" class="chart chart-primary"></div>',
            '      <div id="fish-cumulative-output-chart" class="chart chart-primary"></div>',
            '      <div id="luck-progression-chart" class="chart"></div>',
            "    </section>",
            '    <section class="band" data-fish-persistent-section hidden>',
            "      <h2>每日有效成长时间点</h2>",
            '      <p class="section-note">按每天的在线时间依次展示跨鱼或永久能力成长；单鱼升级、训练结算与临时增益不计入有效成长。</p>',
            '      <div data-fish-persistent-kpis class="kpi-grid" role="list" aria-label="永久成长"></div>',
            '      <div data-daily-progression-charts class="daily-chart-list"></div>',
            '      <div data-progression-events class="table-wrap"></div>',
            "    </section>",
            '    <section class="band">',
            "      <h2>资源曲线</h2>",
            '      <div data-resource-controls class="controls"></div>',
            '      <div id="resource-chart" class="chart"></div>',
            "    </section>",
            '    <section class="band">',
            "      <h2>总产出速率</h2>",
            '      <div id="cps-chart" class="chart"></div>',
            "    </section>",
            '    <section class="band">',
            "      <h2>事件时间线</h2>",
            '      <div id="event-chart" class="chart"></div>',
            "    </section>",
            '    <section class="band">',
            "      <h2>回本压力</h2>",
            '      <div id="payback-chart" class="chart"></div>',
            "    </section>",
            '    <section class="band">',
            "      <h2>分析预警</h2>",
            "      <div data-diagnostics></div>",
            "    </section>",
            '    <section class="band">',
            "      <h2>分析依据</h2>",
            "      <div data-evidence></div>",
            "    </section>",
            "  </main>",
            '  <script id="igess-report-data" type="application/json">'
            + inline_payload
            + "</script>",
            '  <script src="assets/echarts.min.js"></script>',
            '  <script src="assets/report.js"></script>',
            "</body>",
            "</html>",
            "",
        ]
    )


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _scenario_label(scenario_id: str) -> str:
    return _SCENARIO_LABELS.get(scenario_id, scenario_id)


def _json_script_payload(value: Any) -> str:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True)
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
