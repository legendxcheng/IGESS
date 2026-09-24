"""Client for Fish's source-owned Lua simulation session."""

from __future__ import annotations

import hashlib
import json
import queue
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any, Self


class FishSourceRuntimeError(RuntimeError):
    def __init__(self, code: str, detail: str | dict[str, Any] = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


class FishSourceRejection(FishSourceRuntimeError):
    """A valid game/session command refused by the source-owned host."""


def source_code_digest(project_root: str | Path) -> str:
    root = Path(project_root)
    digest = hashlib.sha256()
    paths = sorted((root / "proj" / "Script").rglob("*.lua"))
    paths += sorted((root / "simulation").rglob("*.lua"))
    for path in paths:
        contents = path.read_bytes()
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(contents).to_bytes(8, "big"))
        digest.update(contents)
    return digest.hexdigest()


def data_snapshot_digest(data_root: str | Path) -> str:
    root = Path(data_root)
    digest = hashlib.sha256()
    for path in sorted(root.glob("*.json")):
        name = path.name.encode("utf-8")
        contents = path.read_bytes()
        digest.update(len(name).to_bytes(4, "big"))
        digest.update(name)
        digest.update(len(contents).to_bytes(8, "big"))
        digest.update(contents)
    return digest.hexdigest()


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
        self._source_snapshot: tempfile.TemporaryDirectory[str] | None = None
        self.source_digest: str | None = None
        self.data_digest: str | None = None
        self._frozen_data_root: Path | None = None
        self.capabilities: dict[str, Any] | None = None

    def _freeze_source(self) -> Path:
        snapshot = tempfile.TemporaryDirectory(prefix="igess-fish-lua-")
        frozen_root = Path(snapshot.name)
        try:
            shutil.copytree(
                self.project_root / "proj" / "Script",
                frozen_root / "proj" / "Script",
            )
            shutil.copytree(
                self.project_root / "simulation",
                frozen_root / "simulation",
            )
            frozen_data_root = frozen_root / "selected_data"
            shutil.copytree(self.data_root, frozen_data_root)
            self.source_digest = source_code_digest(frozen_root)
            self.data_digest = data_snapshot_digest(frozen_data_root)
            self._frozen_data_root = frozen_data_root
            self._source_snapshot = snapshot
            return frozen_root
        except (OSError, shutil.Error) as exc:
            snapshot.cleanup()
            raise FishSourceRuntimeError(
                "simulation_source_snapshot_failed", str(exc)
            ) from exc

    def __enter__(self) -> Self:
        executable = shutil.which(self.lua_executable)
        if executable is None:
            raise FishSourceRuntimeError("simulation_lua_unavailable")
        entry = self.project_root / "simulation" / "cli.lua"
        if not entry.is_file():
            raise FishSourceRuntimeError("simulation_host_unavailable")
        frozen_root = self._freeze_source()
        entry = frozen_root / "simulation" / "cli.lua"
        self._stderr = tempfile.TemporaryFile(mode="w+b")
        try:
            self._process = subprocess.Popen(
                [executable, str(entry)],
                cwd=frozen_root,
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
            assert self._source_snapshot is not None
            self._source_snapshot.cleanup()
            self._source_snapshot = None
            raise FishSourceRuntimeError("simulation_launch_failed", str(exc)) from exc
        threading.Thread(target=self._read_stdout, daemon=True).start()
        try:
            capabilities = self.request({"op": "capabilities"})
            if capabilities.get("protocol") != 2:
                raise FishSourceRuntimeError("simulation_protocol_unsupported")
            if capabilities.get("luaVersion") != self.expected_lua_version:
                raise FishSourceRuntimeError(
                    "simulation_lua_version_mismatch",
                    str(capabilities.get("luaVersion")),
                )
            if capabilities.get("checkpointFormat") != 1:
                raise FishSourceRuntimeError("simulation_checkpoint_version_unsupported")
            self.capabilities = capabilities
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

    def _stderr_tail(self) -> str:
        if self._stderr is None:
            return ""
        self._stderr.seek(0, 2)
        end = self._stderr.tell()
        self._stderr.seek(max(0, end - 4096))
        return self._stderr.read().decode("utf-8", errors="replace").strip()

    def request(
        self, payload: dict[str, Any], *, timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        process = self._process
        if process is None or process.stdin is None:
            raise FishSourceRuntimeError("simulation_session_closed")
        try:
            process.stdin.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
            process.stdin.flush()
        except OSError as exc:
            raise FishSourceRuntimeError("simulation_transport_failed", str(exc)) from exc
        try:
            line = self._responses.get(
                timeout=self.timeout_seconds if timeout_seconds is None else timeout_seconds
            )
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
            code = response.get("code")
            kind = response.get("kind")
            detail = response.get("detail", "")
            if not isinstance(code, str) or kind not in ("rejected", "fault"):
                raise FishSourceRuntimeError("simulation_protocol_invalid")
            if not isinstance(detail, (str, dict)):
                raise FishSourceRuntimeError("simulation_protocol_invalid")
            if kind == "rejected":
                raise FishSourceRejection(code, detail)
            log_tail = self._stderr_tail()
            if log_tail:
                detail = {"source_detail": detail, "stderr_tail": log_tail}
            raise FishSourceRuntimeError(code, detail)
        value = response.get("value")
        if not isinstance(value, dict):
            raise FishSourceRuntimeError("simulation_protocol_invalid")
        return value

    def create(
        self, *, start_at: int,
        initial_state: dict[str, Any] | None = None,
        random_seed: int = 0,
        in_fishing_area: bool = False,
        fast_advance: bool = False,
    ) -> dict[str, Any]:
        if self.source_digest is None:
            raise FishSourceRuntimeError("simulation_session_closed")
        assert self._frozen_data_root is not None
        command: dict[str, Any] = {
            "op": "create", "startAt": start_at, "dataRoot": str(self._frozen_data_root),
            "codeDigest": self.source_digest,
            "randomSeed": random_seed,
            "inFishingArea": in_fishing_area,
            "fastAdvance": fast_advance,
        }
        if initial_state is not None:
            command["initialState"] = initial_state
        return self.request(command)

    def checkpoint(self) -> dict[str, Any]:
        return self.request({"op": "checkpoint"})

    def restore(self, checkpoint: dict[str, Any]) -> dict[str, Any]:
        if self.source_digest is None:
            raise FishSourceRuntimeError("simulation_session_closed")
        assert self._frozen_data_root is not None
        history = checkpoint.get("history")
        replay_entries = len(history) if isinstance(history, list) else 0
        replay_timeout = max(self.timeout_seconds, min(1800.0, 30.0 + replay_entries * 0.1))
        return self.request({
            "op": "restore", "dataRoot": str(self._frozen_data_root),
            "codeDigest": self.source_digest,
            "checkpoint": checkpoint,
        }, timeout_seconds=replay_timeout)

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
        if self._source_snapshot is not None:
            self._source_snapshot.cleanup()
            self._source_snapshot = None
            self._frozen_data_root = None
        self.capabilities = None

    def __exit__(self, *_exc: object) -> None:
        self.close()
