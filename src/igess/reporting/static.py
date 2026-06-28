from __future__ import annotations

import html
import json
import shutil
from importlib.resources import files
from pathlib import Path
from typing import Any

from .loader import load_report_data
from .view_model import build_report_view_model


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
    report_title = title or f"IGESS Report - {data.scenario_id}"
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
            '<html lang="en">',
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
            "      <h2>Overview</h2>",
            "      <p>Scenario: <code data-scenario></code></p>",
            "    </section>",
            '    <section class="band">',
            "      <h2>Resource Curves</h2>",
            '      <div data-resource-controls class="controls"></div>',
            '      <div id="resource-chart" class="chart"></div>',
            "    </section>",
            '    <section class="band">',
            "      <h2>Total CPS</h2>",
            '      <div id="cps-chart" class="chart"></div>',
            "    </section>",
            '    <section class="band">',
            "      <h2>Event Timeline</h2>",
            '      <div id="event-chart" class="chart"></div>',
            "    </section>",
            '    <section class="band">',
            "      <h2>Payback Pressure</h2>",
            '      <div id="payback-chart" class="chart"></div>',
            "    </section>",
            '    <section class="band">',
            "      <h2>Analysis Warnings</h2>",
            "      <div data-diagnostics></div>",
            "    </section>",
            '    <section class="band">',
            "      <h2>Evidence</h2>",
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


def _json_script_payload(value: Any) -> str:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True)
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
