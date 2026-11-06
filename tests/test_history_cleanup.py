from dashboard_fixtures import InlineTaskRunner
import json
import re
import time
from http import HTTPStatus
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from threading import BoundedSemaphore, Thread
from urllib.parse import urlencode

import pytest

from igess import dashboard, run_registry
from igess.dashboard_projects import DashboardProject
from igess.run_registry import RunRegistry
from igess.workflows import WorkflowService


CONFIG = "examples/shelldiver_v0/economy.yaml"
TABLES = "examples/shelldiver_v0/luban_exports"


def _record(registry, name, *, kind="formal", status="success"):
    run = registry.runs_root / name
    record = registry.write_status(
        run, status=status, scenario_id="day_1", message="test history",
        kind=kind, change_id="change-1" if kind == "smoke" else None,
        model_digest="sha256:" + "a" * 64,
        output_dir=run / "output", report_dir=run / "report",
        report_index=run / "report" / "index.html",
    )
    record.report_dir.mkdir()
    record.report_index.write_text(name, encoding="utf-8")
    record.output_dir.mkdir()
    (record.output_dir / "timeline.json").write_text("[]", encoding="utf-8")
    return record


def test_clear_history_covers_kinds_legacy_duplicates_and_preserves_other_data(tmp_path):
    modern = RunRegistry(tmp_path / "runs")
    legacy = RunRegistry(tmp_path / ".igess" / "runs")
    records = [
        _record(modern, "duplicate"),
        _record(legacy, "duplicate"),
        _record(legacy, "smoke", kind="smoke"),
        _record(modern, "advice", kind="advice", status="failed"),
    ]
    running = _record(modern, "running", status="running")
    unknown = _record(legacy, "unknown", status="unknown")
    other = _record(RunRegistry(tmp_path / "other-project" / "runs"), "other")
    unregistered = modern.runs_root / "unregistered"
    unregistered.mkdir()
    (unregistered / "keep.txt").write_text("keep", encoding="utf-8")
    inputs = tmp_path / "economy.yaml"
    inputs.write_text("keep inputs", encoding="utf-8")
    registry = RunRegistry(modern.runs_root, read_roots=[legacy.runs_root])
    service = WorkflowService(tmp_path, registry=registry, authoring=False)

    preview = service.preview_history_cleanup()
    assert preview.count == 4  # Both physical copies of the duplicate are included.
    result = service.clear_history(preview.digest)

    assert result.ok and "Cleared 4" in result.message
    assert all(not record.run_dir.exists() for record in records)
    assert {r.run_id for r in service.list_runs()} == {"running", "unknown"}
    assert running.report_index.exists() and unknown.report_index.exists()
    assert other.report_index.read_text(encoding="utf-8") == "other"
    assert (unregistered / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert inputs.read_text(encoding="utf-8") == "keep inputs"
    assert service.preview_history_cleanup().count == 0


def test_clear_history_rejects_stale_preview_without_deleting_anything(tmp_path):
    registry = RunRegistry(tmp_path / "runs")
    original = _record(registry, "original")
    preview = registry.preview_history_cleanup()
    added = _record(registry, "added")

    with pytest.raises(ValueError, match="History changed"):
        registry.clear_history(preview.digest)

    assert original.report_index.exists() and added.report_index.exists()


def test_clear_history_rechecks_status_before_quarantine(tmp_path, monkeypatch):
    registry = RunRegistry(tmp_path / "runs")
    record = _record(registry, "changed")
    preview = registry.preview_history_cleanup()
    delete = RunRegistry._quarantine_and_delete_run

    def became_running(self, bound, **kwargs):
        payload = json.loads(record.status_path.read_text(encoding="utf-8"))
        payload["status"] = "running"
        record.status_path.write_text(json.dumps(payload), encoding="utf-8")
        return delete(self, bound, **kwargs)

    monkeypatch.setattr(RunRegistry, "_quarantine_and_delete_run", became_running)
    result = registry.clear_history(preview.digest)

    assert result.deleted == 0 and result.retained == 1
    assert record.report_index.exists()
    assert registry.list_runs()[0].status == "running"


def test_clear_history_does_not_follow_linked_run_directories(tmp_path):
    registry = RunRegistry(tmp_path / "runs")
    own = _record(registry, "own")
    outside = _record(RunRegistry(tmp_path / "outside"), "linked")
    try:
        (registry.runs_root / "linked").symlink_to(outside.run_dir, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks unavailable")
    preview = registry.preview_history_cleanup()
    assert preview.count == 1

    assert registry.clear_history(preview.digest).deleted == 1
    assert not own.run_dir.exists()
    assert outside.report_index.exists()


def test_clear_history_preserves_live_record_with_mismatched_deletion_manifest(tmp_path):
    registry = RunRegistry(tmp_path / "runs")
    record = _record(registry, "protected")
    loaded = registry._load_bound_record(registry.runs_root, record.run_dir).loaded
    entries = run_registry._snapshot_tombstone_entries(record.run_dir, loaded.directory_identity)
    trash = registry.runs_root / ".run-trash"
    identity = run_registry._ensure_private_trash(registry.runs_root, trash)
    run_registry._write_tombstone_manifest(
        registry.runs_root, trash, identity, trash / ("tomb-" + "a" * 32), loaded, entries,
    )
    foreign = record.run_dir / "foreign.txt"
    foreign.write_text("keep", encoding="utf-8")

    result = registry.clear_history(registry.preview_history_cleanup().digest)

    assert result.deleted == 0 and result.retained == 1
    assert foreign.read_text(encoding="utf-8") == "keep"
    assert record.report_index.exists()


def test_clear_history_can_retry_quarantined_data_after_delete_failure(tmp_path, monkeypatch):
    registry = RunRegistry(tmp_path / "runs")
    record = _record(registry, "retry")
    delete = run_registry._delete_bound_tombstone
    monkeypatch.setattr(run_registry, "_delete_bound_tombstone", lambda *args, **kwargs: False)

    result = registry.clear_history(registry.preview_history_cleanup().digest)

    assert result.deleted == 0 and result.retained == 1
    assert not record.run_dir.exists()
    assert registry.preview_history_cleanup().count == 1
    monkeypatch.setattr(run_registry, "_delete_bound_tombstone", delete)
    result = registry.clear_history(registry.preview_history_cleanup().digest)
    assert result.deleted == 1 and result.retained == 0
    assert registry.preview_history_cleanup().count == 0
    assert not list(registry.runs_root.glob(".run-trash/tomb-*"))


def _wait_task(request, prefix=""):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        task = json.loads(request("GET", prefix + "/task")[2])
        if task["state"] != "running":
            return task
        time.sleep(0.01)
    pytest.fail("cleanup task did not finish")


@pytest.mark.parametrize("single", [False, True])
def test_dashboard_cleanup_requires_confirmation_csrf_and_idle_guard(tmp_path, single):
    registry = RunRegistry(tmp_path / "runs")
    record = _record(registry, "history")
    service = WorkflowService(".", registry=registry, authoring=False)
    guard = BoundedSemaphore(1)
    server = ThreadingHTTPServer(("127.0.0.1", 0), dashboard._handler(
        service, CONFIG, TABLES, csrf_token="token", mutation_guard=guard,
    ))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=3)

    def request(method, path, form=None, headers=None):
        connection.request(method, path, urlencode(form) if form is not None else None, headers or {})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read().decode()

    preview = registry.preview_run_deletions()[record.run_id] if single else registry.preview_history_cleanup()
    form = ({"_csrf": "token", "confirm": "delete", "run_id": record.run_id, "run_digest": preview.digest}
            if single else {"_csrf": "token", "confirm": "clear", "history_digest": preview.digest})
    route = "/delete-run" if single else "/clear-history"
    try:
        assert request("GET", route)[0] == HTTPStatus.METHOD_NOT_ALLOWED
        assert request("POST", route, {"_csrf": "token"})[0] == HTTPStatus.BAD_REQUEST
        assert request("POST", route, {**form, "_csrf": "wrong"})[0] == HTTPStatus.FORBIDDEN
        assert request("POST", route, form, {"Origin": "http://evil.example"})[0] == HTTPStatus.FORBIDDEN
        if single:
            assert request("POST", route, {**form, "run_id": "../history"})[0] == HTTPStatus.BAD_REQUEST
        assert guard.acquire(blocking=False)
        try:
            assert request("POST", route, form)[0] == HTTPStatus.TOO_MANY_REQUESTS
        finally:
            guard.release()
        assert record.report_index.exists()
        status, headers, _ = request("POST", route, form)
        assert status == HTTPStatus.SEE_OTHER and headers["Location"] == "/#runs"
        task = _wait_task(request)
        assert task["state"] == "success" and ("Deleted run history" if single else "Cleared 1") in task["message"]
        assert not record.run_dir.exists()
        assert request("GET", "/reports/history/index.html")[0] == HTTPStatus.NOT_FOUND
    finally:
        connection.close()
        server.shutdown()
        server.RequestHandlerClass.close_tasks()
        server.server_close()
        thread.join(5)


@pytest.mark.parametrize("single", [False, True])
def test_dashboard_cleanup_routes_and_tokens_are_project_scoped(tmp_path, monkeypatch, single):
    services = {}
    records = {}
    entries = []
    for name in ("alpha", "beta"):
        root = tmp_path / name
        registry = RunRegistry(root / "runs")
        records[name] = _record(registry, "history")
        services[name] = WorkflowService(".", registry=registry, authoring=False)
        entries.append(DashboardProject(name, name, root))

    monkeypatch.setattr(dashboard, "create_dashboard_context", lambda root, *args, **kwargs:
                        (services[root.name], CONFIG, TABLES))
    server = ThreadingHTTPServer(("127.0.0.1", 0), dashboard._handler(None, None, None, task_runner_factory=InlineTaskRunner, projects=entries))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=3)

    def request(method, path, form=None):
        connection.request(method, path, urlencode(form) if form else None)
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read().decode()

    def ready_page(prefix):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            body = request("GET", prefix + "/")[2]
            if 'id="clear-history-dialog"' in body:
                return body
            time.sleep(0.01)
        pytest.fail("history page did not load")

    try:
        body_a, body_b = ready_page("/p/alpha"), ready_page("/p/beta")
        assert 'action="/p/alpha/clear-history"' in body_a
        assert 'action="/p/alpha/delete-run"' in body_a
        token_a = re.search(r'name="_csrf" value="([^"]+)"', body_a)[1]
        token_b = re.search(r'name="_csrf" value="([^"]+)"', body_b)[1]
        preview_b = (services["beta"].preview_run_deletions()["history"] if single
                     else services["beta"].preview_history_cleanup())
        form = ({"confirm": "delete", "run_id": "history", "run_digest": preview_b.digest, "_csrf": token_a}
                if single else {"confirm": "clear", "history_digest": preview_b.digest, "_csrf": token_a})
        route = "/p/beta/delete-run" if single else "/p/beta/clear-history"
        assert request("POST", route, form)[0] == HTTPStatus.FORBIDDEN
        form["_csrf"] = token_b
        assert request("POST", route, form)[0] == HTTPStatus.SEE_OTHER
        assert _wait_task(request, "/p/beta")["state"] == "success"
        assert records["alpha"].report_index.exists()
        assert not records["beta"].run_dir.exists()
    finally:
        connection.close()
        server.shutdown()
        server.RequestHandlerClass.close_tasks()
        server.server_close()
        thread.join(5)


@pytest.mark.parametrize("change", ["status", "replacement"])
def test_clear_history_rejects_status_or_directory_changes_since_preview(tmp_path, change):
    registry = RunRegistry(tmp_path / "runs")
    record = _record(registry, "completed")
    preview = registry.preview_history_cleanup()
    if change == "status":
        payload = json.loads(record.status_path.read_text(encoding="utf-8"))
        payload["status"] = "running"
        record.status_path.write_text(json.dumps(payload), encoding="utf-8")
    else:
        record.run_dir.rename(tmp_path / "original")
        _record(registry, "completed")

    with pytest.raises(ValueError, match="History changed"):
        registry.clear_history(preview.digest)
    assert record.report_index.exists()


def test_clear_history_supports_unversioned_legacy_status(tmp_path):
    registry = RunRegistry(tmp_path / "runs")
    directory = registry.runs_root / "legacy"
    record = registry.write_status(
        directory, status="success", scenario_id="day_1", message="Legacy run",
        output_dir=directory / "output", report_dir=directory / "report",
        report_index=directory / "report/index.html",
    )
    assert record.version is None
    result = registry.clear_history(registry.preview_history_cleanup().digest)
    assert (result.deleted, result.retained) == (1, 0)
    assert not directory.exists()


def test_clear_history_failure_retains_data_and_recoverable_manifest(tmp_path, monkeypatch):
    registry = RunRegistry(tmp_path / "runs")
    _record(registry, "completed")
    original_delete = run_registry._delete_bound_tombstone
    monkeypatch.setattr(run_registry, "_delete_bound_tombstone", lambda *args, **kwargs: False)
    service = WorkflowService(".", registry=registry, authoring=False)
    result = service.clear_history(service.preview_history_cleanup().digest)

    assert not result.ok
    assert "Cleared 0" in result.message and "1 records" in result.message
    trash = registry.runs_root / ".run-trash"
    assert len(list(trash.glob("tomb-*.json"))) == 1
    assert len(list(trash.glob("tomb-*/report/index.html"))) == 1
    monkeypatch.setattr(run_registry, "_delete_bound_tombstone", original_delete)
    assert registry._recover_run_trash().deleted_run_ids == ("completed",)
    assert not list(trash.glob("tomb-*"))


@pytest.mark.parametrize("kind,status", [("formal", "success"), ("smoke", "success"), ("advice", "failed")])
def test_delete_run_removes_only_selected_id_and_legacy_copies(tmp_path, kind, status):
    modern = RunRegistry(tmp_path / "runs")
    legacy = RunRegistry(tmp_path / "legacy")
    selected = _record(modern, "selected", kind=kind, status=status)
    copy = _record(legacy, "selected", kind=kind, status=status)
    other = _record(modern, "other")
    registry = RunRegistry(modern.runs_root, read_roots=[legacy.runs_root])
    service = WorkflowService(tmp_path, registry=registry, authoring=False)
    preview = service.preview_run_deletions()["selected"]
    assert preview.count == 2
    added = _record(legacy, "added-after-preview")

    assert service.delete_run("selected", preview.digest).ok
    assert not selected.run_dir.exists() and not copy.run_dir.exists()
    assert other.report_index.exists() and added.report_index.exists()


@pytest.mark.parametrize("change", ["running", "unknown", "replacement", "message", "removed"])
def test_delete_run_rejects_changed_confirmation(tmp_path, change):
    registry = RunRegistry(tmp_path / "runs")
    record = _record(registry, "selected")
    preview = registry.preview_run_deletions()["selected"]
    if change in {"replacement", "removed"}:
        record.run_dir.rename(tmp_path / "original")
        if change == "replacement":
            _record(registry, "selected")
    else:
        payload = json.loads(record.status_path.read_text(encoding="utf-8"))
        payload["message" if change == "message" else "status"] = change
        record.status_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="Run"):
        registry.delete_run("selected", preview.digest)
    assert list(tmp_path.rglob("index.html"))


def test_delete_run_preserves_other_pending_deletions(tmp_path, monkeypatch):
    registry = RunRegistry(tmp_path / "runs")
    _record(registry, "pending")
    original = run_registry._delete_bound_tombstone
    monkeypatch.setattr(run_registry, "_delete_bound_tombstone", lambda *args, **kwargs: False)
    assert registry.clear_history(registry.preview_history_cleanup().digest).retained == 1
    trash = registry.runs_root / ".run-trash"
    before = sorted(str(path) for path in trash.rglob("*"))
    monkeypatch.setattr(run_registry, "_delete_bound_tombstone", original)
    _record(registry, "selected")
    assert registry.delete_run("selected", registry.preview_run_deletions()["selected"].digest).deleted == 1
    assert sorted(str(path) for path in trash.rglob("*")) == before


def test_delete_run_rechecks_status_before_quarantine(tmp_path, monkeypatch):
    registry = RunRegistry(tmp_path / "runs")
    record = _record(registry, "selected")
    preview = registry.preview_run_deletions()["selected"]
    original = RunRegistry._quarantine_and_delete_run

    def changed(self, bound, **kwargs):
        payload = json.loads(record.status_path.read_text(encoding="utf-8"))
        payload["status"] = "running"
        record.status_path.write_text(json.dumps(payload), encoding="utf-8")
        return original(self, bound, **kwargs)

    monkeypatch.setattr(RunRegistry, "_quarantine_and_delete_run", changed)
    assert registry.delete_run("selected", preview.digest).retained == 1
    assert record.report_index.exists()


def test_each_run_has_delete_button_and_unsafe_records_stay_disabled(tmp_path):
    registry = RunRegistry(tmp_path / "runs")
    for status in ("success", "failed", "running", "unknown"):
        _record(registry, status, status=status)
    legacy = RunRegistry(tmp_path / "legacy")
    _record(legacy, "success", status="running")
    registry = RunRegistry(registry.runs_root, read_roots=[legacy.runs_root])
    service = WorkflowService(tmp_path, registry=registry, authoring=False)
    body = dashboard._history_panel(service.list_runs(), service, "token")
    for status in ("success", "failed", "running", "unknown"):
        button = re.search(r'<button[^>]*data-delete-run="' + status + '"[^>]*>', body)[0]
        assert ('disabled data-unavailable' in button) == (status != "failed")
    assert 'id="cancel-delete-run" autofocus' in body
    assert registry.preview_run_deletions().keys() == {"failed"}
    with pytest.raises(ValueError, match="not completed"):
        registry.delete_run("success", "0" * 64)
