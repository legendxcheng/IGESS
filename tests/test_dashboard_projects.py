import re
import time
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Event, Thread
from urllib.parse import urlencode

from igess import dashboard
from igess.authoring.response import CommandResponse
from igess.dashboard_projects import DashboardProject, discover_dashboard_projects
from test_dashboard import _DashboardService


def test_catalog_discovers_projects_and_examples_but_excludes_retired_fish(tmp_path):
    for name in ("projects/fish", "projects/fish_source", "examples/sample"):
        root = tmp_path / name
        root.mkdir(parents=True)
        (root / "economy.yaml").write_text("scenarios: {}")
        (root / "luban_exports").mkdir()
    (tmp_path / "projects/fish_source/Datas").mkdir()
    entries = discover_dashboard_projects(tmp_path, runs_root=tmp_path / "history")
    assert [entry.root.name for entry in entries] == ["fish_source", "sample"]
    assert entries[0].config is None  # Keep authoring semantics.
    assert entries[1].config == tmp_path / "examples/sample/economy.yaml"
    assert len({entry.runs_root for entry in entries}) == 2
    assert [e.key for e in discover_dashboard_projects(tmp_path)] == [e.key for e in entries]
    selected = discover_dashboard_projects(tmp_path / "examples/sample")
    assert selected[0].root.name == "sample"
    assert len(selected) == 2


def test_invalid_authoring_project_does_not_fall_back_to_sample(tmp_path):
    root = tmp_path / "broken"
    root.mkdir()
    (root / "Datas").mkdir()
    (root / "economy.yaml").write_text("scenarios: {}")
    entries = discover_dashboard_projects(root)
    server = ThreadingHTTPServer(("127.0.0.1", 0), dashboard._handler(None, None, None, projects=entries))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=2)
    try:
        connection.request("GET", f"/p/{entries[0].key}/")
        response = connection.getresponse()
        body = response.read().decode()
        assert "Project unavailable" in body
        assert 'id="project-picker"' in body
        assert 'action="/formal"' not in body
        assert "day_1_progression" not in body
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(5)


def test_project_routes_isolate_tasks_tokens_reports_and_lazy_status(tmp_path, monkeypatch):
    services = {}
    entries = []
    for name in ("alpha", "beta"):
        root = tmp_path / name
        service = _DashboardService(root)
        service.project_root = root
        service._runs[0].report_index.write_text(name, encoding="utf-8")
        services[name] = service
        entries.append(DashboardProject(name, name, root))
    created = []

    def context(root, config, tables, runs_root, **kwargs):
        created.append(root.name)
        return services[root.name], None, None

    monkeypatch.setattr(dashboard, "create_dashboard_context", context)
    entered, release = Event(), Event()

    def slow_run(scenario):
        services["alpha"].calls.append(("formal", scenario))
        entered.set()
        assert release.wait(5)
        return CommandResponse("model.simulate", True, "done", "alpha finished")

    services["alpha"].run_authoring_scenario = slow_run
    server = ThreadingHTTPServer(("127.0.0.1", 0), dashboard._handler(None, None, None, projects=entries))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=2)

    def request(path, method="GET", data=None):
        connection.request(method, path, urlencode(data) if data else None)
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read().decode()

    try:
        assert created == []
        status, headers, _ = request("/")
        assert status == 303 and headers["Location"] == "/p/alpha/"
        status, _, body = request("/p/alpha/")
        assert status == 200 and created == ["alpha"]
        assert 'id="project-picker"' in body
        assert 'fetch(\'/p/alpha/task\'' in body
        token_a = re.search(r'name="_csrf" value="([^"]+)"', body)[1]
        status, headers, _ = request("/p/alpha/formal", "POST", {"_csrf": token_a, "scenario": "alpha-day"})
        assert status == 303 and headers["Location"] == "/p/alpha/"
        assert entered.wait(1)
        status, _, body = request("/p/beta/")
        token_b = re.search(r'name="_csrf" value="([^"]+)"', body)[1]
        assert token_a != token_b
        assert '"state": "idle"' in request("/p/beta/task")[2]
        assert '"state": "running"' in request("/p/alpha/task")[2]
        assert request("/p/beta/formal", "POST", {"_csrf": token_a})[0] == 403
        assert services["beta"].calls == []
        for name in ("alpha", "beta"):
            assert request(f"/p/{name}/reports/smoke-1/index.html")[2] == name
        assert request("/p/missing/task")[0] == 404
        assert request("/p/%2e%2e/task")[0] == 404
        assert request("/task")[0] == 404
        release.set()
        deadline = time.monotonic() + 2
        while '"state": "running"' in request("/p/alpha/task")[2] and time.monotonic() < deadline:
            time.sleep(.01)
        assert "alpha finished" in request("/p/alpha/task")[2]
        assert "alpha finished" not in request("/p/beta/task")[2]
        assert services["alpha"].calls == [("formal", "alpha-day")]
        assert created == ["alpha", "beta"]
    finally:
        release.set()
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(5)
