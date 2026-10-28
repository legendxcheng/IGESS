"""Acceptance at the HTTP -> task status -> saved artifacts boundary."""

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from http.client import HTTPConnection
from pathlib import Path
from urllib.parse import urlencode

import pytest


def wait_for(check, timeout=25):
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            value = check()
            if value:
                return value
        except (OSError, ValueError) as error:
            last_error = error
        time.sleep(.04)
    raise AssertionError(f"Dashboard did not reach expected state: {last_error}")


class LiveDashboard:
    def __init__(self, root):
        self.root = root
        self.package = root / "src" / "igess"
        self.project = root / "项目 with spaces"
        self.history = root / "history"
        repo = Path(__file__).resolve().parents[1]
        shutil.copytree(repo / "src/igess", self.package, ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(repo / "examples/shelldiver_v0", self.project,
                        ignore=shutil.ignore_patterns(".igess", "runs", "reports", "__pycache__"))
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            self.port = listener.getsockname()[1]
        self.options = dict(project=str(self.project), config=None, tables=None,
                            runs_root=str(self.history), host="127.0.0.1", port=self.port)
        self.log = (root / "server.log").open("w", encoding="utf-8")
        self.process = None
        self.scenario = "analytic_smoke"

    def start(self):
        self.process = subprocess.Popen(
            [sys.executable, "-u", "-m", "igess.dashboard_process", json.dumps(self.options)],
            cwd=self.root, env={**os.environ, "PYTHONPATH": str(self.root / "src")},
            stdout=self.log, stderr=self.log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        wait_for(lambda: self.get_json("/server/status"))
        _, headers, _ = self.request("/")
        self.prefix = headers["Location"].rstrip("/")
        self.request(self.prefix + "/")
        self.wait_idle()
        return self

    def request(self, path, data=None, headers=None):
        connection = HTTPConnection("127.0.0.1", self.port, timeout=3)
        try:
            connection.request("POST" if data is not None else "GET", path,
                               urlencode(data) if data is not None else None, headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read().decode()
        finally:
            connection.close()

    def get_json(self, path):
        status, _, body = self.request(path)
        if status != 200:
            raise ValueError(f"HTTP {status}: {body[:300]}")
        return json.loads(body)

    def wait_idle(self):
        def ready():
            state = self.get_json(self.prefix + "/task")
            return state if state["state"] != "running" and not state["refreshing"] else None
        return wait_for(ready)

    def submit(self, action="formal"):
        page = self.request(self.prefix + "/")[2]
        token = re.search(r'name="_csrf" value="([^"]+)"', page)[1]
        return self.request(self.prefix + "/" + action, {"_csrf": token, "scenario": self.scenario})[0]

    def run(self):
        assert self.submit() == 303
        result = self.wait_idle()
        assert result["state"] == "success", result
        return self.history / self.prefix.split("/")[-1] / result["run_id"]

    def close(self):
        try:
            if self.process and self.process.poll() is None:
                self.wait_idle()
                page = self.request(self.prefix + "/")[2]
                token = re.search(r'id="confirm-restart-service"[^>]*data-token="([^"]+)"', page)[1]
                assert self.request("/server/restart", {"_csrf": token, "confirm": "restart"})[0] == 200
                self.process.wait(timeout=15)
        finally:
            if self.process and self.process.poll() is None:
                self.process.kill()
                self.process.wait(timeout=10)
            self.log.close()


@pytest.fixture
def live(tmp_path):
    server = LiveDashboard(tmp_path)
    try:
        yield server
    finally:
        server.close()


def test_next_task_loads_changed_simulation_dependency_and_report_without_server_restart(live):
    simulator = live.package / "simulator.py"
    original = simulator.read_text(encoding="utf-8")
    original = original.replace("timeline=timeline, events=events)", "timeline=timeline[:1], events=events)")
    simulator.write_text(original, encoding="utf-8")
    report = live.package / "reporting/static.py"
    report.write_text(report.read_text(encoding="utf-8").replace('return index',
                     'index.write_text(index.read_text(encoding="utf-8") + "<!--version-A-->", encoding="utf-8")\n    return index'), encoding="utf-8")
    live.start()
    instance = live.get_json("/server/status")["instance_id"]
    first = live.run()
    before = (first / "report/index.html").read_bytes()
    assert len(json.loads((first / "output/timeline.json").read_text(encoding="utf-8"))) == 1
    # Same length and mtime: a fresh PID alone must not reuse stale bytecode.
    for path, old, new in ((simulator, "timeline[:1]", "timeline[:2]"), (report, "version-A", "version-B")):
        stamp = path.stat()
        path.write_text(path.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")
        os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    second = live.run()
    assert len(json.loads((second / "output/timeline.json").read_text(encoding="utf-8"))) == 2
    assert "<!--version-B-->" in (second / "report/index.html").read_text(encoding="utf-8")
    assert (first / "report/index.html").read_bytes() == before
    assert live.get_json("/server/status")["instance_id"] == instance


def test_worker_crash_finishes_only_its_run_and_allows_retry(live):
    live.start()
    healthy = live.run()
    original_record = (healthy / "run_status.json").read_bytes()
    simulator = live.package / "simulator.py"
    original = simulator.read_text(encoding="utf-8")
    simulator.write_text(original.replace(
        'def run_scenario(self, scenario_id: str) -> SimulationResult:',
        'def run_scenario(self, scenario_id: str) -> SimulationResult:\n        import os; os._exit(23)'), encoding="utf-8")
    assert live.submit() == 303
    failed = live.wait_idle()
    assert failed["state"] == "failed"
    records = list(live.history.glob("*/*/run_status.json"))
    assert len(records) == 2
    assert all(json.loads(path.read_text())["status"] != "running" for path in records)
    assert (healthy / "run_status.json").read_bytes() == original_record
    assert failed.get("run_id")
    assert "23" in failed["message"]
    assert list((live.project / ".igess/diagnostics").glob("*.json"))
    simulator.write_text(original, encoding="utf-8")
    live.run()


@pytest.mark.parametrize("crash", [False, True])
def test_worker_completion_reaps_its_descendants(live, crash):
    simulator = live.package / "simulator.py"
    original = simulator.read_text(encoding="utf-8")
    code = '''
        import subprocess, sys, os, time
        from pathlib import Path
        child = subprocess.Popen([sys.executable, '-c', "import os,time; from pathlib import Path; Path('descendant.pid').write_text(str(os.getpid())); time.sleep(90)"])
        while not Path('descendant.pid').exists():
            time.sleep(.02)
'''
    if crash:
        code += "        os._exit(24)\n"
    simulator.write_text(original.replace(
        'def run_scenario(self, scenario_id: str) -> SimulationResult:',
        'def run_scenario(self, scenario_id: str) -> SimulationResult:' + code), encoding="utf-8")
    live.start()
    assert live.submit() == 303
    assert live.wait_idle()["state"] == ("failed" if crash else "success")
    pid = int((live.project / "descendant.pid").read_text())
    assert_process_gone(pid)


def assert_process_gone(pid):
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        handle = kernel.OpenProcess(0x100001, False, pid)
        try:
            assert not handle or kernel.WaitForSingleObject(handle, 3000) == 0
        finally:
            if handle:
                if kernel.WaitForSingleObject(handle, 0) != 0:
                    kernel.TerminateProcess(handle, 1)  # Dispose only this test-owned descendant.
                kernel.CloseHandle(handle)
    else:
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)


def test_import_error_is_visible_and_fix_works_without_restart(live):
    live.start()
    instance = live.get_json("/server/status")["instance_id"]
    dependency = live.package / "simulator.py"
    original = dependency.read_text(encoding="utf-8")
    dependency.write_text("syntax error !!!", encoding="utf-8")
    assert live.submit() == 303
    failed = live.wait_idle()
    assert failed["state"] == "failed"
    assert "SyntaxError" in failed["message"]
    assert not list(live.history.glob("*/*/run_status.json"))
    assert "Model check failed" in live.request(live.prefix + "/")[2]
    dependency.write_text(original, encoding="utf-8")
    assert live.submit("refresh") == 303
    live.wait_idle()
    live.run()
    assert live.get_json("/server/status")["instance_id"] == instance


def test_authoring_worker_preserves_custom_history_and_report_failure(live):
    from igess.authoring.templates import initialize_authoring_project
    from igess.authoring.service import AuthoringService
    from test_authoring_service import _add_runnable_activity

    live.project = initialize_authoring_project(live.root / "authoring")
    _add_runnable_activity(AuthoringService(live.project))
    live.options["project"] = str(live.project)
    live.scenario = "smoke"
    live.start()
    assert live.get_json(live.prefix + "/status")["ok"]
    successful = live.run()
    assert json.loads((successful / "run_status.json").read_text())["kind"] == "formal"
    report = live.package / "reporting/static.py"
    original = report.read_text(encoding="utf-8")
    report.write_text(original.replace("    data = load_report_data(run_dir)",
                                      "    raise ValueError('REPORT_FAILURE_TEST')"), encoding="utf-8")
    assert live.submit() == 303
    failed = live.wait_idle()
    assert failed["state"] == "failed"
    assert "REPORT_FAILURE_TEST" in failed["message"]
    directory = live.history / live.prefix.split("/")[-1] / failed["run_id"]
    assert (directory / "output/timeline.json").exists()
    assert json.loads((directory / "run_status.json").read_text())["status"] == "failed"
    diagnostic = live.get_json(live.prefix + "/diagnostics/" + failed["diagnostic"]["details"]["diagnostic_id"])
    assert diagnostic["phase"] == "report"
    report.write_text(original, encoding="utf-8")
    live.run()


def test_refresh_loads_current_check_code_and_polling_is_cached(live):
    live.start()
    checker = live.package / "linter.py"
    source = checker.read_text(encoding="utf-8")
    checker.write_text(source.replace("        rules = raw.rules", "        raise ValueError('CHECK_VERSION_B')"), encoding="utf-8")
    assert live.submit("refresh") == 303
    live.wait_idle()
    assert live.get_json(live.prefix + "/status")["message"] == "CHECK_VERSION_B"
    assert "CHECK_VERSION_B" in live.request(live.prefix + "/")[2]
    checker.write_text(source, encoding="utf-8")
    for _ in range(3):
        assert live.get_json(live.prefix + "/status")["message"] == "CHECK_VERSION_B"
    assert live.submit("refresh") == 303
    live.wait_idle()
    assert live.get_json(live.prefix + "/status")["ok"]


def test_slow_task_isolated_across_projects_and_rejects_restart_and_duplicates(live):
    beta = live.project / "projects/beta"
    beta.parent.mkdir()
    beta.mkdir()
    shutil.copyfile(live.project / "economy.yaml", beta / "economy.yaml")
    shutil.copytree(live.project / "luban_exports", beta / "luban_exports")
    simulator = live.package / "simulator.py"
    source = simulator.read_text(encoding="utf-8")
    source = source.replace("timeline=timeline, events=events)", "timeline=timeline[:1], events=events)")
    pause = '''
        from pathlib import Path
        import time
        if Path('pause').exists():
            Path('entered').touch()
            deadline = time.monotonic() + 20
            while not Path('release').exists() and time.monotonic() < deadline:
                time.sleep(.02)
'''
    source = source.replace('def run_scenario(self, scenario_id: str) -> SimulationResult:',
                            'def run_scenario(self, scenario_id: str) -> SimulationResult:' + pause)
    simulator.write_text(source, encoding="utf-8")
    live.start()
    alpha_prefix = live.prefix
    page = live.request(live.prefix + "/")[2]
    choices = re.findall(r'<option value="(/p/[^\"]+)/"', page)
    beta_prefix = next(path for path in choices if path != alpha_prefix)
    token = re.search(r'id="confirm-restart-service"[^>]*data-token="([^"]+)"', page)[1]
    (live.project / "pause").touch()
    try:
        assert live.submit() == 303
        wait_for(lambda: (live.project / "entered").exists())
        assert live.get_json(alpha_prefix + "/task")["state"] == "running"
        assert live.submit() == 429
        assert live.request("/server/restart", {"_csrf": token, "confirm": "restart"})[0] == 409
        assert live.request(alpha_prefix + "/")[0] == 200
        live.prefix = beta_prefix
        live.request(beta_prefix + "/")
        live.wait_idle()
        beta_run = live.run()
        assert beta_run.exists()
        assert live.get_json(alpha_prefix + "/task")["state"] == "running"
        simulator.write_text(source.replace("timeline[:1]", "timeline[:2]"), encoding="utf-8")
    finally:
        live.prefix = alpha_prefix
        (live.project / "release").touch()
    alpha_result = live.wait_idle()
    alpha_run = live.history / alpha_prefix.split("/")[-1] / alpha_result["run_id"]
    assert len(json.loads((alpha_run / "output/timeline.json").read_text())) == 1
    next_run = live.run()
    assert len(json.loads((next_run / "output/timeline.json").read_text())) == 2


def test_lost_reply_preserves_saved_success_and_reports_communication_error(live):
    class LostReplyProcess(subprocess.Popen):
        def __init__(self, args, **kwargs):
            self.result_path = Path(args[-1])
            self.operation = json.loads(Path(args[-2]).read_text())["operation"]
            super().__init__(args, **kwargs)

        def wait(self, *args, **kwargs):
            code = super().wait(*args, **kwargs)
            if self.operation == "simulate":
                self.result_path.unlink(missing_ok=True)
            return code

    lose_reply = True

    def launch(args, **kwargs):
        return (LostReplyProcess if lose_reply else subprocess.Popen)(args, **kwargs)

    with local_server(live, launch):
        assert live.submit() == 303
        result = live.wait_idle()
        assert result["state"] == "success"
        assert "communication failed" in result["message"]
        run = live.history / result["run_id"]
        assert json.loads((run / "run_status.json").read_text())["status"] == "success"
        assert (run / "report/index.html").exists()
        diagnostic = live.get_json("/diagnostics/" + result["diagnostic"]["details"]["diagnostic_id"])
        assert diagnostic["context"]["exit_code"] == 0
        assert "output_tail" in diagnostic["context"]
        lose_reply = False
        assert live.submit() == 303
        assert live.wait_idle()["state"] == "success"


@contextmanager
def local_server(live, launch):
    from http.server import ThreadingHTTPServer
    from threading import Thread
    from igess.dashboard import _handler
    from igess.dashboard_tasks import DashboardTaskRunner
    from igess.workflows import WorkflowService

    def isolated_launch(args, **kwargs):
        args = list(args)
        args[2] = str(live.package / "dashboard_task_worker.py")
        return launch(args, **kwargs)

    factory = lambda *args: DashboardTaskRunner(*args, launch_process=isolated_launch)
    service = WorkflowService(live.project, live.history, authoring=False)
    handler = _handler(service, "economy.yaml", "luban_exports", csrf_token="token", task_runner_factory=factory)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    live.port, live.prefix = server.server_port, ""
    try:
        live.wait_idle()
        yield handler
    finally:
        server.shutdown()
        handler.close_tasks()
        server.server_close()
        thread.join(5)


def test_controlled_shutdown_reaps_active_worker_descendant_and_temporary_files(live):
    launched = []

    def launch(args, **kwargs):
        process = subprocess.Popen(args, **kwargs)
        launched.append((process, Path(args[-2]).parent))
        return process

    simulator = live.package / "simulator.py"
    code = '''
        import subprocess, sys, os, time
        from pathlib import Path
        Path('worker.pid').write_text(str(os.getpid()))
        subprocess.Popen([sys.executable, '-c', "import os,time; from pathlib import Path; Path('descendant.pid').write_text(str(os.getpid())); time.sleep(90)"])
        time.sleep(90)
'''
    simulator.write_text(simulator.read_text(encoding="utf-8").replace(
        'def run_scenario(self, scenario_id: str) -> SimulationResult:',
        'def run_scenario(self, scenario_id: str) -> SimulationResult:' + code), encoding="utf-8")
    with local_server(live, launch) as handler:
        assert live.submit() == 303
        wait_for(lambda: (live.project / "descendant.pid").exists())
        assert live.get_json("/task")["state"] == "running"
        handler.close_tasks()
        for name in ("worker.pid", "descendant.pid"):
            assert_process_gone(int((live.project / name).read_text()))
        for process, directory in launched:
            assert process.poll() is not None
            assert process.stdout.closed and process.stdin.closed
            assert not directory.exists()
        statuses = list(live.history.glob("*/run_status.json"))
        assert len(statuses) == 1
        assert json.loads(statuses[0].read_text())["status"] == "failed"


def test_launch_failure_is_visible_and_releases_project_for_retry(live):
    from http.server import ThreadingHTTPServer
    from threading import Thread
    from igess.dashboard import _handler
    from igess.dashboard_tasks import DashboardTaskRunner
    from igess.workflows import WorkflowService

    fail_launch = True

    def launch(*args, **kwargs):
        if fail_launch:
            raise OSError("TEST_INTERPRETER_UNAVAILABLE")
        return subprocess.Popen(*args, **kwargs)

    service = WorkflowService(live.project, live.history, authoring=False)
    factory = lambda *args: DashboardTaskRunner(*args, launch_process=launch)
    handler = _handler(service, "economy.yaml", "luban_exports", csrf_token="token", task_runner_factory=factory)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    live.port, live.prefix = server.server_port, ""
    try:
        live.wait_idle()
        assert live.submit() == 303
        failed = live.wait_idle()
        assert failed["state"] == "failed"
        assert "TEST_INTERPRETER_UNAVAILABLE" in failed["message"]
        assert not list(live.history.glob("*/run_status.json"))
        fail_launch = False
        assert live.submit("refresh") == 303
        live.wait_idle()
        assert live.submit() == 303
        assert live.wait_idle()["state"] == "success"
    finally:
        server.shutdown()
        handler.close_tasks()
        server.server_close()
        thread.join(5)


def test_advice_uses_updated_code_and_large_logs_do_not_block_results(live):
    live.start()
    assert live.submit("advise") == 303
    first = live.wait_idle()
    assert first["state"] in {"ok", "needs_attention"}, first
    advice = live.package / "advice.py"
    advice.write_text(advice.read_text(encoding="utf-8").replace(
        "summary = _summary(status, findings, table_recommendations, yaml_recommendations)",
        'print("x" * 2_000_000)\n    summary = "ADVICE_VERSION_B"'), encoding="utf-8")
    assert live.submit("advise") == 303
    second = live.wait_idle()
    assert second["state"] in {"ok", "needs_attention"}, second
    assert second["message"] == "ADVICE_VERSION_B"
    assert second["run_id"] != first["run_id"]
    output = live.get_json(live.prefix + "/diagnostics/" + second["process_log"])
    assert output["exit_code"] == 0
    assert 60000 < len(output["output_tail"]) <= 65536
    assert "Open task output" in live.request(live.prefix + "/")[2]
