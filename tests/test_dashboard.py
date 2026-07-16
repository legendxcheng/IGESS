import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import BoundedSemaphore, Event, Thread
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest

from igess import dashboard
from igess.authoring import AuthoringProject
from igess.authoring.change import ModelChange
from igess.authoring.response import CommandResponse
from igess.authoring.service import AuthoringService
from igess.authoring.templates import initialize_authoring_project
from igess.authoring.transactions import Transaction
from igess.dashboard import create_dashboard_context, render_dashboard_home
from igess.run_registry import RunRegistry
from igess.workflows import WorkflowService


CONFIG = "examples/shelldiver_v0/economy.yaml"
TABLES = "examples/shelldiver_v0/luban_exports"


def test_workflow_service_lints_runs_reports_and_lists_history(tmp_path):
    service = WorkflowService(project_root=".", runs_root=tmp_path / "runs")

    lint = service.lint(CONFIG, TABLES)
    record = service.run_scenario(CONFIG, TABLES, "day_1_progression")
    history = RunRegistry(tmp_path / "runs").list_runs()

    assert lint.ok
    assert record.status == "success"
    assert record.scenario_id == "day_1_progression"
    assert record.report_index.exists()
    assert record.output_dir.joinpath("timeline.json").exists()
    status = json.loads(record.status_path.read_text(encoding="utf-8"))
    assert status["status"] == "success"
    assert status["scenario_id"] == "day_1_progression"
    assert status["report_index"] == str(record.report_index)
    assert [item.run_id for item in history] == [record.run_id]


def test_workflow_service_records_failed_run_status(tmp_path):
    service = WorkflowService(project_root=".", runs_root=tmp_path / "runs")

    record = service.run_scenario(CONFIG, TABLES, "missing_scenario")

    assert record.status == "failed"
    assert "missing_scenario" in record.message
    status = json.loads(record.status_path.read_text(encoding="utf-8"))
    assert status["status"] == "failed"
    assert "missing_scenario" in status["message"]


def test_render_dashboard_home_lists_actions_and_history(tmp_path):
    service = WorkflowService(project_root=".", runs_root=tmp_path / "runs")
    record = service.run_scenario(CONFIG, TABLES, "day_1_progression")

    html = render_dashboard_home(service, CONFIG, TABLES)

    assert "IGESS Dashboard" in html
    assert "day_1_progression" in html
    assert record.run_id in html
    assert "Run Scenario" in html
    assert "Diagnostics" in html
    assert "Agent Analyst" in html
    assert "Latest advice" in html


def test_send_report_file_response_blocks_path_traversal(tmp_path):
    service = WorkflowService(project_root=".", runs_root=tmp_path / "runs")
    record = service.run_scenario(CONFIG, TABLES, "day_1_progression")
    secret = tmp_path / "runs" / "secret.txt"
    secret.write_text("outside-report", encoding="utf-8")

    status, content_type, body = dashboard.send_report_file_response(
        service,
        f"{record.run_id}/../secret.txt",
    )

    assert status == HTTPStatus.NOT_FOUND
    assert content_type == "text/plain; charset=utf-8"
    assert body == b"Not found"


def test_dashboard_serves_shared_report_assets(tmp_path):
    service = WorkflowService(project_root=".", runs_root=tmp_path / "runs")
    record = service.run_scenario(CONFIG, TABLES, "day_1_progression")

    for relative in [
        f"{record.run_id}/report_data.json",
        f"{record.run_id}/assets/report.js",
        f"{record.run_id}/assets/echarts.min.js",
    ]:
        status, content_type, body = dashboard.send_report_file_response(service, relative)
        assert status == HTTPStatus.OK
        assert content_type
        assert body


def test_cli_dashboard_help_exposes_local_server_options():
    result = subprocess.run(
        [sys.executable, "-m", "igess.cli", "dashboard", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "--project" in result.stdout
    assert "--host" in result.stdout
    assert "--port" in result.stdout


class _DashboardService:
    def __init__(self, tmp_path: Path):
        self.is_authoring = True
        self.calls: list[tuple[str, str]] = []
        report = tmp_path / "runs" / "smoke-1" / "report"
        report.mkdir(parents=True)
        (report / "index.html").write_text("smoke report", encoding="utf-8")
        self._runs = [
            SimpleNamespace(
                run_id="smoke-1",
                scenario_id="smoke",
                status="success",
                message="<probe complete>",
                kind="smoke",
                change_id="change-1",
                report_dir=report,
                report_index=report / "index.html",
            ),
            SimpleNamespace(
                run_id="formal-1",
                scenario_id="day<1",
                status="failed",
                message="<formal failed>",
                kind="formal",
                change_id=None,
                report_dir=tmp_path / "runs" / "formal-1" / "report",
                report_index=tmp_path / "runs" / "formal-1" / "report" / "index.html",
            ),
        ]

    def lint(self, config, tables):
        raise AssertionError("authoring dashboard must not lint committed exports")

    def model_status(self):
        return CommandResponse(
            "model.status",
            True,
            "status",
            "Model is runnable <now>",
            result={
                "model_digest": "sha256:" + "a" * 64,
                "structural_valid": True,
                "smoke_eligible": True,
                "state": "ready",
                "entity_counts": {"resource<script>": 2, "activity": 1},
                "missing_requirements": [
                    {"code": "first", "message": "First <missing>"},
                    {"code": "second", "message": "Second & missing"},
                ],
                "warnings": [
                    {"code": "recovered", "message": "Recovered <journal>"},
                    {"code": "exports_stale", "message": "Exports are stale & old"},
                ],
                "available_scenarios": ["smoke", "day<1"],
                "latest_smoke_run_id": "smoke-1",
            },
        )

    def latest_change(self):
        return {
            "timestamp": "2026-07-16T08:00:00Z",
            "outcome": "success",
            "change": {"entity": "resource", "id": "gold<script>"},
            "status": {"state": "ready"},
        }

    def list_runs(self):
        return list(self._runs)

    def latest_advice(self):
        return {"status": "ok", "summary": "Advice <safe>", "findings": []}

    def run_authoring_scenario(self, scenario: str):
        self.calls.append(("formal", scenario))
        return CommandResponse("model.simulate", True, "simulated", "done")

    def run_scenario(self, config, tables, scenario: str):
        self.calls.append(("legacy", scenario))

    def run_advice(self, config, tables, scenario: str):
        self.calls.append(("advice", scenario))


def test_authoring_dashboard_renders_read_only_observability_with_escaped_values(tmp_path):
    service = _DashboardService(tmp_path)

    body = render_dashboard_home(service, None, None)

    assert 'class="state-badge ready"' in body
    assert "resource&lt;script&gt;" in body
    assert "gold&lt;script&gt;" in body
    assert "day&lt;1" in body
    assert "<script>" not in body
    assert body.index("First &lt;missing&gt;") < body.index("Second &amp; missing")
    assert "Recovered &lt;journal&gt;" in body
    assert "Exports are stale &amp; old" in body
    assert "Latest applied rule" in body
    assert "Latest smoke" in body
    assert "kind-smoke" in body and "kind-formal" in body
    assert '/reports/smoke-1/index.html' in body
    assert '<select id="scenario" name="scenario">' in body
    assert '<option value="day&lt;1">day&lt;1</option>' in body
    assert 'action="/smoke" method="post"' in body
    assert 'action="/formal" method="post"' in body
    assert 'action="/advise" method="post"' in body
    assert 'type="hidden" name="_csrf"' in body
    assert 'method="get"' not in body.lower()
    assert "Run smoke scenario (formal)" in body


def test_dashboard_mutations_require_post_and_redirect_home(tmp_path):
    service = _DashboardService(tmp_path)
    token = "test-csrf-token"
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        dashboard._handler(service, None, None, csrf_token=token),
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    try:
        for path in ("/smoke", "/formal", "/run", "/advise"):
            connection.request("GET", path)
            response = connection.getresponse()
            response.read()
            assert response.status == HTTPStatus.METHOD_NOT_ALLOWED
        assert service.calls == []

        for path, scenario, expected in (
            ("/smoke", "ignored", ("formal", "smoke")),
            ("/formal", "day<1", ("formal", "day<1")),
            ("/advise", "day<1", ("advice", "day<1")),
        ):
            encoded = urlencode({"scenario": scenario, "_csrf": token})
            connection.request(
                "POST",
                path,
                encoded,
                {"Content-Type": "application/x-www-form-urlencoded"},
            )
            response = connection.getresponse()
            response.read()
            assert response.status == HTTPStatus.SEE_OTHER
            assert response.getheader("Location") == "/"
            assert service.calls[-1] == expected

        connection.request("GET", "/status")
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        assert response.status == HTTPStatus.OK
        assert payload["command"] == "model.status"
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_dashboard_post_rejects_csrf_origin_host_and_concurrent_mutations(tmp_path):
    service = _DashboardService(tmp_path)
    token = "test-csrf-token"
    guard = BoundedSemaphore(1)
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        dashboard._handler(
            service,
            None,
            None,
            csrf_token=token,
            mutation_guard=guard,
        ),
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def post(fields, headers=None, *, host=None):
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        encoded = urlencode(fields)
        request_headers = {"Content-Type": "application/x-www-form-urlencoded"}
        request_headers.update(headers or {})
        if host is None:
            connection.request("POST", "/formal", encoded, request_headers)
        else:
            connection.putrequest("POST", "/formal", skip_host=True)
            connection.putheader("Host", host)
            for key, value in request_headers.items():
                connection.putheader(key, value)
            connection.putheader("Content-Length", str(len(encoded.encode("ascii"))))
            connection.endheaders(encoded.encode("ascii"))
        response = connection.getresponse()
        response.read()
        status = response.status
        connection.close()
        return status

    try:
        assert post({"scenario": "smoke"}) == HTTPStatus.FORBIDDEN
        assert post({"scenario": "smoke", "_csrf": "wrong"}) == HTTPStatus.FORBIDDEN
        assert (
            post(
                {"scenario": "smoke", "_csrf": token},
                {"Origin": "http://evil.example"},
            )
            == HTTPStatus.FORBIDDEN
        )
        assert (
            post(
                {"scenario": "smoke", "_csrf": token},
                host=f"evil.example:{server.server_port}",
            )
            == HTTPStatus.FORBIDDEN
        )
        assert service.calls == []

        assert guard.acquire(blocking=False)
        try:
            assert (
                post({"scenario": "smoke", "_csrf": token})
                == HTTPStatus.TOO_MANY_REQUESTS
            )
        finally:
            guard.release()
        assert service.calls == []

        origin = f"http://127.0.0.1:{server.server_port}"
        assert (
            post(
                {"scenario": "smoke", "_csrf": token},
                {"Origin": origin},
            )
            == HTTPStatus.SEE_OTHER
        )
        assert service.calls == [("formal", "smoke")]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_dashboard_server_refuses_non_loopback_binding():
    with pytest.raises(ValueError, match="loopback"):
        dashboard.serve_dashboard(
            project=".",
            config=CONFIG,
            tables=TABLES,
            runs_root=None,
            host="0.0.0.0",
            port=8765,
        )


def test_dashboard_context_auto_discovers_authoring_and_preserves_legacy_overrides(tmp_path):
    root = initialize_authoring_project(tmp_path / "model")

    service, config, tables = create_dashboard_context(root, None, None, None)
    assert service.is_authoring
    assert config == root / "economy.yaml"
    assert tables is None
    assert service.model_status().command == "model.status"

    legacy, config, tables = create_dashboard_context(root, "custom.yaml", None, None)
    assert not legacy.is_authoring
    assert config == "custom.yaml"
    assert tables == "examples/shelldiver_v0/luban_exports"

    plain = tmp_path / "plain"
    plain.mkdir()
    legacy, config, tables = create_dashboard_context(plain, None, None, None)
    assert not legacy.is_authoring
    assert config == "examples/shelldiver_v0/economy.yaml"
    assert tables == "examples/shelldiver_v0/luban_exports"


def test_workflow_service_merges_authoring_and_legacy_run_history(tmp_path):
    root = initialize_authoring_project(tmp_path / "model")
    modern = RunRegistry(root / "runs")
    legacy = RunRegistry(root / ".igess" / "runs")

    def write(registry, run_id, message):
        run_dir = registry.runs_root / run_id
        registry.write_status(
            run_dir,
            status="success",
            scenario_id="smoke",
            message=message,
            output_dir=run_dir / "output",
            report_dir=run_dir / "report",
            report_index=run_dir / "report" / "index.html",
        )

    write(legacy, "duplicate", "legacy")
    write(legacy, "legacy-only", "legacy-only")
    write(modern, "duplicate", "modern")
    write(modern, "modern-only", "modern-only")

    service = WorkflowService(root)
    history = {record.run_id: record for record in service.list_runs()}

    assert set(history) == {"duplicate", "legacy-only", "modern-only"}
    assert history["duplicate"].message == "modern"


def test_workflow_service_authoring_facade_uses_injected_collaborators(tmp_path):
    root = initialize_authoring_project(tmp_path / "model")
    project = AuthoringProject.discover(root)
    status = CommandResponse("model.status", True, "status", "ready", result={"state": "ready"})

    class Authoring:
        def __init__(self):
            self.scenarios = []

        def status(self):
            return status

        def simulate(self, scenario):
            self.scenarios.append(scenario)
            return CommandResponse("model.simulate", True, "simulated", "done")

    class Changes:
        def latest(self):
            return {"change": {"entity": "resource", "id": "gold"}}

    authoring = Authoring()
    service = WorkflowService(
        root,
        authoring_project=project,
        authoring_service=authoring,
        registry=RunRegistry(root / "injected-runs"),
        change_store=Changes(),
    )

    assert service.model_status() is status
    assert service.latest_change()["change"]["id"] == "gold"
    assert service.run_authoring_scenario("day_1").ok
    assert authoring.scenarios == ["day_1"]


def test_custom_authoring_runs_root_is_shared_by_status_simulation_history_and_reports(
    tmp_path,
):
    root = initialize_authoring_project(tmp_path / "model")
    project = AuthoringProject.discover(root)
    custom_runs = tmp_path / "dashboard-runs"
    registry = RunRegistry(custom_runs)
    legacy = RunRegistry(root / ".igess" / "runs")
    legacy_dir = legacy.runs_root / "20260715T010203000000Z-legacy"
    legacy.write_status(
        legacy_dir,
        status="success",
        scenario_id="day_1",
        message="Legacy formal run",
        output_dir=legacy_dir / "output",
        report_dir=legacy_dir / "report",
        report_index=legacy_dir / "report" / "index.html",
    )
    smoke_dir = custom_runs / "20260716T010203000000Z-smoke-change-1"
    registry.write_status(
        smoke_dir,
        status="success",
        scenario_id="smoke",
        message="Automatic smoke complete",
        output_dir=smoke_dir / "output",
        report_dir=smoke_dir / "report",
        report_index=smoke_dir / "report" / "index.html",
        kind="smoke",
        change_id="change-1",
        model_digest=project.model_digest(),
    )

    service = WorkflowService(root, custom_runs)

    assert service.model_status().result["latest_smoke_run_id"] == smoke_dir.name
    response = service.run_authoring_scenario("smoke")
    assert response.ok
    assert response.result["kind"] == "formal"
    assert custom_runs.joinpath(response.result["run_id"]).is_dir()
    assert {record.run_id for record in service.list_runs()} == {
        legacy_dir.name,
        smoke_dir.name,
        response.result["run_id"],
    }
    report_status, content_type, body = dashboard.send_report_file_response(
        service,
        f"{response.result['run_id']}/index.html",
    )
    assert report_status == HTTPStatus.OK
    assert content_type == "text/html"
    assert body
    project_runs = root / "runs"
    assert not project_runs.exists() or list(project_runs.iterdir()) == []


def test_custom_authoring_service_registry_must_match_dashboard_registry(tmp_path):
    root = initialize_authoring_project(tmp_path / "model")
    custom_runs = tmp_path / "dashboard-runs"
    mismatched = AuthoringService(root)

    with pytest.raises(ValueError, match="registry"):
        WorkflowService(root, custom_runs, authoring_service=mismatched)

    project = AuthoringProject.discover(root)
    shared = RunRegistry(custom_runs, read_roots=project.read_run_roots())
    matching = AuthoringService(root, registry_factory=lambda _project: shared)
    service = WorkflowService(
        root,
        custom_runs,
        authoring_service=matching,
        registry=shared,
    )
    assert service.registry is shared


def test_injected_authoring_service_registry_factory_is_pinned_once(tmp_path):
    root = initialize_authoring_project(tmp_path / "model")
    first = RunRegistry(tmp_path / "first-runs")
    second = RunRegistry(tmp_path / "second-runs")
    calls = []

    def unstable(_project):
        calls.append(len(calls))
        return first if len(calls) == 1 else second

    injected = AuthoringService(root, registry_factory=unstable)
    service = WorkflowService(root, authoring_service=injected, registry=first)

    assert service.model_status().command == "model.status"
    response = service.run_authoring_scenario("smoke")
    assert response.ok
    assert first.runs_root.joinpath(response.result["run_id"]).is_dir()
    assert not second.runs_root.exists()
    assert calls == []


def test_authoring_advice_waits_for_apply_replace_and_reads_one_locked_snapshot(tmp_path):
    root = initialize_authoring_project(tmp_path / "model")
    writer_ready = Event()
    release_writer = Event()
    advice_started = Event()
    observed = {}

    def advice_runner(config, tables, _scenario, out):
        advice_started.set()
        observed["config"] = Path(config).read_text(encoding="utf-8")
        observed["resources"] = Path(tables, "resources.json").read_text(
            encoding="utf-8"
        )
        payload = {
            "status": "ok",
            "summary": "Snapshot advice",
            "findings": [],
            "table_recommendations": [],
        }
        Path(out).mkdir(parents=True, exist_ok=True)
        Path(out, "advice.json").write_text(json.dumps(payload), encoding="utf-8")
        return payload

    service = WorkflowService(root, advice_runner=advice_runner)

    def transaction_factory(project, change_id, digest):
        def checkpoint(name):
            if name.startswith("target:0:"):
                writer_ready.set()
                assert release_writer.wait(timeout=10)

        return Transaction(project, change_id, digest, checkpoint=checkpoint)

    writer_service = AuthoringService(
        root,
        id_factory=lambda: "writer-change",
        transaction_factory=transaction_factory,
    )
    change = ModelChange(
        1,
        "upsert",
        "resource",
        "gold",
        {"name": "Gold", "dimension": "currency"},
    )

    def writer():
        response = writer_service.apply(change)
        assert response.ok, response.to_payload()

    with ThreadPoolExecutor(max_workers=2) as executor:
        writer_future = executor.submit(writer)
        assert writer_ready.wait(timeout=10)
        advice_future = executor.submit(service.run_advice, None, None, "smoke")
        assert not advice_started.wait(timeout=0.25)
        release_writer.set()
        writer_future.result(timeout=30)
        record = advice_future.result(timeout=30)

    assert advice_started.is_set()
    assert "model:" in observed["config"]
    assert "gold" in observed["resources"]
    assert record.kind == "advice"
    assert record.model_digest == AuthoringProject.discover(root).model_digest()


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"status": "ok", "summary": "bad", "findings": None},
        {"status": "ok", "summary": "bad", "findings": "not-a-list"},
    ],
)
def test_latest_advice_rejects_malformed_or_wrong_schema_payloads(tmp_path, payload):
    registry = RunRegistry(tmp_path / "runs")
    run_dir = registry.runs_root / "20260716T010203000000Z-advice_day_1"
    advice_dir = run_dir / "advice"
    advice_dir.mkdir(parents=True)
    (advice_dir / "advice.json").write_text(json.dumps(payload), encoding="utf-8")
    registry.write_status(
        run_dir,
        status="success",
        scenario_id="day_1",
        message="Advice complete",
        output_dir=advice_dir / "run",
        report_dir=advice_dir / "report",
        report_index=advice_dir / "report" / "index.html",
        kind="advice",
        model_digest="sha256:" + "a" * 64,
    )
    service = WorkflowService(".", registry=registry, authoring=False)

    assert service.latest_advice() is None
    assert "Latest advice: none yet." in render_dashboard_home(service, CONFIG, TABLES)
    assert "Latest advice is unavailable." in dashboard._advice_panel(payload)


def test_latest_advice_is_bounded_and_does_not_follow_links(tmp_path):
    registry = RunRegistry(tmp_path / "runs")
    run_dir = registry.runs_root / "20260716T010203000000Z-advice_day_1"
    advice_dir = run_dir / "advice"
    advice_dir.mkdir(parents=True)
    path = advice_dir / "advice.json"
    oversized = {
        "status": "ok",
        "summary": "x" * (1024 * 1024),
        "findings": [],
    }
    path.write_text(json.dumps(oversized), encoding="utf-8")
    registry.write_status(
        run_dir,
        status="success",
        scenario_id="day_1",
        message="Advice complete",
        output_dir=advice_dir / "run",
        report_dir=advice_dir / "report",
        report_index=advice_dir / "report" / "index.html",
        kind="advice",
        model_digest="sha256:" + "a" * 64,
    )
    service = WorkflowService(".", registry=registry, authoring=False)
    assert service.latest_advice() is None

    path.unlink()
    outside = tmp_path / "outside-advice.json"
    outside.write_text(
        json.dumps({"status": "ok", "summary": "secret", "findings": []}),
        encoding="utf-8",
    )
    try:
        path.symlink_to(outside)
    except OSError:
        return
    assert service.latest_advice() is None


def test_dashboard_get_returns_stable_error_card_when_observability_raises(tmp_path):
    service = _DashboardService(tmp_path)

    def broken():
        raise RuntimeError("must not escape into the HTTP connection")

    service.latest_advice = broken

    body = render_dashboard_home(service, None, None)

    assert "Dashboard unavailable" in body
    assert "must not escape" not in body


def test_legacy_dashboard_advice_has_kind_and_canonical_model_digest(tmp_path):
    service = WorkflowService(".", runs_root=tmp_path / "runs", authoring=False)

    record = service.run_advice(CONFIG, TABLES, "day_1_progression")

    assert record.kind == "advice"
    assert record.version == 1
    assert record.run_id.endswith("-advice_day_1_progression")
    assert record.model_digest.startswith("sha256:")
    assert len(record.model_digest) == 71
    assert "kind-advice" in render_dashboard_home(service, CONFIG, TABLES)


def test_send_report_file_response_rejects_symlinked_assets(tmp_path):
    service = WorkflowService(project_root=".", runs_root=tmp_path / "runs")
    record = service.run_scenario(CONFIG, TABLES, "day_1_progression")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = record.report_dir / "linked.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        return

    status, _, body = dashboard.send_report_file_response(
        service,
        f"{record.run_id}/linked.txt",
    )

    assert status == HTTPStatus.NOT_FOUND
    assert body == b"Not found"


def test_report_reader_does_not_follow_file_swapped_after_validation(tmp_path):
    service = WorkflowService(project_root=".", runs_root=tmp_path / "runs")
    record = service.run_scenario(CONFIG, TABLES, "day_1_progression")
    target = record.report_dir / "report_data.json"
    outside = tmp_path / "outside-secret.json"
    outside.write_text('{"secret":"must-not-leak"}', encoding="utf-8")

    def replace_with_link():
        target.unlink()
        try:
            target.symlink_to(outside)
        except OSError:
            pytest.skip("symlink creation is unavailable")

    status, _, body = dashboard.send_report_file_response(
        service,
        f"{record.run_id}/report_data.json",
        _before_file_open=replace_with_link,
    )

    assert status == HTTPStatus.NOT_FOUND
    assert b"must-not-leak" not in body
