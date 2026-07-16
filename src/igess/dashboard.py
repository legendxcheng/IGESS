from __future__ import annotations

import html
import json
import mimetypes
import os
import stat
from collections.abc import Mapping, Sequence
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, unquote, urlparse

from .authoring.project import AuthoringProject
from .authoring.response import CommandResponse
from .workflows import WorkflowService


_SAMPLE_CONFIG = "examples/shelldiver_v0/economy.yaml"
_SAMPLE_TABLES = "examples/shelldiver_v0/luban_exports"
_MAX_FORM_BYTES = 64 * 1024
_MUTATION_PATHS = frozenset({"/smoke", "/formal", "/run", "/advise"})


def create_dashboard_context(
    project: str | Path,
    config: str | Path | None,
    tables: str | Path | None,
    runs_root: str | Path | None,
) -> tuple[WorkflowService, str | Path, str | Path | None]:
    """Resolve authoring mode only for an unoverridden project root.

    One explicit source override selects the legacy workflow and the other
    source retains its historical sample default.  In authoring mode tables
    deliberately remain ``None``: simulations and advice obtain an ephemeral
    export from the current Datas through the authoring workflow.
    """

    project_path = Path(project)
    if config is None and tables is None:
        try:
            authoring_project = AuthoringProject.discover(project_path)
        except Exception:  # noqa: BLE001 - a non-authoring root is supported.
            pass
        else:
            service = WorkflowService(
                authoring_project.root,
                runs_root,
                authoring_project=authoring_project,
            )
            return service, authoring_project.config, None

    service = WorkflowService(project_path, runs_root, authoring=False)
    return service, config or _SAMPLE_CONFIG, tables or _SAMPLE_TABLES


def render_dashboard_home(
    service: WorkflowService,
    config: str | Path | None,
    tables: str | Path | None,
) -> str:
    status_response = service.model_status() if service.is_authoring else None
    runs = service.list_runs()
    advice = service.latest_advice()
    if status_response is not None:
        main_content = _authoring_content(service, status_response, runs, advice)
    else:
        main_content = _legacy_content(service, config, tables, runs, advice)
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
    select, input {{ padding: 8px; min-width: 280px; }}
    button {{ padding: 8px 12px; margin-top: 10px; cursor: pointer; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ border-bottom: 1px solid #e3e8ef; padding: 8px; text-align: left; }}
    .ok, .ready, .runnable {{ color: #166534; }}
    .failed {{ color: #991b1b; }}
    .incomplete {{ color: #92400e; }}
    .state-badge, .kind {{ display: inline-block; border: 1px solid currentColor; border-radius: 999px; padding: 2px 8px; font-weight: 700; }}
    .kind {{ color: #334155; font-size: 0.85rem; }}
    .actions {{ display: flex; flex-wrap: wrap; gap: 14px; align-items: end; }}
    .actions form {{ border-left: 3px solid #d9e1ea; padding-left: 12px; }}
    .counts {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 8px; }}
    .counts div {{ padding: 8px; background: #f8fafc; }}
    code {{ overflow-wrap: anywhere; }}
  </style>
</head>
<body>
  <main>
    <h1>IGESS Dashboard</h1>
{main_content}
  </main>
</body>
</html>
"""


def _authoring_content(
    service: WorkflowService,
    response: CommandResponse,
    runs: Sequence[object],
    advice: dict | None,
) -> str:
    status = response.result
    state = _text(status.get("state"), "failed")
    counts = status.get("entity_counts")
    count_items = counts.items() if isinstance(counts, Mapping) else ()
    counts_html = "".join(
        f"<div><strong>{_e(name)}</strong>: {_e(count)}</div>" for name, count in count_items
    ) or "<p>No entities defined.</p>"
    missing_html = _issue_list(status.get("missing_requirements"), "No missing requirements.")
    warnings_html = _issue_list(status.get("warnings"), "No warnings.")
    scenarios = _string_sequence(status.get("available_scenarios"))
    options = "".join(
        f'<option value="{_e(scenario)}">{_e(scenario)}</option>' for scenario in scenarios
    )
    if not options:
        options = '<option value="" disabled>No scenarios available</option>'
    latest_change = _latest_change_panel(service.latest_change())
    latest_smoke = _latest_smoke_panel(status.get("latest_smoke_run_id"), runs)
    return f"""    <section>
      <h2>Model status</h2>
      <p><span class="state-badge {_e(state)}">{_e(state)}</span> {_e(response.message)}</p>
      <p>Digest: <code>{_e(status.get('model_digest'))}</code></p>
      <a href="/status">View status JSON</a>
      <h3>Defined entities</h3>
      <div class="counts">{counts_html}</div>
      <h3>Missing requirements</h3>
      {missing_html}
      <h3>Recovery and source warnings</h3>
      {warnings_html}
    </section>
    <section>
      <h2>Latest authoring activity</h2>
      {latest_change}
      {latest_smoke}
    </section>
    <section>
      <h2>Scenario actions</h2>
      <p>Manual scenario actions are recorded as <strong>formal</strong> runs. Automatic smoke records are created by successful rule application.</p>
      <div class="actions">
        <form action="/smoke" method="post">
          <button type="submit">Run smoke scenario (formal)</button>
        </form>
        <form action="/formal" method="post">
          <label for="scenario">Formal scenario</label>
          <select id="scenario" name="scenario">{options}</select>
          <button type="submit">Run formal scenario</button>
        </form>
        <form action="/advise" method="post">
          <label for="advice-scenario">Advice scenario</label>
          <select id="advice-scenario" name="scenario">{options}</select>
          <button type="submit">Run advice (advice)</button>
        </form>
      </div>
    </section>
    {_history_panel(runs)}
    <section>
      <h2>Latest advice</h2>
      {_advice_panel(advice)}
    </section>"""


def _legacy_content(
    service: WorkflowService,
    config: str | Path | None,
    tables: str | Path | None,
    runs: Sequence[object],
    advice: dict | None,
) -> str:
    lint = service.lint(config or _SAMPLE_CONFIG, tables or _SAMPLE_TABLES)
    return f"""    <section>
      <h2>Diagnostics</h2>
      <p class="{'ok' if lint.ok else 'failed'}">{_e(lint.message)}</p>
      <p>Config: <code>{_e(config)}</code></p>
      <p>Tables: <code>{_e(tables)}</code></p>
    </section>
    <section>
      <h2>Run Scenario</h2>
      <form action="/formal" method="post">
        <label for="scenario">Scenario</label>
        <input id="scenario" name="scenario" value="day_1_progression">
        <button type="submit">Run formal scenario</button>
      </form>
    </section>
    <section>
      <h2>Agent Analyst</h2>
      <form action="/advise" method="post">
        <label for="advice-scenario">Scenario</label>
        <input id="advice-scenario" name="scenario" value="day_1_progression">
        <button type="submit">Run advice (advice)</button>
      </form>
      {_advice_panel(advice)}
    </section>
    {_history_panel(runs)}"""


def _history_panel(runs: Sequence[object]) -> str:
    rows = "\n".join(
        "        <tr>"
        f"<td>{_e(getattr(record, 'run_id', ''))}</td>"
        f"<td>{_e(getattr(record, 'scenario_id', ''))}</td>"
        f"<td><span class=\"kind kind-{_e(getattr(record, 'kind', 'formal'))}\">{_e(getattr(record, 'kind', 'formal'))}</span></td>"
        f"<td>{_e(getattr(record, 'status', ''))}</td>"
        f"<td>{_e(getattr(record, 'message', ''))}</td>"
        f"<td><a href=\"/reports/{_e(getattr(record, 'run_id', ''))}/index.html\">report</a></td>"
        "</tr>"
        for record in runs
    )
    if not rows:
        rows = '        <tr><td colspan="6">No runs yet.</td></tr>'
    return f"""    <section>
      <h2>Unified run history</h2>
      <table>
        <thead><tr><th>Run</th><th>Scenario</th><th>Kind</th><th>Status</th><th>Message</th><th>Report</th></tr></thead>
        <tbody>
{rows}
        </tbody>
      </table>
    </section>"""


def _latest_change_panel(record: dict | None) -> str:
    if record is None:
        return "<h3>Latest applied rule</h3><p>None yet.</p>"
    change = record.get("change")
    change = change if isinstance(change, Mapping) else {}
    validation = record.get("status")
    validation = validation if isinstance(validation, Mapping) else {}
    return (
        "<h3>Latest applied rule</h3>"
        f"<p><code>{_e(change.get('entity'))}:{_e(change.get('id'))}</code> "
        f"— {_e(record.get('outcome'))} at {_e(record.get('timestamp'))}</p>"
        f"<p>Validation state: <strong>{_e(validation.get('state'))}</strong></p>"
    )


def _latest_smoke_panel(run_id: object, runs: Sequence[object]) -> str:
    if not isinstance(run_id, str) or not run_id:
        return "<h3>Latest smoke</h3><p>None yet.</p>"
    record = next((item for item in runs if getattr(item, "run_id", None) == run_id), None)
    if record is None:
        return f"<h3>Latest smoke</h3><p><code>{_e(run_id)}</code></p>"
    return (
        "<h3>Latest smoke</h3>"
        f"<p><a href=\"/reports/{_e(run_id)}/index.html\"><code>{_e(run_id)}</code></a> "
        f"— {_e(getattr(record, 'status', ''))}: {_e(getattr(record, 'message', ''))}</p>"
    )


def serve_dashboard(
    *,
    project: str | Path,
    config: str | Path | None,
    tables: str | Path | None,
    runs_root: str | Path | None,
    host: str,
    port: int,
) -> None:
    service, resolved_config, resolved_tables = create_dashboard_context(
        project,
        config,
        tables,
        runs_root,
    )
    handler = _handler(service, resolved_config, resolved_tables)
    server = ThreadingHTTPServer((host, port), handler)
    print(f"IGESS dashboard running at http://{host}:{port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def _handler(
    service: WorkflowService,
    config: str | Path | None,
    tables: str | Path | None,
):
    class DashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib handler API.
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._send_html(render_dashboard_home(service, config, tables))
                return
            if parsed.path == "/status":
                self._send_status()
                return
            if parsed.path.startswith("/reports/"):
                self._send_report_file(parsed.path.removeprefix("/reports/"))
                return
            if parsed.path in _MUTATION_PATHS:
                self.send_response(HTTPStatus.METHOD_NOT_ALLOWED)
                self.send_header("Allow", "POST")
                self.end_headers()
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:  # noqa: N802 - stdlib handler API.
            parsed = urlparse(self.path)
            if parsed.path not in _MUTATION_PATHS:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            try:
                form = self._read_form()
                scenario = form.get("scenario", ["day_1_progression"])[0]
                if parsed.path == "/smoke":
                    if service.is_authoring:
                        service.run_authoring_scenario("smoke")
                    else:
                        service.run_scenario(config, tables, "smoke")
                elif parsed.path in {"/formal", "/run"}:
                    if service.is_authoring:
                        service.run_authoring_scenario(scenario)
                    else:
                        service.run_scenario(config, tables, scenario)
                else:
                    service.run_advice(
                        None if service.is_authoring else config,
                        None if service.is_authoring else tables,
                        scenario,
                    )
            except Exception:  # noqa: BLE001 - operation services persist their own failures.
                pass
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", "/")
            self.end_headers()

        def log_message(self, format: str, *args) -> None:  # noqa: A002
            return

        def _read_form(self) -> dict[str, list[str]]:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            if length < 0 or length > _MAX_FORM_BYTES:
                raise ValueError("invalid form size")
            body = self.rfile.read(length).decode("utf-8")
            return parse_qs(body, keep_blank_values=True)

        def _send_status(self) -> None:
            response = service.model_status() if service.is_authoring else None
            if response is not None:
                body = response.to_json().encode("utf-8")
            else:
                lint = service.lint(config or _SAMPLE_CONFIG, tables or _SAMPLE_TABLES)
                body = json.dumps(
                    {"ok": lint.ok, "message": lint.message},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, body: str) -> None:
            encoded = body.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def _send_report_file(self, relative: str) -> None:
            status, content_type, body = send_report_file_response(service, relative)
            self.send_response(int(status))
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return DashboardHandler


def send_report_file_response(
    service: WorkflowService,
    relative: str,
) -> tuple[HTTPStatus, str, bytes]:
    decoded = unquote(relative)
    if "\\" in decoded or "\x00" in decoded:
        return _not_found_response()
    parts = PurePosixPath(decoded).parts
    if len(parts) < 2 or any(part in {"", ".", ".."} for part in parts):
        return _not_found_response()
    run_id, *asset_parts = parts
    run = next((record for record in service.list_runs() if record.run_id == run_id), None)
    if run is None:
        return _not_found_response()
    report_root = Path(run.report_dir)
    path = report_root.joinpath(*asset_parts)
    try:
        if _is_indirection(report_root.lstat()):
            return _not_found_response()
        resolved_root = report_root.resolve(strict=True)
        current = report_root
        for component in asset_parts:
            current = current / component
            identity = current.lstat()
            if _is_indirection(identity):
                return _not_found_response()
        resolved_path = path.resolve(strict=True)
        if resolved_path != resolved_root and resolved_root not in resolved_path.parents:
            return _not_found_response()
        if not stat.S_ISREG(path.stat().st_mode):
            return _not_found_response()
        body = path.read_bytes()
    except (OSError, RuntimeError, ValueError):
        return _not_found_response()
    return (
        HTTPStatus.OK,
        mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        body,
    )


def _is_indirection(identity: os.stat_result) -> bool:
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(identity.st_mode) or bool(
        getattr(identity, "st_file_attributes", 0) & reparse
    )


def _not_found_response() -> tuple[HTTPStatus, str, bytes]:
    return HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", b"Not found"


def _issue_list(value: object, empty: str) -> str:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return f"<p>{_e(empty)}</p>"
    items = []
    for issue in value:
        if isinstance(issue, Mapping):
            code = issue.get("code")
            message = issue.get("message")
            entity = issue.get("entity")
            entity_id = issue.get("id")
            reference = ":".join(
                str(item) for item in (entity, entity_id) if isinstance(item, str) and item
            )
            prefix = f"[{_e(reference)}] " if reference else ""
            items.append(f"<li>{prefix}{_e(message)} <code>{_e(code)}</code></li>")
        else:
            items.append(f"<li>{_e(issue)}</li>")
    return f"<ol>{''.join(items)}</ol>" if items else f"<p>{_e(empty)}</p>"


def _advice_panel(advice: dict | None) -> str:
    if advice is None:
        return "<p>Latest advice: none yet.</p>"
    findings = advice.get("findings", [])
    recommendations = advice.get("table_recommendations", [])
    finding_items = "".join(
        f"<li>{_e(item.get('category'))}: {_e(item.get('message'))}</li>"
        for item in findings[:5]
        if isinstance(item, Mapping)
    )
    rec_items = "".join(
        f"<li>{_e(item.get('workbook'))} {_e(item.get('row_id'))} {_e(item.get('field'))}</li>"
        for item in recommendations[:5]
        if isinstance(item, Mapping)
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


def _string_sequence(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item)


def _text(value: object, fallback: str) -> str:
    return value if isinstance(value, str) and value else fallback


def _e(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)
