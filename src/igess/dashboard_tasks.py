"""One fresh interpreter per Dashboard calculation; no business logic here."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import Lock, Thread
from time import monotonic, sleep
import uuid

from .dashboard_process_tree import TaskProcessTree


class DashboardTaskRunner:
    def __init__(self, service, config, tables, *, launch_process=None):
        project = service.project_root.resolve()

        def absolute(path):
            return str((project / path).resolve()) if path is not None else None

        self.context = {
            "project": str(project), "authoring": service.is_authoring,
            "config": None if service.is_authoring else absolute(config),
            "tables": None if service.is_authoring else absolute(tables),
            "runs_root": str(service.registry.runs_root.resolve()),
        }
        self.registry = service.registry
        self._lock = Lock()
        self._children = set()
        self._closed = False
        self._launch_process = launch_process or subprocess.Popen

    def run(self, operation, scenario="", *, resume_run_id=None):
        if operation not in {"simulate", "advise", "check"}:
            raise ValueError("Unsupported Dashboard operation")
        task_id = uuid.uuid4().hex
        with tempfile.TemporaryDirectory(prefix="igess-dashboard-task-") as temporary:
            directory = Path(temporary)
            request, result = directory / "request.json", directory / "result.json"
            claim = directory / "claim.json"
            request.write_text(json.dumps({"version": 1, "task_id": task_id,
                                          "context": self.context, "operation": operation,
                                          "scenario": scenario, "resume_run_id": resume_run_id,
                                          "claim_path": str(claim)}), encoding="utf-8")
            code, log = None, ""
            try:
                code, log = self._run_process(request, result, task_id)
                if code:
                    raise RuntimeError(f"Task process exited with code {code}:\n{log}")
                payload = self._read_payload(result)
                if payload.get("version") != 1 or payload.get("task_id") != task_id:
                    raise ValueError("Dashboard task result does not match the request")
                outcome = payload["outcome"]
                if not isinstance(outcome, dict):
                    raise ValueError("Invalid Dashboard task outcome")
                if operation == "check":
                    if not isinstance(outcome.get("status"), dict):
                        raise ValueError("Missing model check result")
                else:
                    if not isinstance(outcome.get("message"), str):
                        raise ValueError("Missing task completion message")
                    if outcome.get("state") not in {"success", "failed", "ok", "needs_attention"}:
                        raise ValueError("Invalid task completion state")
                    record = self._owned_record(claim, task_id)
                    if outcome.get("run_id") != (record.run_id if record else None):
                        raise ValueError("Task result does not match its registered run")
                    if record and record.status != outcome["state"]:
                        raise ValueError("Task result conflicts with saved run status")
                    if not record and outcome["state"] != "failed":
                        raise ValueError("Successful task has no registered run")
                if log:
                    from .development_diagnostics import DevelopmentDiagnostics

                    try:
                        outcome["process_log"] = DevelopmentDiagnostics(self.context["project"]).write_task_output(
                            task_id, operation, code, log,
                        )["diagnostic_id"]
                    except Exception as diagnostic_error:
                        outcome["log_warning"] = f"Task output could not be saved: {diagnostic_error}"
                return outcome
            except Exception as error:
                outcome = self._failed(error, claim, task_id, operation, code, log)
                if operation == "check":
                    raise RuntimeError(outcome["message"]) from error
                return outcome

    def _run_process(self, request, result, task_id):
        tail = bytearray()
        process = None
        tree = None
        reader = None

        def drain():
            while chunk := process.stdout.read1(8192):
                tail.extend(chunk)
                if len(tail) > 65536:
                    del tail[:-65536]

        try:
            with self._lock:
                if self._closed:
                    raise RuntimeError("Dashboard is stopping")
                process = self._launch_process(
                    [sys.executable, "-u", str(Path(__file__).with_name("dashboard_task_worker.py")),
                     str(request), str(result)], cwd=self.context["project"],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.PIPE,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                    start_new_session=os.name != "nt",
                )
                reader = Thread(target=drain, daemon=True)
                reader.start()
                ready = request.with_name("ready.json")
                deadline = monotonic() + 15
                while not ready.exists():
                    if process.poll() is not None:
                        reader.join(2)
                        raise RuntimeError(f"Task bootstrap exited with code {process.returncode}:\n"
                                           + tail.decode("utf-8", errors="replace"))
                    if monotonic() > deadline:
                        raise RuntimeError("Task interpreter did not become ready")
                    sleep(.02)
                startup = self._read_payload(ready)
                if startup.get("task_id") != task_id or type(startup.get("pid")) is not int:
                    raise ValueError("Invalid task bootstrap identity")
                tree = TaskProcessTree(process, startup["pid"])
                self._children.add(tree)
                process.stdin.write((task_id + "\n").encode())
                process.stdin.close()
            code = process.wait()
        finally:
            if tree:
                tree.close()  # Kill remaining descendants before waiting for pipe EOF.
                with self._lock:
                    self._children.discard(tree)
            if process:
                if process.stdin and not process.stdin.closed:
                    process.stdin.close()
                if process.poll() is None:
                    process.terminate()
                process.wait(timeout=10)
                if reader:
                    reader.join(5)
                process.stdout.close()
        return code, tail.decode("utf-8", errors="replace")

    @staticmethod
    def _read_payload(path):
        with path.open("rb") as stream:
            body = stream.read(4 * 1024 * 1024 + 1)
        if len(body) > 4 * 1024 * 1024:
            raise ValueError("Dashboard task result is too large")
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise ValueError("Invalid task payload")
        return payload

    def _owned_record(self, claim_path, task_id):
        if not claim_path.exists():
            return None
        import re

        claim = self._read_payload(claim_path)
        if claim.get("task_id") != task_id or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", claim.get("run_id", "")):
            raise ValueError("Invalid task run ownership")
        path = self.registry.runs_root / claim["run_id"]
        info = path.lstat()
        if (info.st_dev, info.st_ino) != (claim.get("device"), claim.get("inode")):
            raise ValueError("Task run directory identity changed")
        if path.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("Task run directory is a link")
        # Registry validation retains the established path/status safety checks.
        record = next((r for r in self.registry.list_runs()
                       if r.run_id == claim["run_id"] and r.run_dir.resolve() == path.resolve()), None)
        if record is None and (path / "run_status.json").exists():
            raise ValueError("Task run status could not be read safely")
        return record

    def _failed(self, error, claim, task_id, operation, exit_code, log):
        from .development_diagnostics import DevelopmentDiagnostics
        from .formal_run import RunFailure

        message = f"{type(error).__name__}: {error}"
        record = None
        try:
            record = self._owned_record(claim, task_id)
            if record and record.status == "running":
                metadata = ({"kind": record.kind, "change_id": record.change_id,
                             "model_digest": record.model_digest} if record.version else {})
                record = self.registry.write_status(
                    record.run_dir, status="failed", scenario_id=record.scenario_id,
                    message=message, output_dir=record.output_dir, report_dir=record.report_dir,
                    report_index=record.report_index, engine_id=record.engine_id, **metadata,
                )
        except Exception as status_error:
            message += f"\nRun status could not be confirmed/saved: {status_error}"
        state = record.status if record and record.status != "running" else "failed"
        if state != "failed":
            message = f"Saved run status: {state}. Worker communication failed.\n" + message
        outcome = {"state": state, "message": message, "run_id": record.run_id if record else None}
        try:
            failure = RunFailure("task_process", error)
            failure.diagnostic["diagnostic_id"] = "task-" + task_id
            details = DevelopmentDiagnostics(self.context["project"])(failure, {
                "task_id": task_id, "run_id": outcome["run_id"], "operation": operation,
                "exit_code": exit_code, "output_tail": log,
            })
            outcome["diagnostic"] = {"details": details}
        except Exception as diagnostic_error:
            outcome["message"] += f"\nDiagnostic could not be saved: {diagnostic_error}"
        return outcome

    def close(self):
        with self._lock:
            self._closed = True
            for child in self._children:
                child.close()
