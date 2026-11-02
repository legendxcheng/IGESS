"""HTTP integration for the Fish skill client, using a bounded task double."""

import importlib.util
import json
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Event, Thread
import time
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest

from dashboard_fixtures import InlineTaskRunner
from igess import dashboard
from igess.dashboard_projects import discover_dashboard_projects
from test_dashboard import _DashboardService


SCRIPT = Path(__file__).resolve().parents[1] / ".agents/skills/fish_sim/scripts/run_dashboard.py"
spec = importlib.util.spec_from_file_location("fish_dashboard_client", SCRIPT)
client_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client_module)


@pytest.fixture
def running_dashboard(tmp_path, monkeypatch):
    project = tmp_path / "fish_source"
    service = _DashboardService(project)
    (project / "economy.yaml").write_text("{}", encoding="utf-8")
    entries = discover_dashboard_projects(project, runs_root=tmp_path / "custom-history")
    record = service._runs[0]
    record.engine_id = "fish_source"
    record.run_dir = record.report_dir.parent
    checkpoint = record.run_dir / "output/final_checkpoint.json"
    checkpoint.parent.mkdir()
    checkpoint.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(dashboard, "create_dashboard_context", lambda *a, **kw: (service, None, None))
    entered, release = Event(), Event()
    calls = []
    outcome = {"state": "success", "message": "done", "run_id": "test-result"}

    class Runner(InlineTaskRunner):
        def run(self, operation, scenario="", **options):
            if operation == "check":
                return super().run(operation, scenario)
            calls.append((operation, scenario, options))
            entered.set()
            assert release.wait(5)
            return dict(outcome)

    handler = dashboard._handler(None, None, None, projects=entries,
                                 restart_event=Event(), task_runner_factory=Runner)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = client_module.DashboardClient(f"http://127.0.0.1:{server.server_port}", project)
    assert client.prefix == "/p/" + entries[0].key
    # Initial project access starts the service's cached readiness check.
    deadline = time.monotonic() + 3
    while "name=\"scenario\"" not in client.get(client.url, json_response=False):
        assert time.monotonic() < deadline
        time.sleep(0.01)
    try:
        yield SimpleNamespace(client=client, calls=calls, entered=entered, release=release,
                              outcome=outcome, jobs=tmp_path / "receipts")
    finally:
        release.set()
        server.shutdown()
        handler.close_tasks()
        server.server_close()
        thread.join(5)


@pytest.mark.parametrize("state", ["success", "failed"])
def test_submission_runs_on_existing_service_and_status_is_read_only(running_dashboard, state):
    env = running_dashboard
    env.outcome["state"] = state
    result = env.client.submit("day<1", "smoke-1", env.jobs)
    assert result["state"] == "accepted" and result["ok"]
    assert json.loads(Path(result["receipt_path"]).read_text(encoding="utf-8")) == result
    assert "_csrf" not in json.dumps(result)
    assert env.entered.wait(1)
    assert env.client.status()["current_task"]["state"] == "running"
    with pytest.raises(ValueError, match="already has a running"):
        env.client.submit("smoke", None, env.jobs)
    env.release.set()
    deadline = time.monotonic() + 3
    while env.client.status()["current_task"]["state"] == "running":
        assert time.monotonic() < deadline
        time.sleep(0.01)
    current = env.client.status()
    assert current["ok"]  # HTTP success is independent of simulation success.
    assert current["current_task"]["state"] == state
    assert current["current_task"]["run_id"] == "test-result"
    assert env.calls == [("simulate", "day<1", {"resume_run_id": "smoke-1"})]


def test_preflight_rejects_unavailable_inputs_without_submitting(running_dashboard):
    env = running_dashboard
    with pytest.raises(ValueError, match="scenario unavailable"):
        env.client.submit("nonexistent", None, env.jobs)
    with pytest.raises(ValueError, match="Continuation run"):
        env.client.submit("smoke", "missing-run", env.jobs)
    missing = client_module.DashboardClient(env.client.server, env.jobs / "other-project")
    with pytest.raises(HTTPError) as exc:
        missing.submit("smoke", None, env.jobs)
    assert exc.value.code == 404
    assert env.calls == []
    assert not env.jobs.exists()


def test_admission_race_is_rejected_without_retry(running_dashboard, monkeypatch):
    env = running_dashboard
    monkeypatch.setattr(dashboard._DashboardRuntime, "submit", lambda *a, **kw: False)
    result = env.client.submit("smoke", None, env.jobs)
    assert result["state"] == "rejected" and not result["ok"]
    assert "429" in result["message"]
    assert env.calls == []


def test_lost_post_response_preserves_uncertainty_and_does_not_resubmit(running_dashboard):
    env = running_dashboard
    opener = env.client.opener

    class LostResponse:
        def open(self, request, **kwargs):
            if not isinstance(request, str) and request.get_method() == "POST":
                try:
                    opener.open(request, **kwargs)
                except HTTPError as exc:
                    assert exc.code == 303
                    exc.close()
                raise TimeoutError("response lost after acceptance")
            return opener.open(request, **kwargs)

    env.client.opener = LostResponse()
    result = env.client.submit("smoke", None, env.jobs)
    assert result["state"] == "submission_unknown" and not result["ok"]
    assert env.entered.wait(1)
    assert len(env.calls) == 1
    assert json.loads(Path(result["receipt_path"]).read_text(encoding="utf-8"))["state"] == "submission_unknown"


@pytest.mark.parametrize("server", ["https://127.0.0.1:8771", "http://example.com", "http://localhost/p/x/", "http://user@localhost"])
def test_only_explicit_local_origins_are_accepted(tmp_path, server):
    with pytest.raises(ValueError, match="local HTTP origin"):
        client_module.DashboardClient(server, tmp_path)


def test_unreachable_service_never_falls_back_to_cli(tmp_path, monkeypatch, capsys):
    def unavailable(*args, **kwargs):
        raise ConnectionRefusedError("service unavailable")

    monkeypatch.setattr(client_module.DashboardClient, "get", unavailable)
    assert client_module.main(["submit", "--scenario", "smoke", "--jobs-root", str(tmp_path)]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["state"] == "not_submitted"
    assert not list(tmp_path.iterdir())


def test_unsupported_cutoff_is_not_silently_ignored():
    with pytest.raises(SystemExit) as exc:
        client_module.main(["submit", "--scenario", "smoke", "--until-seconds", "2"])
    assert exc.value.code == 2
