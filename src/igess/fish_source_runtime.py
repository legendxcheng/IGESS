"""Client for Fish's source-owned Lua simulation session."""

from __future__ import annotations

import json
import queue
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any


class FishSourceRuntimeError(RuntimeError):
    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        super().__init__(f"{code}: {detail}" if detail else code)


class FishSourceRuntime:
    """One isolated source Lua process for one Fish simulation run."""

    def __init__(
        self,
        project_root: str | Path,
        data_root: str | Path,
        *,
        lua_executable: str = "lua55",
        expected_lua_version: str = "Lua 5.5",
        timeout_seconds: float = 30.0,
    ) -> None:
        self.project_root = Path(project_root).resolve(strict=True)
        self.data_root = Path(data_root).resolve(strict=True)
        self.lua_executable = lua_executable
        self.expected_lua_version = expected_lua_version
        self.timeout_seconds = timeout_seconds
        self._process: subprocess.Popen[str] | None = None
        self._responses: queue.Queue[str] = queue.Queue()
        self._stderr = None

    def __enter__(self) -> FishSourceRuntime:
        executable = shutil.which(self.lua_executable)
        if executable is None:
            raise FishSourceRuntimeError("simulation_lua_unavailable")
        entry = self.project_root / "simulation" / "cli.lua"
        if not entry.is_file():
            raise FishSourceRuntimeError("simulation_host_unavailable")
        self._stderr = tempfile.TemporaryFile(mode="w+t", encoding="utf-8")
        try:
            self._process = subprocess.Popen(
                [executable, str(entry)],
                cwd=self.project_root,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self._stderr,
                text=True,
                encoding="utf-8",
                bufsize=1,
            )
        except OSError as exc:
            self._stderr.close()
            self._stderr = None
            raise FishSourceRuntimeError("simulation_launch_failed", str(exc)) from exc
        threading.Thread(target=self._read_stdout, daemon=True).start()
        try:
            capabilities = self.request({"op": "capabilities"})
            if capabilities.get("protocol") != 1:
                raise FishSourceRuntimeError("simulation_protocol_unsupported")
            if capabilities.get("luaVersion") != self.expected_lua_version:
                raise FishSourceRuntimeError(
                    "simulation_lua_version_mismatch",
                    str(capabilities.get("luaVersion")),
                )
        except BaseException:
            self.close()
            raise
        return self

    def _read_stdout(self) -> None:
        process = self._process
        assert process is not None and process.stdout is not None
        for line in process.stdout:
            self._responses.put(line)
        self._responses.put("")

    def request(self, payload: dict[str, Any]) -> dict[str, Any]:
        process = self._process
        if process is None or process.stdin is None:
            raise FishSourceRuntimeError("simulation_session_closed")
        try:
            process.stdin.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
            process.stdin.flush()
        except OSError as exc:
            raise FishSourceRuntimeError("simulation_transport_failed", str(exc)) from exc
        try:
            line = self._responses.get(timeout=self.timeout_seconds)
        except queue.Empty as exc:
            process.kill()
            raise FishSourceRuntimeError("simulation_request_timeout") from exc
        if not line:
            raise FishSourceRuntimeError("simulation_host_exited")
        try:
            response = json.loads(line)
        except json.JSONDecodeError as exc:
            raise FishSourceRuntimeError("simulation_protocol_invalid", line[:120]) from exc
        if not isinstance(response, dict) or type(response.get("ok")) is not bool:
            raise FishSourceRuntimeError("simulation_protocol_invalid")
        if not response["ok"]:
            raise FishSourceRuntimeError(str(response.get("code", "simulation_failed")))
        value = response.get("value")
        if not isinstance(value, dict):
            raise FishSourceRuntimeError("simulation_protocol_invalid")
        return value

    def create(self, *, start_at: int, initial_state: dict[str, Any] | None = None) -> dict[str, Any]:
        command: dict[str, Any] = {
            "op": "create", "startAt": start_at, "dataRoot": str(self.data_root)
        }
        if initial_state is not None:
            command["initialState"] = initial_state
        return self.request(command)

    def close(self) -> None:
        process = self._process
        self._process = None
        if process is not None:
            if process.stdin is not None:
                process.stdin.close()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            if process.stdout is not None:
                process.stdout.close()
        if self._stderr is not None:
            self._stderr.close()
            self._stderr = None

    def __exit__(self, *_exc: object) -> None:
        self.close()
