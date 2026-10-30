from __future__ import annotations

import html
import ipaddress
import json
import mimetypes
import re
import secrets
from collections.abc import Mapping, Sequence
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from threading import BoundedSemaphore, Event, Lock, Thread
from time import monotonic
from urllib.parse import parse_qs, unquote, urlparse

from .dashboard_ui import dashboard_shell, restart_controls
from .dashboard_tasks import DashboardTaskRunner
from .dashboard_projects import discover_dashboard_projects
from .authoring.project import AuthoringProject
from .authoring.response import CommandResponse
from .workflows import WorkflowService, _read_bounded_relative_file


_SAMPLE_CONFIG = "examples/shelldiver_v0/economy.yaml"
_SAMPLE_TABLES = "examples/shelldiver_v0/luban_exports"
_MAX_FORM_BYTES = 64 * 1024
_MAX_REPORT_BYTES = 32 * 1024 * 1024
_MUTATION_PATHS = frozenset({"/smoke", "/formal", "/run", "/advise", "/refresh"})


def create_dashboard_context(
    project: str | Path,
    config: str | Path | None,
    tables: str | Path | None,
    runs_root: str | Path | None,
    *,
    strict_authoring: bool = False,
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
            if strict_authoring:
                raise
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
    *,
    csrf_token: str | None = None,
    status_response: CommandResponse | None = None,
    check_snapshot: dict | None = None,
) -> str:
    token = csrf_token or secrets.token_urlsafe(32)
    try:
        if status_response is None and service.is_authoring:
            status_response = service.model_status()
        runs = service.list_runs()
        advice = service.latest_advice()
        if status_response is not None:
            main_content = _authoring_content(
                service,
                status_response,
                runs,
                advice,
                token,
            )
        else:
            main_content = _legacy_content(
                service,
                config,
                tables,
                runs,
                advice,
                token,
                check_snapshot,
            )
        summary = '<div class="counts run-summary" data-view="overview">' + ''.join(
            f'<div><strong>{label}</strong>{count}</div>'
            for label, count in (
                ("Total runs", len(runs)),
                ("Successful", sum(getattr(run, "status", "") == "success" for run in runs)),
                ("Failed", sum(getattr(run, "status", "") == "failed" for run in runs)),
                ("Running", sum(getattr(run, "status", "") == "running" for run in runs)),
            )
        ) + '</div>'
        main_content = summary + main_content
    except Exception:  # noqa: BLE001 - GET must remain a stable observability boundary.
        main_content = (
            '    <section><h2>Dashboard unavailable</h2><p class="failed">'
            "Model observability data could not be loaded safely.</p></section>"
        )
    return dashboard_shell(
        main_content,
        str(getattr(service, "project_root", "Local project")),
        "Authoring project" if service.is_authoring else "Configuration project",
    )


def _authoring_content(
    service: WorkflowService,
    response: CommandResponse,
    runs: Sequence[object],
    advice: object,
    csrf_token: str,
) -> str:
    status = response.result
    state = _text(status.get("state"), "failed")
    counts = status.get("entity_counts")
    count_items = counts.items() if isinstance(counts, Mapping) else ()
    counts_html = "".join(
        f"<div><strong>{_e(name)}</strong>{_e(count)}</div>" for name, count in count_items
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
    resume_options = "".join(
        f'<option value="{_e(run.run_id)}">{_e(run.run_id)}</option>'
        for run in reversed(runs)
        if getattr(run, "status", "") == "success"
        and getattr(run, "engine_id", None) == "fish_source"
        and (Path(run.run_dir) / "output" / "final_checkpoint.json").is_file()
    )
    resume_control = (
        '<label for="resume-run">起点</label>'
        '<select id="resume-run" name="resume_run_id"><option value="">从新玩家开始</option>'
        + resume_options + '</select><p class="hint">选择历史结果可继续到目标天数。'
        '需保持数值表、策略和源码不变；报告只统计本次新增区间。</p>'
    ) if resume_options else ""
    return f"""    <div class="overview-grid" data-view="overview"><section>
      <h2>Model status</h2>
      <p><span class="state-badge {_e(state)}">{_e(state)}</span> {_e(response.message)}</p>
      <details><summary>Model identity &amp; status JSON</summary><p>Digest: <code>{_e(status.get('model_digest'))}</code></p>
      <a href="/status">View status JSON</a></details>
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
    </section></div>
    <section data-view="runs">
      <h2>Scenario actions</h2>
      <p>Manual scenario actions are recorded as <strong>formal</strong> runs. Automatic smoke records are created by successful rule application.</p>
      <div class="actions">
        <form action="/smoke" method="post">
          {_csrf_input(csrf_token)}
          <label>Quick validation</label><p>Run the smoke scenario as a formal run.</p>
          <button type="submit">Run smoke scenario (formal)</button>
        </form>
        <form action="/formal" method="post">
          {_csrf_input(csrf_token)}
          <label for="scenario">Formal scenario</label>
          <select id="scenario" name="scenario">{options}</select>
          {resume_control}
          <button type="submit" {"" if scenarios else "disabled data-unavailable"}>Run formal scenario</button>
        </form>

      </div>
    </section>
    {_history_panel(runs)}
    <section data-view="advice">
      <h2>Latest advice</h2>
      <p class="hint">Analyze a scenario and review recommendations before changing your tables.</p>
        <form action="/advise" method="post">
          {_csrf_input(csrf_token)}
          <label for="advice-scenario">Advice scenario</label>
          <select id="advice-scenario" name="scenario">{options}</select>
          <button type="submit" {"" if scenarios else "disabled data-unavailable"}>Run advice (advice)</button>
        </form>
      {_advice_panel(advice)}
    </section>"""


def _legacy_content(
    service: WorkflowService,
    config: str | Path | None,
    tables: str | Path | None,
    runs: Sequence[object],
    advice: object,
    csrf_token: str,
    check_snapshot: dict | None = None,
) -> str:
    from types import SimpleNamespace

    lint = (SimpleNamespace(**check_snapshot["status"]) if check_snapshot is not None
            else service.lint(config or _SAMPLE_CONFIG, tables or _SAMPLE_TABLES))
    try:
        if check_snapshot is not None and check_snapshot.get("scenario_error"):
            raise ValueError(check_snapshot["scenario_error"])
        scenarios = (check_snapshot["scenarios"] if check_snapshot is not None
                     else service.available_scenarios(config or _SAMPLE_CONFIG))
        scenario_hint = "" if scenarios else "No scenarios configured. Add a scenario to the selected configuration, then refresh the model snapshot."
    except Exception as error:  # noqa: BLE001 - keep diagnostics and history accessible.
        scenarios = ()
        scenario_hint = f"Could not load scenarios: {error}. Fix the configuration, then refresh the model snapshot."
    options = "".join(
        f'<option value="{_e(scenario)}">{_e(scenario)}</option>' for scenario in scenarios
    ) or '<option value="" disabled>No scenarios available</option>'
    disabled = "" if scenarios else "disabled data-unavailable"
    hint = f'<p class="hint">{_e(scenario_hint)}</p>' if scenario_hint else ""
    return f"""    <section data-view="overview">
      <h2>Diagnostics</h2>
      <p class="{'ok' if lint.ok else 'failed'}">{_e(lint.message)}</p>
      <p>Config: <code>{_e(config)}</code></p>
      <p>Tables: <code>{_e(tables)}</code></p>
    </section>
    <section data-view="runs">
      <h2>Run Scenario</h2>
      <form action="/formal" method="post">
        {_csrf_input(csrf_token)}
        <label for="scenario">Scenario</label>
        <select id="scenario" name="scenario">{options}</select>
        {hint}
        <button type="submit" {disabled}>Run formal scenario</button>
      </form>
    </section>
    <section data-view="advice">
      <h2>Agent Analyst</h2>
      <form action="/advise" method="post">
        {_csrf_input(csrf_token)}
        <label for="advice-scenario">Scenario</label>
        <select id="advice-scenario" name="scenario">{options}</select>
        {hint}
        <button type="submit" {disabled}>Run advice (advice)</button>
      </form>
      {_advice_panel(advice)}
    </section>
    {_history_panel(runs)}"""


def _history_panel(runs: Sequence[object]) -> str:
    rows = "\n".join(
        f'<tr data-run data-status="{_e(getattr(record, "status", ""))}" data-kind="{_e(getattr(record, "kind", "formal"))}">'
        f"<td><code>{_e(getattr(record, 'run_id', ''))}</code></td>"
        f"<td>{_e(getattr(record, 'scenario_id', ''))}</td>"
        f"<td><span class=\"kind kind-{_e(getattr(record, 'kind', 'formal'))}\">{_e(getattr(record, 'kind', 'formal'))}</span></td>"
        f'<td><span class="state-badge {_e(getattr(record, "status", ""))}">{_e(getattr(record, "status", ""))}</span></td>'
        f"<td>{_e(getattr(record, 'message', ''))}</td>"
        f"<td><a href=\"/reports/{_e(getattr(record, 'run_id', ''))}/index.html\">report</a>"
        + (f" · <a href=\"/diagnostics/{_e(getattr(record, 'run_id', ''))}\">diagnostic</a>" if getattr(record, 'status', '') == 'failed' else '')
        + "</td>"
        "</tr>"
        for record in sorted(runs, key=lambda item: getattr(item, 'run_id', ''), reverse=True)
    )
    if not rows:
        rows = '<tr><td colspan="6" class="empty-state"><strong>No runs yet.</strong>Choose a scenario above to create your first run.</td></tr>'
    return f"""    <section data-view="runs">
      <h2>Unified run history</h2>
      <p class="hint">Newest first · Formal runs, automatic smoke and advice share this history.</p>
      <div class="history-toolbar">
        <div class="search-field"><label for="history-search">Search runs</label><input type="search" id="history-search" placeholder="Run ID, scenario or message…"></div>
        <div><label for="history-status">Status</label><select id="history-status"><option value="">All statuses</option><option value="success">Success</option><option value="failed">Failed</option><option value="running">Running</option></select></div>
        <div><label for="history-kind">Kind</label><select id="history-kind"><option value="">All kinds</option><option value="formal">Formal</option><option value="smoke">Smoke</option><option value="advice">Advice</option></select></div>
        <button type="button" id="clear-filters">Clear filters</button>
      </div>
      <p id="history-count" class="hint" role="status">{len(runs)} runs</p>
      <div class="table-scroll" role="region" aria-label="Run history" tabindex="0"><table>
        <thead><tr><th>Run</th><th>Scenario</th><th>Kind</th><th>Status</th><th>Message</th><th>Report</th></tr></thead>
        <tbody>
{rows}
        </tbody>
      </table></div>
      <p id="history-no-match" class="empty-state" hidden>No matching runs. Try a different search or clear the filters.</p>
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
    if not _is_loopback_host(host):
        raise ValueError("Dashboard host must be a loopback address")
    from .dashboard_process import supervise_dashboard

    supervise_dashboard(project=project, config=config, tables=tables,
                        runs_root=runs_root, host=host, port=port)



def _serve_dashboard_worker(*, project, config, tables, runs_root, host, port):
    if not _is_loopback_host(host):
        raise ValueError("Dashboard host must be a loopback address")
    restart = Event()
    projects = discover_dashboard_projects(project, config, tables, runs_root)
    handler = _handler(None, None, None, projects=projects, restart_event=restart)
    server = ThreadingHTTPServer((host, port), handler)
    print(f"IGESS dashboard running at http://{host}:{server.server_port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        handler.close_tasks()
        server.server_close()
    return restart.is_set()


class _DashboardRuntime:
    """Keep expensive workflow reads and writes outside HTTP request threads.

    Snapshots are explicitly cached; polling never starts a model readiness check.
    The mutation guard stays owned by the worker until execution has finished.
    """

    def __init__(self, service, config, tables, token, guard, task_runner=None):
        self.service, self.config, self.tables = service, config, tables
        self.token, self.guard = token, guard
        self.task_runner = task_runner or DashboardTaskRunner(service, config, tables)
        self.lock = Lock()
        self.page = dashboard_shell('<section><h2>Checking model in background…</h2><p class="hint">You can inspect task status while the model check completes.</p></section>', str(getattr(service, 'project_root', 'Local project')), 'Loading project')
        self.status = {"command": "model.status", "ok": False, "message": "Checking model in background"}
        self.task = {"state": "idle", "message": "No task submitted in this server session."}
        self.started = None
        self.refreshing = False
        self.refresh_pending = False
        self.revision = 0
        self.stopping = False
        self.workers = set()
        self.refresh()

    def _start_worker(self, target, *args):
        def work():
            try:
                target(*args)
            finally:
                with self.lock:
                    self.workers.discard(thread)

        thread = Thread(target=work, daemon=True)
        with self.lock:
            if self.stopping:
                raise RuntimeError("Dashboard is stopping")
            self.workers.add(thread)
            try:
                thread.start()
            except BaseException:
                self.workers.discard(thread)
                raise

    def close(self):
        with self.lock:
            self.stopping = True
            workers = list(self.workers)
        self.task_runner.close()
        for worker in workers:
            worker.join(timeout=15)

    def snapshot(self):
        with self.lock:
            elapsed = self.task.get("duration_seconds", round(monotonic() - self.started, 1) if self.started else 0)
            return {**self.task, "elapsed_seconds": elapsed,
                    "refreshing": self.refreshing, "revision": self.revision}

    def refresh(self):
        with self.lock:
            if self.stopping:
                return
            if self.refreshing:
                self.refresh_pending = True
                return
            self.refreshing = True
        self._start_worker(self._refresh)

    def _refresh(self):
        try:
            check = self.task_runner.run("check")
            payload = check.get("authoring")
            response = CommandResponse(**{key: value for key, value in payload.items() if key != "schema_version"}) if payload else None
            page = render_dashboard_home(self.service, self.config, self.tables,
                                         csrf_token=self.token, status_response=response, check_snapshot=check)
            status = check["status"]
        except Exception as error:  # noqa: BLE001 - retain a visible refresh error.
            status = {"ok": False, "message": str(error)}
            page = dashboard_shell('<section><h2>Model check failed</h2><p class="failed">' + _e(error) + '</p></section>', str(getattr(self.service, 'project_root', 'Local project')), 'Project unavailable')
        with self.lock:
            self.page, self.status = page, status
            self.revision += 1
            pending = self.refresh_pending
            self.refresh_pending = False
            self.refreshing = pending
        if pending:
            self._refresh()

    def submit(self, path, scenario, *, resume_run_id=None):
        if not self.guard.acquire(blocking=False):
            return False
        with self.lock:
            self.started = monotonic()
            message = "Task accepted; executing workflow (including any project lock wait)."
            self.task = {"state": "running", "message": message,
                         "scenario": scenario, "action": path}
        try:
            self._start_worker(self._execute, path, scenario, resume_run_id)
        except Exception as error:
            with self.lock:
                self.task = {"state": "failed", "message": str(error)}
            self.guard.release()
        return True

    def _execute(self, path, scenario, resume_run_id=None):
        outcome = {"state": "failed", "message": "Worker interrupted; check run history before retrying."}
        try:
            options = {"resume_run_id": resume_run_id} if resume_run_id else {}
            outcome = self.task_runner.run("advise" if path == "/advise" else "simulate", scenario, **options)
            diagnostic_id = outcome.get("diagnostic", {}).get("details", {}).get("diagnostic_id")
            if outcome["state"] == "failed" and isinstance(diagnostic_id, str):
                try:
                    diagnostic = _read_diagnostic(self.service, diagnostic_id)
                    error = diagnostic.get("primary_error", {})
                    summary = str(error.get("message", ""))
                    if summary:
                        outcome["message"] += "\n" + str(error.get("error_type", "Error")) + ": " + summary[:2000]
                except (OSError, RuntimeError, ValueError, AttributeError):
                    pass  # The workflow failure and diagnostic identifier remain visible.
        except Exception as error:  # noqa: BLE001 - expose exceptions as task failures.
            outcome = {"state": "failed", "message": f"{type(error).__name__}: {error}"}
        finally:
            try:
                self.refresh()
            finally:
                with self.lock:
                    self.task.update(outcome)
                    self.task["duration_seconds"] = round(monotonic() - self.started, 1)
                    self.guard.release()

    def home(self):
        task = self.snapshot()
        with self.lock:
            page = self.page
        panel = ('<section id="task-panel" aria-live="polite"><h2>Current task</h2>'
                 '<p id="task-state" class="' + _e(task["state"]) + '">' + _e(task["state"]) + '</p><p id="task-message" style="white-space:pre-wrap">' + _e(task["message"]) + '</p>'
                 '<p id="task-time"></p><a href="/task" target="_blank">Task details / diagnostics</a>'
                 '<p id="connection-state"></p>'
                 '<form action="/refresh" method="post">' + _csrf_input(self.token) +
                 '<button type="submit">Refresh model snapshot</button></form>')
        diagnostic_id = task.get("diagnostic", {}).get("details", {}).get("diagnostic_id")
        if isinstance(diagnostic_id, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", diagnostic_id):
            panel += '<p><a href="/diagnostics/' + diagnostic_id + '">Open failure diagnostic</a></p>'
        process_log = task.get("process_log")
        if isinstance(process_log, str) and re.fullmatch(r"task-log-[a-f0-9]{32}", process_log):
            panel += '<p><a href="/diagnostics/' + process_log + '">Open task output</a></p>'
        if task.get("log_warning"):
            panel += '<p>' + _e(task["log_warning"]) + '</p>'
        if task.get("state") == "success" and task.get("run_id"):
            panel += '<p><a href="/reports/' + _e(task['run_id']) + '/index.html">Open completed report</a></p>'
        panel += '</section>'
        script = """<script>
const revision = REVISION;
let previousState = STATE;
function displayTask(t) {
  document.querySelector('#task-state').textContent = t.state === 'idle' ? 'Ready for a new task' : t.state;
  document.querySelector('#task-state').className = t.state;
  document.querySelector('#task-message').textContent = t.message;
  document.querySelector('#task-time').textContent = 'Elapsed: ' + (t.duration_seconds ?? t.elapsed_seconds) + ' s' + (t.refreshing ? ' — refreshing model snapshot in background' : ' — model snapshot is cached');
  document.querySelectorAll('button[type=submit], [data-mutation]').forEach(b => b.disabled = t.state === 'running' || b.hasAttribute('data-unavailable') || b.hasAttribute('data-empty-history'));
}
document.querySelectorAll('form').forEach(f => f.addEventListener('submit', event => {
  if (event.defaultPrevented) return;
  f.action = new URL(f.action).pathname + location.hash;
  document.querySelector('#task-message').textContent = 'Submitting task…';
  document.querySelectorAll('button[type=submit]').forEach(b => b.disabled = true);
}));
async function poll() {
  if (window.dashboardRestarting) { setTimeout(poll, 1000); return; }
  try {
    const r = await fetch('/task', {cache: 'no-store', signal: AbortSignal.timeout(4000)});
    if (!r.ok) throw Error('HTTP ' + r.status);
    const t = await r.json();
    if (window.dashboardRestarting) { setTimeout(poll, 1000); return; }
    const serverInstance = document.querySelector('#restart-service')?.dataset.instance;
    if (serverInstance && t.instance_id && serverInstance !== t.instance_id) { location.reload(); return; }
    document.querySelector('#connection-state').textContent = '';
    displayTask(t);
    if (t.revision !== revision || (previousState === 'running' && t.state !== 'running')) { location.reload(); return; }
    previousState = t.state;
  } catch (e) { document.querySelector('#connection-state').textContent = 'Cannot reach dashboard. Task outcome is unknown; do not resubmit. ' + e.message; }
  setTimeout(poll, 1000);
}
displayTask(INITIAL);
poll();
</script>"""
        # Escape JSON for script context, independently of HTML text escaping.
        script = script.replace('REVISION', str(task['revision'])).replace('STATE', json.dumps(task['state']))
        script = script.replace('INITIAL', json.dumps(task).replace('<', '\\u003c'))
        if '<div id="task-slot"></div>' in page:
            page = page.replace('<div id="task-slot"></div>', panel)
        else:
            page = page.replace('<h1>IGESS Dashboard</h1>', '<h1>IGESS Dashboard</h1>' + panel)
        return page.replace('</body>', script + '</body>')


def _read_diagnostic(service, identifier):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", identifier):
        raise ValueError("Invalid diagnostic identifier")
    body = _read_bounded_relative_file(
        Path(service.project_root), (".igess", "diagnostics", identifier + ".json"),
        max_bytes=_MAX_REPORT_BYTES,
    )
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("Invalid diagnostic")
    return payload


def _handler(
    service: WorkflowService,
    config: str | Path | None,
    tables: str | Path | None,
    *,
    csrf_token: str | None = None,
    mutation_guard: BoundedSemaphore | None = None,
    projects=None,
    restart_event=None,
    task_runner_factory=DashboardTaskRunner,
):
    token = csrf_token or secrets.token_urlsafe(32)
    guard = mutation_guard or BoundedSemaphore(1)
    runtime = (_DashboardRuntime(service, config, tables, token, guard,
                                 task_runner_factory(service, config, tables)) if projects is None else None)
    catalog = {entry.key: entry for entry in projects or ()}
    runtimes = {}
    runtime_lock = Lock()
    restart_requested = False
    instance_id = secrets.token_urlsafe(24)
    server_token = secrets.token_urlsafe(32)

    class DashboardHandler(BaseHTTPRequestHandler):
        @staticmethod
        def close_tasks():
            nonlocal restart_requested
            with runtime_lock:
                restart_requested = True
                active = list(runtimes.values()) if catalog else [runtime]
            for item in active:
                item.close()

        def _select_project(self):
            path = urlparse(self.path).path
            self.prefix = ""
            self.project_key = None
            if not catalog:
                self.runtime = runtime
                return path
            if path == "/":
                self.send_response(HTTPStatus.SEE_OTHER)
                self.send_header("Location", "/p/" + next(iter(catalog)) + "/")
                self.end_headers()
                return None
            match = re.fullmatch(r"/p/([a-z0-9-]+)(/.*)?", path)
            if match is None or match[1] not in catalog:
                self.send_error(HTTPStatus.NOT_FOUND, "Unknown dashboard project")
                return None
            key = match[1]
            self.prefix, self.project_key = "/p/" + key, key
            if match[2] is None:
                self.send_response(HTTPStatus.SEE_OTHER)
                self.send_header("Location", self.prefix + "/")
                self.end_headers()
                return None
            with runtime_lock:
                if restart_requested:
                    self.send_error(HTTPStatus.SERVICE_UNAVAILABLE, "Dashboard is restarting")
                    return None
                if key not in runtimes:
                    entry = catalog[key]
                    try:
                        context = create_dashboard_context(
                            entry.root, entry.config, entry.tables, entry.runs_root,
                            strict_authoring=entry.config is None and entry.tables is None,
                        )
                    except Exception as error:  # noqa: BLE001 - retain the project switcher on failure.
                        self._send_html(self._mount_page(dashboard_shell(
                            '<section><h2>Project unavailable</h2><p class="failed">' + _e(error) +
                            '</p><p>Fix the project files and reload, or select another project.</p></section>',
                            str(entry.root), 'Project unavailable',
                        )))
                        return None
                    runtimes[key] = _DashboardRuntime(*context, secrets.token_urlsafe(32), BoundedSemaphore(1),
                                                      task_runner_factory(*context))
                self.runtime = runtimes[key]
            return match[2]

        def _home(self):
            return self._mount_page(self.runtime.home())

        def _mount_page(self, page):
            if restart_event is not None:
                page = page.replace('<!-- server-controls -->', restart_controls(server_token, instance_id))
            if not catalog:
                return page
            # Only known application routes are mounted; report-relative assets
            # keep resolving within their own project-qualified report directory.
            for route in ("status", "task", "reports/", "diagnostics/", "refresh", "smoke", "formal", "run", "advise"):
                page = page.replace('href="/' + route, 'href="' + self.prefix + '/' + route)
                page = page.replace('action="/' + route, 'action="' + self.prefix + '/' + route)
            page = page.replace("fetch('/task'", "fetch('" + self.prefix + "/task'")
            options = ''.join(
                '<option value="/p/' + key + '/"' + (' selected' if key == self.project_key else '') + '>' + _e(entry.label) + '</option>'
                for key, entry in catalog.items()
            )
            picker = '<label for="project-picker">Project</label><select id="project-picker" aria-label="Project">' + options + '</select>'
            page = page.replace('<!-- project-picker -->', picker)
            return page

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler API.
            if urlparse(self.path).path == "/server/status":
                self._send_json({"instance_id": instance_id, "restarting": restart_requested})
                return
            if urlparse(self.path).path == "/server/restart":
                self.send_response(HTTPStatus.METHOD_NOT_ALLOWED)
                self.send_header("Allow", "POST")
                self.end_headers()
                return
            path = self._select_project()
            if path is None:
                return
            parsed = urlparse(path)
            if parsed.path == "/":
                self._send_html(self._home())
                return
            if parsed.path == "/task":
                self._send_json({**self.runtime.snapshot(), "instance_id": instance_id})
                return
            if parsed.path.startswith("/diagnostics/"):
                identifier = parsed.path.removeprefix("/diagnostics/")
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", identifier):
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                try:
                    self._send_json(_read_diagnostic(self.runtime.service, identifier))
                except (OSError, RuntimeError, ValueError):
                    self.send_error(HTTPStatus.NOT_FOUND, "No saved diagnostic for this run")
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
            if urlparse(self.path).path == "/server/restart":
                self._restart()
                return
            # Serialize admission with the workspace-wide restart check.
            with runtime_lock:
                if restart_requested:
                    self.send_error(HTTPStatus.SERVICE_UNAVAILABLE, "Dashboard is restarting")
                    return
            self._post_project()

        def _restart(self):
            nonlocal restart_requested
            if restart_event is None:
                self.send_error(HTTPStatus.NOT_IMPLEMENTED, "Restart requires the Dashboard launcher")
                return
            try:
                form = self._read_form()
            except (UnicodeError, ValueError):
                self.send_error(HTTPStatus.BAD_REQUEST)
                return
            if (not self._host_is_local() or not self._origin_is_same()
                    or not secrets.compare_digest(form.get("_csrf", [""])[0], server_token)):
                self.send_error(HTTPStatus.FORBIDDEN)
                return
            if form.get("confirm", [""])[0] != "restart":
                self.send_error(HTTPStatus.BAD_REQUEST, "Confirm the service restart first")
                return
            with runtime_lock:
                if restart_requested:
                    self.send_error(HTTPStatus.CONFLICT, "Restart already requested")
                    return
                active = list(runtimes.values()) if catalog else [runtime]
                acquired = []
                try:
                    for item in active:
                        if not item.guard.acquire(blocking=False):
                            self.send_error(HTTPStatus.CONFLICT, "A project task is running. Wait for it to finish.")
                            return
                        acquired.append(item.guard)
                        if item.snapshot()["refreshing"]:
                            self.send_error(HTTPStatus.CONFLICT, "A model check is running. Wait for it to finish.")
                            return
                    restart_requested = True
                    restart_event.set()
                finally:
                    for held in acquired:
                        held.release()
            try:
                self._send_json({"instance_id": instance_id, "restarting": True})
            finally:
                # shutdown must run outside serve_forever, after replying to the browser.
                Thread(target=self.server.shutdown, daemon=True).start()

        def _submit(self, *args, **kwargs):
            with runtime_lock:
                return not restart_requested and self.runtime.submit(*args, **kwargs)

        def _post_project(self):
            path = self._select_project()
            if path is None:
                return
            parsed = urlparse(path)
            if parsed.path not in _MUTATION_PATHS:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            try:
                form = self._read_form()
            except (UnicodeError, ValueError):
                self.send_error(HTTPStatus.BAD_REQUEST)
                return
            supplied_token = form.get("_csrf", [""])[0]
            if (
                not self._host_is_local()
                or not self._origin_is_same()
                or not secrets.compare_digest(supplied_token, self.runtime.token)
            ):
                self.send_error(HTTPStatus.FORBIDDEN)
                return
            if parsed.path == "/refresh":
                with runtime_lock:
                    if restart_requested:
                        self.send_error(HTTPStatus.SERVICE_UNAVAILABLE, "Dashboard is restarting")
                        return
                    self.runtime.refresh()
                self.send_response(HTTPStatus.SEE_OTHER)
                self.send_header("Location", self.prefix + "/")
                self.end_headers()
                return
            scenario = "smoke" if parsed.path == "/smoke" else form.get("scenario", ["day_1_progression"])[0]
            resume_run_id = form.get("resume_run_id", [""])[0]
            if resume_run_id and (parsed.path not in {"/formal", "/run"}
                                  or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", resume_run_id) is None):
                self.send_error(HTTPStatus.BAD_REQUEST, "Invalid continuation run")
                return
            options = {"resume_run_id": resume_run_id} if resume_run_id else {}
            if not self._submit(parsed.path, scenario, **options):
                self.send_error(HTTPStatus.TOO_MANY_REQUESTS)
                return
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", self.prefix + "/")
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

        def _host_is_local(self) -> bool:
            return _valid_local_authority(
                self.headers.get("Host"),
                self.server.server_port,
            )

        def _origin_is_same(self) -> bool:
            origin = self.headers.get("Origin")
            if origin is None:
                return True
            parsed = urlparse(origin)
            return (
                parsed.scheme == "http"
                and not parsed.path.strip("/")
                and not parsed.params
                and not parsed.query
                and not parsed.fragment
                and _valid_local_authority(parsed.netloc, self.server.server_port)
                and parsed.netloc.casefold()
                == (self.headers.get("Host") or "").casefold()
            )

        def _send_status(self) -> None:
            with self.runtime.lock:
                payload = {**self.runtime.status, "cached": True, "refreshing": self.runtime.refreshing}
            self._send_json(payload)

        def _send_json(self, payload) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Cache-Control", "no-store")
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
            status, content_type, body = send_report_file_response(self.runtime.service, relative)
            self.send_response(int(status))
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return DashboardHandler


def send_report_file_response(
    service: WorkflowService,
    relative: str,
    *,
    _before_file_open=None,
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
    try:
        body = _read_bounded_relative_file(
            report_root,
            tuple(asset_parts),
            max_bytes=_MAX_REPORT_BYTES,
            before_file_open=_before_file_open,
        )
    except (OSError, RuntimeError, ValueError):
        return _not_found_response()
    path = Path(asset_parts[-1])
    return (
        HTTPStatus.OK,
        mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        body,
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


def _advice_panel(advice: object) -> str:
    if advice is None:
        return "<p>Latest advice: none yet.</p>"
    if not isinstance(advice, Mapping):
        return '<p class="failed">Latest advice is unavailable.</p>'
    status = advice.get("status")
    summary = advice.get("summary")
    findings = advice.get("findings", [])
    recommendations = advice.get("table_recommendations", [])
    if (
        not isinstance(status, str)
        or not status
        or not isinstance(summary, str)
        or not summary
        or not isinstance(findings, Sequence)
        or isinstance(findings, (str, bytes, bytearray))
        or not isinstance(recommendations, Sequence)
        or isinstance(recommendations, (str, bytes, bytearray))
        or any(not isinstance(item, Mapping) for item in findings)
        or any(not isinstance(item, Mapping) for item in recommendations)
    ):
        return '<p class="failed">Latest advice is unavailable.</p>'
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
        f"<p>Latest advice: <code>{_e(status)}</code></p>"
        f"<p>{_e(summary)}</p>"
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


def _csrf_input(token: str) -> str:
    return f'<input type="hidden" name="_csrf" value="{_e(token)}">'


def _is_loopback_host(host: str) -> bool:
    if host.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _valid_local_authority(authority: str | None, port: int) -> bool:
    if not isinstance(authority, str) or not authority:
        return False
    parsed = urlparse(f"//{authority}")
    try:
        parsed_port = parsed.port
    except ValueError:
        return False
    return (
        parsed.username is None
        and parsed.password is None
        and parsed_port == port
        and parsed.hostname is not None
        and _is_loopback_host(parsed.hostname)
    )
