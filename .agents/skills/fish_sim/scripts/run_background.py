"""Detach an IGESS CLI run and notify the local Windows user when it ends."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from datetime import datetime, timezone
from uuid import uuid4


def write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def notify(message: str) -> None:
    # The receipt is already terminal before this dialog waits for dismissal.
    result = ctypes.windll.user32.MessageBoxW(None, message, "Fish 跑测已结束", 0x40 | 0x10000)
    if not result:
        raise OSError("Windows could not display the completion dialog")


def run_worker(job_dir: Path) -> None:
    job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    state = {"state": "starting", "worker_pid": os.getpid(), "job_dir": str(job_dir)}
    try:
        with (job_dir / "response.json").open("w", encoding="utf-8") as stdout, \
                (job_dir / "stderr.log").open("w", encoding="utf-8") as stderr:
            process = subprocess.Popen(
                job["command"], cwd=job["cwd"], stdin=subprocess.DEVNULL,
                stdout=stdout, stderr=stderr,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            state.update(state="running", cli_pid=process.pid)
            write_json(job_dir / "status.json", state)
            state["exit_code"] = process.wait()
        response = json.loads((job_dir / "response.json").read_text(encoding="utf-8-sig"))
        state["state"] = (
            "command_succeeded" if state["exit_code"] == 0 and response.get("ok") is True
            else "command_failed"
        )
        state["code"] = response.get("code")
        result = response.get("result") or {}
        state.update({key: result.get(key) for key in ("run_id", "output_dir", "report_index")})
    except Exception as exc:
        state.update(state="command_failed", error=f"{type(exc).__name__}: {exc}")
    state["finished_at"] = datetime.now(timezone.utc).isoformat()
    state["notification"] = "pending"
    write_json(job_dir / "status.json", state)
    outcome = "命令成功，待核验报告" if state["state"] == "command_succeeded" else "执行失败，待排查"
    try:
        notify(f"{job['scenario']}：{outcome}。\n可以唤醒 Agent 了，请回复：分析这次跑测。\n任务目录：{job_dir}")
        state["notification"] = "dismissed"
    except Exception as exc:
        state.update(notification="failed", notification_error=str(exc))
    write_json(job_dir / "status.json", state)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--scenario")
    parser.add_argument("--project", default="projects/fish_source")
    parser.add_argument("--jobs-root", default=".scratch/fish-background")
    parser.add_argument("--runs-root")
    resume = parser.add_mutually_exclusive_group()
    resume.add_argument("--resume-run-id")
    resume.add_argument("--checkpoint-in")
    parser.add_argument("--until-seconds", type=float)
    args = parser.parse_args()
    if args.worker:
        run_worker(args.worker.resolve())
        return 0
    if os.name != "nt":
        parser.error("This helper requires a Windows interactive desktop")
    if not args.scenario:
        parser.error("--scenario is required")
    command = [sys.executable, "-m", "igess.cli", "model", "simulate",
               "--project", args.project, "--scenario", args.scenario, "--json"]
    for name in ("runs_root", "resume_run_id", "checkpoint_in", "until_seconds"):
        value = getattr(args, name)
        if value is not None:
            command.extend(["--" + name.replace("_", "-"), str(value)])
    job_dir = Path(args.jobs_root).resolve() / (
        datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid4().hex[:8]
    )
    job_dir.mkdir(parents=True)
    write_json(job_dir / "job.json", {
        "command": command, "cwd": str(Path.cwd()), "scenario": args.scenario,
    })
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "utf-8"
    with (job_dir / "worker.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--worker", str(job_dir)],
            stdin=subprocess.DEVNULL, stdout=log, stderr=log, env=environment,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
        )
    # Bounded startup acknowledgement only; never wait here for the simulation.
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        receipt = job_dir / "status.json"
        if receipt.exists():
            state = json.loads(receipt.read_text(encoding="utf-8"))
            print(json.dumps(state, ensure_ascii=False))
            return 1 if state["state"] == "command_failed" else 0
        if process.poll() is not None:
            break
        time.sleep(0.1)
    print(json.dumps({
        "state": "startup_unconfirmed", "worker_pid": process.pid,
        "job_dir": str(job_dir), "message": "Inspect worker.log and status.json; do not launch a duplicate run.",
    }, ensure_ascii=False))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
