from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from .loader import ReportData, load_report_data


def generate_static_report(
    run_dir: str | Path, output_dir: str | Path, title: str | None = None
) -> Path:
    data = load_report_data(run_dir)
    output_dir = Path(output_dir)
    assets_dir = output_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    report_title = title or f"IGESS Report - {data.scenario_id}"
    (assets_dir / "report.css").write_text(_css(), encoding="utf-8", newline="\n")
    (assets_dir / "report.js").write_text(_js(), encoding="utf-8", newline="\n")
    index = output_dir / "index.html"
    index.write_text(_html(data, report_title), encoding="utf-8", newline="\n")
    return index


def _html(data: ReportData, title: str) -> str:
    payload = {
        "timeline": data.timeline,
        "events": data.events,
        "profiles": data.profiles,
    }
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
            "<body>",
            "  <main>",
            f"    <h1>{_e(title)}</h1>",
            _overview(data),
            _resource_section(payload),
            _events_section(data),
            _payback_section(data),
            _analysis_section(data),
            _trace_section(data),
            "  </main>",
            "  <script id=\"igess-data\" type=\"application/json\">"
            + _e(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            + "</script>",
            '  <script src="assets/report.js"></script>',
            "</body>",
            "</html>",
            "",
        ]
    )


def _overview(data: ReportData) -> str:
    missing = ", ".join(data.missing_artifacts) if data.missing_artifacts else "None"
    rows = [
        ("Scenario", data.scenario_id),
        ("Model", str(data.manifest.get("model_id") or "Unknown")),
        ("Profiles", ", ".join(data.profiles)),
        ("Timeline rows", str(len(data.timeline))),
        ("Events", str(len(data.events))),
        ("Missing artifacts", missing),
    ]
    items = "\n".join(f"        <dt>{_e(label)}</dt><dd>{_e(value)}</dd>" for label, value in rows)
    return f"""
    <section class="band">
      <h2>Overview</h2>
      <dl class="overview">
{items}
      </dl>
    </section>"""


def _resource_section(payload: dict[str, Any]) -> str:
    timeline = payload["timeline"]
    resource_ids = sorted(
        {
            resource_id
            for row in timeline
            for resource_id in dict(row.get("resources", {})).keys()
        }
    )
    buttons = "\n".join(
        f'        <button type="button" data-resource="{_e(resource_id)}">{_e(resource_id)}</button>'
        for resource_id in resource_ids
    )
    if not buttons:
        buttons = "        <p>No timeline resources available.</p>"
    return f"""
    <section class="band">
      <h2>Resource Curves</h2>
      <div class="resource-controls">
{buttons}
      </div>
      <div id="resource-chart" class="chart" aria-label="Resource chart"></div>
    </section>"""


def _events_section(data: ReportData) -> str:
    rows = "\n".join(
        "        <tr>"
        f"<td>{event.get('time_seconds')}</td>"
        f"<td>{_e(event.get('profile_id'))}</td>"
        f"<td>{_e(event.get('kind'))}</td>"
        f"<td>{_e(event.get('item_id'))}</td>"
        "</tr>"
        for event in data.events[:100]
    )
    return f"""
    <section class="band">
      <h2>Event Timeline</h2>
      <table>
        <thead><tr><th>Time</th><th>Profile</th><th>Kind</th><th>Item</th></tr></thead>
        <tbody>
{rows}
        </tbody>
      </table>
    </section>"""


def _payback_section(data: ReportData) -> str:
    if not data.payback_rows:
        body = '        <tr><td colspan="6">Payback data is not available.</td></tr>'
    else:
        body = "\n".join(
            "        <tr>"
            f"<td>{_e(row.get('profile_id'))}</td>"
            f"<td>{_e(row.get('kind'))}</td>"
            f"<td>{_e(row.get('item_id'))}</td>"
            f"<td>{_e(row.get('cost'))}</td>"
            f"<td>{_e(row.get('delta_cps'))}</td>"
            f"<td>{_e(row.get('payback_seconds'))}</td>"
            "</tr>"
            for row in data.payback_rows[:100]
        )
    return f"""
    <section class="band">
      <h2>Payback</h2>
      <table>
        <thead><tr><th>Profile</th><th>Kind</th><th>Item</th><th>Cost</th><th>Delta CPS</th><th>Payback Seconds</th></tr></thead>
        <tbody>
{body}
        </tbody>
      </table>
    </section>"""


def _analysis_section(data: ReportData) -> str:
    invalid = data.analysis.get("invalid_content_report", {})
    overpowered = data.analysis.get("overpowered_content_report", [])
    bottlenecks = data.analysis.get("bottleneck_report", {})
    warnings = [
        ("Never Purchased", invalid.get("never_purchased", [])),
        ("Never Unlocked", invalid.get("never_unlocked", [])),
        ("Overpowered", [row.get("item_id") for row in overpowered]),
        ("Bottlenecks", [f"{profile}: {len(gaps)} gaps" for profile, gaps in bottlenecks.items()]),
    ]
    items = "\n".join(
        f"        <li><strong>{_e(label)}:</strong> {_e(', '.join(map(str, values)) or 'None')}</li>"
        for label, values in warnings
    )
    return f"""
    <section class="band">
      <h2>Analysis Warnings</h2>
      <ul>
{items}
      </ul>
    </section>"""


def _trace_section(data: ReportData) -> str:
    trace_rows = []
    for event in data.events:
        details = event.get("details", {})
        if isinstance(details, dict) and details.get("formula_trace"):
            trace_rows.append(
                f"<li><code>{_e(event.get('profile_id'))} {event.get('time_seconds')}s "
                f"{_e(event.get('kind'))}:{_e(event.get('item_id'))}</code> "
                f"{_e(details.get('formula_trace'))}</li>"
            )
    for row in data.payback_rows:
        if row.get("formula_trace"):
            trace_rows.append(
                f"<li><code>{_e(row.get('profile_id'))} payback:{_e(row.get('item_id'))}</code> "
                f"{_e(row.get('formula_trace'))}</li>"
            )
    body = "\n".join(f"        {row}" for row in trace_rows[:100]) or "        <li>No traces available.</li>"
    return f"""
    <section class="band">
      <h2>Trace View</h2>
      <ul class="traces">
{body}
      </ul>
    </section>"""


def _css() -> str:
    return """
:root {
  color-scheme: light;
  font-family: Segoe UI, Arial, sans-serif;
  background: #f4f6f8;
  color: #17202a;
}
body {
  margin: 0;
}
main {
  max-width: 1180px;
  margin: 0 auto;
  padding: 24px;
}
h1 {
  font-size: 32px;
  margin: 0 0 20px;
}
h2 {
  font-size: 20px;
  margin: 0 0 14px;
}
.band {
  background: #ffffff;
  border: 1px solid #d8dee6;
  border-radius: 6px;
  margin: 14px 0;
  padding: 18px;
}
.overview {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 8px 18px;
}
dt {
  font-weight: 700;
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 14px;
}
th,
td {
  border-bottom: 1px solid #e3e8ef;
  padding: 8px;
  text-align: left;
}
.chart {
  min-height: 260px;
  border: 1px solid #e3e8ef;
  border-radius: 4px;
  padding: 8px;
}
.resource-controls {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
}
.resource-controls button {
  border: 1px solid #8aa0b8;
  background: #edf4fb;
  border-radius: 4px;
  padding: 6px 10px;
  cursor: pointer;
}
.traces {
  overflow-wrap: anywhere;
}
"""


def _js() -> str:
    return """
const raw = document.getElementById('igess-data');
const chart = document.getElementById('resource-chart');
const data = raw ? JSON.parse(raw.textContent) : { timeline: [], profiles: [] };

function numeric(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function render(resource) {
  const rows = data.timeline || [];
  if (!rows.length || !resource) {
    chart.textContent = 'No resource data available.';
    return;
  }
  const width = 920;
  const height = 240;
  const maxTime = Math.max(...rows.map(row => Number(row.time_seconds || 0)), 1);
  const maxValue = Math.max(...rows.map(row => numeric((row.resources || {})[resource])), 1);
  const colors = ['#1f77b4', '#2ca02c', '#d62728', '#9467bd', '#8c564b'];
  const profiles = data.profiles || [];
  const lines = profiles.map((profile, index) => {
    const points = rows
      .filter(row => row.profile_id === profile)
      .map(row => {
        const x = (Number(row.time_seconds || 0) / maxTime) * width;
        const y = height - (numeric((row.resources || {})[resource]) / maxValue) * height;
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(' ');
    return `<polyline fill="none" stroke="${colors[index % colors.length]}" stroke-width="2" points="${points}" />`;
  }).join('');
  const legend = profiles.map((profile, index) =>
    `<span style="color:${colors[index % colors.length]}">${profile}</span>`
  ).join(' | ');
  chart.innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="img">${lines}</svg><div>${legend}</div>`;
}

document.querySelectorAll('[data-resource]').forEach((button, index) => {
  button.addEventListener('click', () => render(button.dataset.resource));
  if (index === 0) {
    render(button.dataset.resource);
  }
});
"""


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)
