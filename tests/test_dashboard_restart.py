from dashboard_fixtures import InlineTaskRunner
import json
import re
import socket
import subprocess
import time
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Event, Thread
from urllib.parse import urlencode

import pytest

from igess import dashboard, dashboard_process
from igess.authoring.response import CommandResponse
from igess.dashboard_projects import DashboardProject
from test_dashboard import _DashboardService


def request(port, path, data=None, headers=None, method=None):
    connection = HTTPConnection("127.0.0.1", port, timeout=3)
    try:
        connection.request(method or ("POST" if data is not None else "GET"), path,
                           urlencode(data) if data is not None else None, headers or {})
        response = connection.getresponse()
        return response.status, response.read().decode()
    finally:
        connection.close()


def wait_until(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            result = predicate()
            if result:
                return result
        except (OSError, ValueError):
            pass
        time.sleep(.03)
    raise AssertionError("Dashboard did not reach the expected state")


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    services = {name: _DashboardService(tmp_path / name) for name in ("alpha", "beta")}
    monkeypatch.setattr(dashboard, "create_dashboard_context",
                        lambda root, *args, **kwargs: (services[root.name], None, None))
    entries = [DashboardProject(name, name, tmp_path / name) for name in services]
    restart = Event()
    server = ThreadingHTTPServer(("127.0.0.1", 0), dashboard._handler(
        None, None, None, task_runner_factory=InlineTaskRunner, projects=entries, restart_event=restart))
    shutdown = server.shutdown
    # Keep serving after admission so rejected late requests can be asserted.
    server.shutdown = lambda: None
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_port
    for name in services:
        request(port, f"/p/{name}/")
        wait_until(lambda: not json.loads(request(port, f"/p/{name}/task")[1])["refreshing"])
    page = request(port, "/p/beta/")[1]
    token = re.search(r'id="confirm-restart-service"[^>]*data-token="([^"]+)"', page)[1]
    try:
        yield port, services, restart, {"_csrf": token, "confirm": "restart"}
    finally:
        shutdown()
        server.RequestHandlerClass.close_tasks()
        server.server_close()
        thread.join(5)


def test_restart_requires_post_confirmation_and_local_csrf(workspace):
    port, _, restart, form = workspace
    assert request(port, "/server/restart")[0] == 405
    assert request(port, "/server/restart", {"confirm": "restart"})[0] == 403
    assert request(port, "/server/restart", {"_csrf": form["_csrf"]})[0] == 400
    for headers in ({"Origin": "https://evil.example"}, {"Host": "evil.example"}):
        assert request(port, "/server/restart", form, headers)[0] == 403
    assert not restart.is_set()
    assert request(port, "/server/restart", form)[0] == 200
    assert restart.is_set()
    assert request(port, "/server/restart", form)[0] == 409
    assert request(port, "/p/alpha/formal", {})[0] == 503
    assert request(port, "/p/beta/refresh", {})[0] == 503
    assert json.loads(request(port, "/server/status")[1])["restarting"] is True


def test_restart_from_beta_preserves_running_alpha_task(workspace):
    port, services, restart, form = workspace
    entered, release = Event(), Event()

    def run(scenario):
        entered.set()
        assert release.wait(10)
        return CommandResponse("model.simulate", True, "done", "completed")

    services["alpha"].run_authoring_scenario = run
    page = request(port, "/p/alpha/")[1]
    token = re.search(r'name="_csrf" value="([^"]+)"', page)[1]
    try:
        assert request(port, "/p/alpha/formal", {"_csrf": token, "scenario": "smoke"})[0] == 303
        assert entered.wait(2)
        assert request(port, "/server/restart", form)[0] == 409
        assert not restart.is_set()
        assert json.loads(request(port, "/p/alpha/task")[1])["state"] == "running"
    finally:
        release.set()
    wait_until(lambda: json.loads(request(port, "/p/alpha/task")[1])["state"] == "success")
    wait_until(lambda: not json.loads(request(port, "/p/alpha/task")[1])["refreshing"])
    assert request(port, "/server/restart", form)[0] == 200


def test_restart_waits_for_model_refresh(workspace):
    port, services, restart, form = workspace
    entered, release = Event(), Event()
    original = services["alpha"].model_status

    def status():
        entered.set()
        assert release.wait(10)
        return original()

    services["alpha"].model_status = status
    page = request(port, "/p/alpha/")[1]
    token = re.search(r'name="_csrf" value="([^"]+)"', page)[1]
    try:
        assert request(port, "/p/alpha/refresh", {"_csrf": token})[0] == 303
        assert entered.wait(2)
        assert request(port, "/server/restart", form)[0] == 409
        assert not restart.is_set()
    finally:
        release.set()
    wait_until(lambda: not json.loads(request(port, "/p/alpha/task")[1])["refreshing"])
    assert request(port, "/server/restart", form)[0] == 200


def test_supervisor_restarts_real_process_and_keeps_launch_options(tmp_path, monkeypatch):
    repo = Path(__file__).resolve().parents[1]
    project = tmp_path / "workspace"
    project.mkdir()
    runs = tmp_path / "saved-runs"
    runs.mkdir()
    sentinel = runs / "keep.txt"
    sentinel.write_text("saved history")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    options = dict(project=project, config=repo / "examples/shelldiver_v0/economy.yaml",
                   tables=repo / "examples/shelldiver_v0/luban_exports", runs_root=runs,
                   host="127.0.0.1", port=port)
    processes, errors = [], []
    original = subprocess.Popen
    log = (tmp_path / "server.log").open("w", encoding="utf-8")

    def launch(*args, **kwargs):
        kwargs.update(stdout=log, stderr=log)
        process = original(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(dashboard_process.subprocess, "Popen", launch)

    def supervise():
        try:
            dashboard_process.supervise_dashboard(**options)
        except RuntimeError as error:
            errors.append(error)

    thread = Thread(target=supervise, daemon=True)
    thread.start()
    try:
        old = wait_until(lambda: json.loads(request(port, "/server/status")[1]))
        key = dashboard.discover_dashboard_projects(project, options["config"], options["tables"], runs)[0].key
        page_path = f"/p/{key}/"
        page = request(port, page_path)[1]
        wait_until(lambda: not json.loads(request(port, page_path + "task")[1])["refreshing"])
        form = {"_csrf": re.search(r'id="confirm-restart-service"[^>]*data-token="([^"]+)"', page)[1],
                "confirm": "restart"}
        assert request(port, "/server/restart", form)[0] == 200
        new = wait_until(lambda: (state if (state := json.loads(request(port, "/server/status")[1]))["instance_id"] != old["instance_id"] else None))
        assert not new["restarting"]
        assert len(processes) == 2
        assert processes[0].poll() == dashboard_process.RESTART_EXIT_CODE
        assert processes[0].pid != processes[1].pid
        assert processes[0].args == processes[1].args
        assert request(port, page_path)[0] == 200
        assert request(port, "/server/restart", form)[0] == 403  # Old credentials expire.
        assert sentinel.read_text() == "saved history"
        assert (tmp_path / "server.log").read_text(encoding="utf-8").count("IGESS dashboard running") == 2
    finally:
        if processes:
            processes[-1].terminate()
            processes[-1].wait(timeout=10)
        thread.join(10)
        log.close()
    assert not thread.is_alive()
    assert errors  # A crash/termination is surfaced, never a restart loop.
