"""Fresh-process restarts for the development Dashboard (never shell commands)."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys


RESTART_EXIT_CODE = 75


def supervise_dashboard(**options):
    # Resolve an ephemeral port once, so subsequent generations retain the URL.
    if options["port"] == 0:
        with socket.socket() as listener:
            listener.bind((options["host"], 0))
            options["port"] = listener.getsockname()[1]
    command = [sys.executable, "-m", "igess.dashboard_process", json.dumps(options, default=str)]
    while True:
        process = subprocess.Popen(
            command,
            stdout=sys.stdout,
            stderr=sys.stderr,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        try:
            code = process.wait()
        except KeyboardInterrupt:
            return
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait()
        if code != RESTART_EXIT_CODE:
            if code:
                raise RuntimeError(f"Dashboard process exited with code {code}; check the server console.")
            return


if __name__ == "__main__":
    from .dashboard import _serve_dashboard_worker

    sys.exit(RESTART_EXIT_CODE if _serve_dashboard_worker(**json.loads(sys.argv[1])) else 0)
