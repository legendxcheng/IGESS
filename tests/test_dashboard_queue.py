"""FIFO admission, attribution and HTTP boundaries for simulation batches."""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from threading import BoundedSemaphore, Event, Thread
from urllib.parse import urlencode

import pytest

from dashboard_fixtures import InlineTaskRunner
from test_dashboard import _DashboardService
from igess.dashboard import _DashboardRuntime, _handler


def wait_for(check):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(.01)
    raise AssertionError("Queue did not reach the expected state")


class ControlledRunner(InlineTaskRunner):
    def __init__(self, *args):
        super().__init__(*args)
        self.entered, self.release = Event(), Event()
        self.calls = []

    def run(self, operation, scenario="", **options):
        if operation == "check":
            return super().run(operation, scenario)
        self.calls.append(scenario)
        if len(self.calls) == 1:
            self.entered.set()
            assert self.release.wait(5)
        if scenario == "day<1":
            raise RuntimeError("Injected simulation failure")
        return {"state": "success", "message": "Complete", "run_id": f"run-{len(self.calls)}"}

    def close(self):
        self.release.set()


@pytest.fixture
def runtime(tmp_path):
    service = _DashboardService(tmp_path)
    runner = ControlledRunner(service, None, None)
    runtime = _DashboardRuntime(service, None, None, "token", BoundedSemaphore(1), runner)
    wait_for(lambda: not runtime.snapshot()["refreshing"])
    try:
        yield runtime, runner
    finally:
        runtime.close()


def test_fifo_append_failure_and_unique_receipts(runtime):
    runtime, runner = runtime
    first = runtime.enqueue(["smoke", "day<1", "smoke"])
    assert runner.entered.wait(1)
    second = runtime.enqueue(["smoke"])
    assert runtime.snapshot()["queued_count"] == 3
    assert not runtime.submit("/clear-history", "", history_digest="a" * 64)
    assert not runtime.guard.acquire(blocking=False)
    # Returned receipts and polling snapshots cannot mutate scheduler state.
    first[0]["scenario"] = "changed"
    runtime.snapshot()["queue"][1]["scenario"] = "changed"
    runner.release.set()
    done = wait_for(lambda: runtime.snapshot() if runtime.snapshot()["state"] != "running" else None)
    assert runner.calls == ["smoke", "day<1", "smoke", "smoke"]
    assert [t["state"] for t in done["queue"]] == ["success", "failed", "success", "success"]
    assert len({t["task_id"] for t in done["queue"]}) == 4
    assert done["queue"][-1]["task_id"] == second[0]["task_id"]
    assert done["queued_count"] == 0
    for before, after in zip(done["queue"], done["queue"][1:]):
        assert before["finished_at"] <= after["started_at"]
    assert runtime.guard.acquire(blocking=False)
    runtime.guard.release()


def test_batch_is_atomic_and_can_follow_existing_single_task(runtime):
    runtime, runner = runtime
    for invalid in ([], ["smoke", "missing"], ["smoke"] * 101):
        with pytest.raises(ValueError):
            runtime.enqueue(invalid)
    assert runtime.snapshot()["queue"] == []
    assert runtime.submit("/formal", "smoke")
    assert runner.entered.wait(1)
    assert runtime.enqueue(["smoke", "smoke"])
    runner.release.set()
    wait_for(lambda: runtime.snapshot()["state"] != "running")
    assert runner.calls == ["smoke"] * 3


def test_concurrent_batches_remain_contiguous(runtime):
    runtime, runner = runtime
    runtime.enqueue(["smoke"])
    assert runner.entered.wait(1)
    with ThreadPoolExecutor(max_workers=6) as pool:
        batches = list(pool.map(lambda _: runtime.enqueue(["smoke", "day<1"]), range(6)))
    ids = [t["task_id"] for t in runtime.snapshot()["queue"]]
    for batch in batches:
        position = ids.index(batch[0]["task_id"])
        assert ids[position + 1] == batch[1]["task_id"]
    runner.release.set()
    wait_for(lambda: runtime.snapshot()["state"] != "running")
    assert runner.calls == ["smoke"] + ["smoke", "day<1"] * 6


def test_shutdown_cancels_waiting_entries_without_starting_them(runtime):
    runtime, runner = runtime
    runtime.enqueue(["smoke", "smoke", "smoke"])
    assert runner.entered.wait(1)
    runtime.close()
    assert runner.calls == ["smoke"]
    assert [t["state"] for t in runtime.snapshot()["queue"]] == ["success", "cancelled", "cancelled"]
    assert runtime.enqueue(["smoke"]) is None


def test_worker_start_failure_releases_queue_and_allows_next_submission(runtime, monkeypatch):
    runtime, runner = runtime
    original = runtime._start_worker
    def fail(*args):
        raise RuntimeError("Cannot start thread")
    monkeypatch.setattr(runtime, "_start_worker", fail)
    runtime.enqueue(["smoke", "smoke"])
    assert [t["state"] for t in runtime.snapshot()["queue"]] == ["failed", "failed"]
    monkeypatch.setattr(runtime, "_start_worker", original)
    runner.release.set()
    assert runtime.enqueue(["smoke"])
    wait_for(lambda: runtime.snapshot()["state"] == "success")


def test_queue_http_receipt_security_and_live_polling(tmp_path):
    service = _DashboardService(tmp_path)
    runner = ControlledRunner(service, None, None)
    handler = _handler(service, None, None, csrf_token="token", task_runner_factory=lambda *args: runner)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    def request(path, data=None, headers=None):
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=1)
        try:
            connection.request("GET" if data is None else "POST", path,
                               None if data is None else urlencode(data), headers or {})
            response = connection.getresponse()
            return response.status, response.read().decode()
        finally:
            connection.close()
    try:
        wait_for(lambda: not json.loads(request("/task")[1])["refreshing"])
        form = {"_csrf": "token", "scenarios": "smoke\nday<1\nsmoke"}
        assert request("/queue", {**form, "_csrf": "wrong"})[0] == 403
        assert request("/queue", form, {"Origin": "https://other.example"})[0] == 403
        assert request("/queue", {**form, "scenarios": "smoke\nmissing"})[0] == 400
        assert request("/queue", {**form, "resume_run_id": "previous-run"})[0] == 400
        assert json.loads(request("/queue")[1])["queue"] == []
        code, body = request("/queue", form, {"Accept": "application/json"})
        assert code == 202
        receipt = json.loads(body)
        assert receipt["instance_id"]
        assert len(receipt["tasks"]) == 3
        assert runner.entered.wait(1)
        state = json.loads(request("/queue")[1])
        assert state["queued_count"] == 2
        assert state["queue"][0]["task_id"] == receipt["tasks"][0]["task_id"]
        assert request("/queue", {**form, "scenarios": "smoke"})[0] == 303
        assert request("/formal", {"_csrf": "token", "scenario": "smoke"})[0] == 429
        assert request("/")[0] == 200
        runner.release.set()
        wait_for(lambda: json.loads(request("/task")[1])["state"] != "running")
        assert runner.calls == ["smoke", "day<1", "smoke", "smoke"]
    finally:
        runner.release.set()
        server.shutdown()
        handler.close_tasks()
        server.server_close()
        thread.join(5)
