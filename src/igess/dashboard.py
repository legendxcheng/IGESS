from __future__ import annotations

import html
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .workflows import WorkflowService


def render_dashboard_home(service: WorkflowService, config: str | Path, tables: str | Path) -> str:
    lint = service.lint(config, tables)
    runs = service.list_runs()
    advice = service.latest_advice()
    advice_html = _advice_panel(advice)
    run_rows = "\n".join(
        "        <tr>"
        f"<td>{_e(record.run_id)}</td>"
        f"<td>{_e(record.scenario_id)}</td>"
        f"<td>{_e(record.status)}</td>"
        f"<td>{_e(record.message)}</td>"
        f"<td><a href=\"/reports/{_e(record.run_id)}/index.html\">report</a></td>"
        "</tr>"
        for record in runs
    )
    if not run_rows:
        run_rows = '        <tr><td colspan="5">No runs yet.</td></tr>'
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>IGESS Dashboard</title>
  <style>
    body {{ margin: 0; font-family: Segoe UI, Arial, sans-serif; background: #f5f7fa; color: #17202a; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 24px; }}
    section {{ background: white; border: 1px solid #d9e1ea; border-radius: 6px; padding: 18px; margin: 14px 0; }}
    label {{ display: block; font-weight: 700; margin-bottom: 6px; }}
    input {{ padding: 8px; min-width: 280px; }}
    button {{ padding: 8px 12px; margin-top: 10px; cursor: pointer; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ border-bottom: 1px solid #e3e8ef; padding: 8px; text-align: left; }}
    .ok {{ color: #166534; }}
    .failed {{ color: #991b1b; }}
  </style>
</head>
<body>
  <main>
    <h1>IGESS Dashboard</h1>
    <section>
      <h2>Diagnostics</h2>
      <p class="{'ok' if lint.ok else 'failed'}">{_e(lint.message)}</p>
      <p>Config: <code>{_e(config)}</code></p>
      <p>Tables: <code>{_e(tables)}</code></p>
    </section>
    <section>
      <h2>Run Scenario</h2>
      <form action="/run" method="get">
        <input type="hidden" name="config" value="{_e(config)}">
        <input type="hidden" name="tables" value="{_e(tables)}">
        <label for="scenario">Scenario</label>
        <input id="scenario" name="scenario" value="day_1_progression">
        <br>
        <button type="submit">Run</button>
      </form>
    </section>
    <section>
      <h2>Agent Analyst</h2>
      <form action="/advise" method="get">
        <input type="hidden" name="config" value="{_e(config)}">
        <input type="hidden" name="tables" value="{_e(tables)}">
        <label for="advice-scenario">Scenario</label>
        <input id="advice-scenario" name="scenario" value="day_1_progression">
        <br>
        <button type="submit">Run Advice</button>
      </form>
      {advice_html}
    </section>
    <section>
      <h2>Run History</h2>
      <table>
        <thead><tr><th>Run</th><th>Scenario</th><th>Status</th><th>Message</th><th>Report</th></tr></thead>
        <tbody>
{run_rows}
        </tbody>
      </table>
    </section>
  </main>
</body>
</html>
"""


def serve_dashboard(
    *,
    project: str | Path,
    config: str | Path,
    tables: str | Path,
    runs_root: str | Path | None,
    host: str,
    port: int,
) -> None:
    project_path = Path(project)
    service = WorkflowService(project_path, runs_root)
    handler = _handler(service, config, tables)
    server = ThreadingHTTPServer((host, port), handler)
    print(f"IGESS dashboard running at http://{host}:{port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def _handler(service: WorkflowService, config: str | Path, tables: str | Path):
    class DashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib handler API.
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._send_html(render_dashboard_home(service, config, tables))
                return
            if parsed.path == "/run":
                query = parse_qs(parsed.query)
                scenario = query.get("scenario", ["day_1_progression"])[0]
                run_config = query.get("config", [str(config)])[0]
                run_tables = query.get("tables", [str(tables)])[0]
                service.run_scenario(run_config, run_tables, scenario)
                self.send_response(303)
                self.send_header("Location", "/")
                self.end_headers()
                return
            if parsed.path == "/advise":
                query = parse_qs(parsed.query)
                scenario = query.get("scenario", ["day_1_progression"])[0]
                run_config = query.get("config", [str(config)])[0]
                run_tables = query.get("tables", [str(tables)])[0]
                service.run_advice(run_config, run_tables, scenario)
                self.send_response(303)
                self.send_header("Location", "/")
                self.end_headers()
                return
            if parsed.path.startswith("/reports/"):
                self._send_report_file(parsed.path.removeprefix("/reports/"))
                return
            self.send_error(404)

        def log_message(self, format: str, *args) -> None:  # noqa: A002
            return

        def _send_html(self, body: str) -> None:
            encoded = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def _send_report_file(self, relative: str) -> None:
            parts = Path(relative)
            if len(parts.parts) < 2:
                self.send_error(404)
                return
            run_id = parts.parts[0]
            rest = Path(*parts.parts[1:])
            run = next((record for record in service.list_runs() if record.run_id == run_id), None)
            if run is None:
                self.send_error(404)
                return
            path = run.report_dir / rest
            if not path.exists() or not path.is_file():
                self.send_error(404)
                return
            body = path.read_bytes()
            self.send_response(200)
            self.send_header(
                "Content-Type",
                mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            )
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return DashboardHandler


def _advice_panel(advice: dict | None) -> str:
    if advice is None:
        return "<p>Latest advice: none yet.</p>"
    findings = advice.get("findings", [])
    recommendations = advice.get("table_recommendations", [])
    finding_items = "".join(
        f"<li>{_e(item.get('category'))}: {_e(item.get('message'))}</li>" for item in findings[:5]
    )
    rec_items = "".join(
        f"<li>{_e(item.get('workbook'))} {_e(item.get('row_id'))} {_e(item.get('field'))}</li>"
        for item in recommendations[:5]
    )
    if not finding_items:
        finding_items = "<li>No findings.</li>"
    if not rec_items:
        rec_items = "<li>No table recommendations.</li>"
    return (
        f"<p>Latest advice: <code>{_e(advice.get('status'))}</code></p>"
        f"<p>{_e(advice.get('summary'))}</p>"
        f"<h3>Main findings</h3><ul>{finding_items}</ul>"
        f"<h3>Human table recommendations</h3><ul>{rec_items}</ul>"
    )


def _e(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)
