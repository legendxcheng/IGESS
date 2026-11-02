"""Exercise process/notification handoff without running a Fish simulation."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest


SCRIPT = Path(__file__).with_name("run_background.py")
spec = importlib.util.spec_from_file_location("fish_background", SCRIPT)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


def job(tmp_path, output, exit_code=0, delay=0):
    command = [sys.executable, "-c", (
        f"import time; time.sleep({delay!r}); print({output!r}); raise SystemExit({exit_code})"
    )]
    helper.write_json(tmp_path / "job.json", {
        "command": command, "cwd": str(tmp_path), "scenario": "fixture",
    })


@pytest.mark.parametrize("output,exit_code,expected", [
    (json.dumps({"ok": True, "result": {"run_id": "fixture-run"}}), 0, "command_succeeded"),
    (json.dumps({"ok": False}), 0, "command_failed"),
    (json.dumps({"ok": True}), 1, "command_failed"),
    ("invalid JSON", 0, "command_failed"),
])
def test_completion_is_persisted_before_notification(tmp_path, monkeypatch, output, exit_code, expected):
    job(tmp_path, output, exit_code)
    messages = []

    def notification(message):
        receipt = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
        assert receipt["state"] == expected
        assert receipt["exit_code"] == exit_code
        messages.append(message)

    monkeypatch.setattr(helper, "notify", notification)
    helper.run_worker(tmp_path)
    receipt = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert receipt["notification"] == "dismissed"
    assert len(messages) == 1
    assert str(tmp_path) in messages[0]
    assert "可以唤醒 Agent" in messages[0]
    if expected == "command_succeeded":
        assert receipt["run_id"] == "fixture-run"


def test_notification_failure_preserves_cli_outcome(tmp_path, monkeypatch):
    job(tmp_path, '{"ok": true}')

    def unavailable(message):
        raise OSError("desktop unavailable")

    monkeypatch.setattr(helper, "notify", unavailable)
    helper.run_worker(tmp_path)
    receipt = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert receipt["state"] == "command_succeeded"
    assert receipt["notification"] == "failed"


@pytest.mark.skipif(os.name != "nt", reason="Windows detachment contract")
def test_worker_survives_launcher_exit(tmp_path):
    job(tmp_path, '{"ok": true}', delay=1)
    # Use the real worker, with only the UI replaced by a recorded notification.
    worker = tmp_path / "worker.py"
    worker.write_text(
        "import runpy\nfrom pathlib import Path\n"
        f"module = runpy.run_path({str(SCRIPT)!r})\n"
        f"worker = module['run_worker']\n"
        f"worker.__globals__['notify'] = lambda message: Path({str(tmp_path / 'notified.txt')!r}).write_text(message, encoding='utf-8')\n"
        f"worker(Path({str(tmp_path)!r}))\n", encoding="utf-8",
    )
    launcher = (
        "import subprocess, sys\n"
        f"subprocess.Popen([sys.executable, {str(worker)!r}], "
        "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, "
        "creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP, close_fds=True)\n"
    )
    subprocess.run([sys.executable, "-c", launcher], check=True, timeout=5)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        receipt_path = tmp_path / "status.json"
        if receipt_path.exists():
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            if receipt.get("notification") == "dismissed":
                break
        time.sleep(0.1)
    else:
        pytest.fail("Detached worker did not complete after launcher exited")
    assert receipt["state"] == "command_succeeded"
    assert "可以唤醒 Agent" in (tmp_path / "notified.txt").read_text(encoding="utf-8")
