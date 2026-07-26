"""Watch model inputs and publish the latest formal report in one browser tab."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import partial
import hashlib
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path, PurePosixPath
import sys
import threading
import time
from typing import Any
from urllib.parse import unquote, urlsplit
import webbrowser

import yaml

from .response import CommandResponse
from .service import AuthoringService


_PROJECT_SOURCE_SUFFIXES = frozenset({".csv", ".tsv", ".xls", ".xlsx"})
_FISH_ARTIFACTS = (
    "behavior_progression.csv",
    "behavior_progression.json",
    "luck_progression.csv",
    "luck_progression.json",
)
_STANDARD_ARTIFACTS = (
    "analysis.json",
    "analysis.md",
    "events.csv",
    "events.json",
    "final_checkpoint.json",
    "run_manifest.json",
    "timeline.csv",
    "timeline.json",
)


@dataclass(frozen=True, slots=True)
class LiveRun:
    """Validated paths and source identity for one published run."""

    run_id: str
    scenario_id: str
    model_digest: str
    output_dir: Path
    report_index: Path


class LiveReportState:
    """Thread-safe state shared by the watcher and the local HTTP server."""

    def __init__(self, scenario_id: str) -> None:
        self._lock = threading.Lock()
        self._report_root: Path | None = None
        self._payload: dict[str, Any] = {
            "revision": 0,
            "status": "starting",
            "message": "正在启动数值监听器…",
            "scenario_id": scenario_id,
            "run_id": None,
            "model_digest": None,
            "changed_files": [],
            "updated_at": _utc_now(),
            "report_url": None,
        }

    def public_payload(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._payload)

    def report_root(self) -> Path | None:
        with self._lock:
            return self._report_root

    def set_status(
        self,
        status: str,
        message: str,
        *,
        changed_files: Sequence[str] = (),
    ) -> None:
        with self._lock:
            self._payload.update(
                status=status,
                message=message,
                changed_files=list(changed_files),
                updated_at=_utc_now(),
            )

    def publish(self, run: LiveRun) -> None:
        with self._lock:
            self._report_root = run.report_index.parent
            self._payload.update(
                revision=int(self._payload["revision"]) + 1,
                status="success",
                message="报表已更新",
                scenario_id=run.scenario_id,
                run_id=run.run_id,
                model_digest=run.model_digest,
                changed_files=[],
                updated_at=_utc_now(),
                report_url="/report/index.html",
            )


class LiveReportServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class _LiveReportHandler(BaseHTTPRequestHandler):
    server_version = "IGESSLiveReport/1"

    def __init__(self, *args: Any, state: LiveReportState, **kwargs: Any) -> None:
        self._state = state
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self._dispatch(head_only=False)

    def do_HEAD(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self._dispatch(head_only=True)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _dispatch(self, *, head_only: bool) -> None:
        path = urlsplit(self.path).path
        if path == "/":
            self._send_bytes(
                _LIVE_PAGE.encode("utf-8"),
                "text/html; charset=utf-8",
                head_only=head_only,
            )
            return
        if path == "/api/status":
            body = json.dumps(
                self._state.public_payload(),
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            self._send_bytes(
                body,
                "application/json; charset=utf-8",
                head_only=head_only,
            )
            return
        if path == "/report" or path.startswith("/report/"):
            self._send_report_file(path, head_only=head_only)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def _send_report_file(self, request_path: str, *, head_only: bool) -> None:
        report_root = self._state.report_root()
        if report_root is None:
            self.send_error(HTTPStatus.SERVICE_UNAVAILABLE, "Report is not ready")
            return
        suffix = request_path.removeprefix("/report").lstrip("/") or "index.html"
        relative = PurePosixPath(unquote(suffix))
        if relative.is_absolute() or ".." in relative.parts:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            root = report_root.resolve(strict=True)
            target = root.joinpath(*relative.parts).resolve(strict=True)
            target.relative_to(root)
        except (OSError, RuntimeError, ValueError):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            body = target.read_bytes()
        except OSError:
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in {
            "application/javascript",
            "application/json",
        }:
            content_type += "; charset=utf-8"
        self._send_bytes(body, content_type, head_only=head_only)

    def _send_bytes(self, body: bytes, content_type: str, *, head_only: bool) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if not head_only:
            self.wfile.write(body)


def start_live_server(
    state: LiveReportState,
    *,
    port: int = 0,
) -> tuple[LiveReportServer, threading.Thread, str]:
    """Start a loopback-only report server and return its public URL."""

    handler = partial(_LiveReportHandler, state=state)
    server = LiveReportServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=server.serve_forever, name="igess-live-report")
    thread.daemon = True
    thread.start()
    actual_port = int(server.server_address[1])
    return server, thread, f"http://127.0.0.1:{actual_port}/"


def discover_watch_files(project_root: str | Path) -> tuple[Path, ...]:
    """Discover local sources and configured external Fish production inputs."""

    root = Path(project_root).expanduser().resolve()
    config = root / "economy.yaml"
    files: set[Path] = {config}
    datas = root / "Datas"
    if datas.is_dir():
        files.update(
            path
            for path in datas.rglob("*")
            if path.is_file()
            and not path.name.startswith("~$")
            and path.suffix.lower() in _PROJECT_SOURCE_SUFFIXES
        )

    try:
        raw = yaml.safe_load(config.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        raw = None
    engine = raw.get("engine") if isinstance(raw, Mapping) else None
    if not isinstance(engine, Mapping):
        return tuple(sorted(files, key=_path_key))

    schema_value = engine.get("python_schema")
    if isinstance(schema_value, str) and schema_value:
        files.add(_configured_path(root, schema_value))

    data_root_value = engine.get("data_root")
    if isinstance(data_root_value, str) and data_root_value:
        data_root = _configured_path(root, data_root_value)
        required = engine.get("required_tables")
        if isinstance(required, Sequence) and not isinstance(required, (str, bytes)):
            table_names = sorted(
                {name for name in required if isinstance(name, str) and name}
            )
        else:
            table_names = []
        if table_names:
            files.update(data_root / f"{name}.json" for name in table_names)
        elif data_root.is_dir():
            files.update(data_root.glob("*.json"))

    return tuple(sorted(files, key=_path_key))


def fingerprint_files(paths: Sequence[Path]) -> tuple[tuple[str, str], ...]:
    """Return a content-based fingerprint that tolerates files mid-export."""

    return tuple((_path_key(path), _fingerprint_file(path)) for path in paths)


def changed_files(
    before: Sequence[tuple[str, str]],
    after: Sequence[tuple[str, str]],
) -> tuple[str, ...]:
    """Describe the paths whose content identity changed."""

    left = dict(before)
    right = dict(after)
    return tuple(
        path
        for path in sorted(set(left) | set(right), key=str.casefold)
        if left.get(path) != right.get(path)
    )


def validate_live_run(
    response: CommandResponse,
    *,
    project_root: str | Path,
    scenario_id: str,
) -> LiveRun:
    """Require the formal artifacts and production provenance before publishing."""

    if not response.ok:
        raise RuntimeError(f"{response.code}: {response.message}")
    result = response.result
    run_id = _required_text(result, "run_id")
    actual_scenario = _required_text(result, "scenario_id")
    if actual_scenario != scenario_id:
        raise RuntimeError(
            f"scenario mismatch: expected {scenario_id}, got {actual_scenario}"
        )
    model_digest = _required_text(result, "model_digest")
    output_dir = Path(_required_text(result, "output_dir")).resolve()
    report_index = Path(_required_text(result, "report_index")).resolve()
    if report_index.name != "index.html" or not report_index.is_file():
        raise RuntimeError(f"missing report index: {report_index}")
    if not output_dir.is_dir():
        raise RuntimeError(f"missing output directory: {output_dir}")
    for name in _STANDARD_ARTIFACTS:
        if not (output_dir / name).is_file():
            raise RuntimeError(f"missing formal artifact: {output_dir / name}")

    manifest_path = output_dir / "run_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"invalid run manifest: {type(error).__name__}") from error
    if not isinstance(manifest, Mapping):
        raise RuntimeError("invalid run manifest: root must be an object")
    _require_manifest_value(manifest, "scenario_id", actual_scenario)
    _require_manifest_value(manifest, "model_digest", model_digest)

    declared = manifest.get("artifacts")
    if not isinstance(declared, Sequence) or isinstance(declared, (str, bytes)):
        raise RuntimeError("invalid run manifest: artifacts must be a list")
    for name in declared:
        if not isinstance(name, str) or not (output_dir / name).is_file():
            raise RuntimeError(f"manifest artifact is missing or invalid: {name!r}")

    if manifest.get("engine_id") == "fish":
        for name in _FISH_ARTIFACTS:
            if not (output_dir / name).is_file():
                raise RuntimeError(f"missing Fish progression artifact: {output_dir / name}")
        _validate_fish_provenance(manifest, Path(project_root).resolve())

    return LiveRun(
        run_id=run_id,
        scenario_id=actual_scenario,
        model_digest=model_digest,
        output_dir=output_dir,
        report_index=report_index,
    )


def run_live_report(
    project_root: str | Path,
    scenario_id: str,
    *,
    poll_seconds: float = 0.5,
    debounce_seconds: float = 1.0,
    port: int = 0,
    open_browser: bool = True,
    service_factory: Callable[[str | Path], AuthoringService] = AuthoringService,
    stop_event: threading.Event | None = None,
) -> int:
    """Run immediately, then repeat whenever watched inputs settle after a change."""

    root = Path(project_root).expanduser().resolve()
    state = LiveReportState(scenario_id)
    try:
        server, thread, url = start_live_server(state, port=port)
    except OSError as error:
        print(
            f"Could not start live report server: {type(error).__name__}: {error}",
            file=sys.stderr,
            flush=True,
        )
        return 1
    print(f"Live report: {url}", flush=True)
    print(f"Scenario: {scenario_id}", flush=True)
    print("Watching numeric inputs; press Ctrl+C to stop.", flush=True)
    stopper = stop_event or threading.Event()
    try:
        if open_browser:
            webbrowser.open(url)

        service = service_factory(root)
        watched = discover_watch_files(root)
        baseline = fingerprint_files(watched)
        _print_watched_inputs(watched)
        before_run = baseline
        _simulate_and_publish(service, state, root, scenario_id, reason="initial run")
        watched = discover_watch_files(root)
        baseline = fingerprint_files(watched)
        pending_since = time.monotonic() if baseline != before_run else None

        while not stopper.wait(poll_seconds):
            current_watched = discover_watch_files(root)
            current = fingerprint_files(current_watched)
            differences = changed_files(baseline, current)
            if differences:
                watched = current_watched
                baseline = current
                pending_since = time.monotonic()
                display = _display_paths(differences, root)
                state.set_status(
                    "pending",
                    f"检测到 {len(differences)} 个输入变化，等待导出稳定…",
                    changed_files=display,
                )
                print(f"Change detected: {', '.join(display)}", flush=True)
                continue
            if pending_since is None:
                continue
            if time.monotonic() - pending_since < debounce_seconds:
                continue

            before_run = baseline
            _simulate_and_publish(
                service,
                state,
                root,
                scenario_id,
                reason="inputs changed",
            )
            watched = discover_watch_files(root)
            after_run = fingerprint_files(watched)
            if after_run != before_run:
                display = _display_paths(changed_files(before_run, after_run), root)
                state.set_status(
                    "pending",
                    "模拟期间输入再次变化，正在等待下一轮…",
                    changed_files=display,
                )
                pending_since = time.monotonic()
            else:
                pending_since = None
            baseline = after_run
    except KeyboardInterrupt:
        print("Stopped live report watcher.", flush=True)
    except Exception as error:
        print(
            f"Live report watcher failed: {type(error).__name__}: {error}",
            file=sys.stderr,
            flush=True,
        )
        return 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    return 0


def _simulate_and_publish(
    service: AuthoringService,
    state: LiveReportState,
    root: Path,
    scenario_id: str,
    *,
    reason: str,
) -> bool:
    state.set_status("running", f"正在运行 {scenario_id}（{reason}）…")
    started = time.monotonic()
    print(f"Running {scenario_id} ({reason})...", flush=True)
    response = service.simulate(scenario_id)
    try:
        run = validate_live_run(response, project_root=root, scenario_id=scenario_id)
    except (OSError, RuntimeError, ValueError) as error:
        state.set_status("error", f"模拟失败：{error}")
        print(f"Simulation failed: {error}", flush=True)
        return False
    elapsed = time.monotonic() - started
    state.publish(run)
    print(
        f"Published {run.run_id} in {elapsed:.2f}s: {run.report_index}",
        flush=True,
    )
    return True


def _validate_fish_provenance(manifest: Mapping[str, Any], project_root: Path) -> None:
    config = project_root / "economy.yaml"
    try:
        raw = yaml.safe_load(config.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise RuntimeError(f"cannot validate Fish provenance: {type(error).__name__}") from error
    engine = raw.get("engine") if isinstance(raw, Mapping) else None
    if not isinstance(engine, Mapping) or not engine.get("production_data", False):
        return
    if manifest.get("production_data") is not True:
        raise RuntimeError("Fish run did not record production_data=true")
    if manifest.get("matches_production_data") is not True:
        raise RuntimeError("Fish run did not match the production snapshot")

    data_root_value = engine.get("data_root")
    if not isinstance(data_root_value, str) or not data_root_value:
        raise RuntimeError("Fish production data_root is missing from economy.yaml")
    expected_root = _configured_path(project_root, data_root_value)
    actual_root = manifest.get("data_root")
    if not isinstance(actual_root, str) or Path(actual_root).resolve() != expected_root:
        raise RuntimeError(
            f"Fish data_root mismatch: expected {expected_root}, got {actual_root}"
        )

    schema_value = engine.get("python_schema")
    if not isinstance(schema_value, str) or not schema_value:
        raise RuntimeError("Fish production python_schema is missing from economy.yaml")
    expected_schema = _configured_path(project_root, schema_value)
    loader_files = manifest.get("loader_files")
    if not isinstance(loader_files, Sequence) or isinstance(loader_files, (str, bytes)):
        raise RuntimeError("Fish run manifest has no loader_files list")
    loader_paths = {
        Path(item["file"]).resolve()
        for item in loader_files
        if isinstance(item, Mapping) and isinstance(item.get("file"), str)
    }
    if expected_schema not in loader_paths:
        raise RuntimeError(f"Fish schema provenance is missing: {expected_schema}")


def _configured_path(project_root: Path, value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = project_root / path
    return path.resolve()


def _fingerprint_file(path: Path) -> str:
    try:
        before = path.stat()
        if not path.is_file():
            return "!not-file"
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        after = path.stat()
    except OSError as error:
        return f"!{type(error).__name__}"
    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        return f"!unstable:{before.st_size}:{before.st_mtime_ns}"
    return f"sha256:{digest.hexdigest()}"


def _required_text(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise RuntimeError(f"simulation response is missing {key}")
    return item


def _require_manifest_value(
    manifest: Mapping[str, Any], key: str, expected: str
) -> None:
    actual = manifest.get(key)
    if actual != expected:
        raise RuntimeError(
            f"manifest {key} mismatch: expected {expected}, got {actual}"
        )


def _display_paths(paths: Sequence[str], project_root: Path) -> tuple[str, ...]:
    display: list[str] = []
    for value in paths[:8]:
        path = Path(value)
        try:
            display.append(str(path.relative_to(project_root)))
        except ValueError:
            display.append(str(path))
    if len(paths) > 8:
        display.append(f"… +{len(paths) - 8}")
    return tuple(display)


def _print_watched_inputs(paths: Sequence[Path]) -> None:
    external = sum(1 for path in paths if "igess_export" in _path_key(path).casefold())
    print(f"Watching {len(paths)} files ({external} production snapshot files).", flush=True)


def _path_key(path: Path) -> str:
    try:
        return str(path.resolve())
    except (OSError, RuntimeError):
        return str(path.absolute())


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


_LIVE_PAGE = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>IGESS Fish 实时报表</title>
  <style>
    :root { color-scheme: dark; font-family: Inter, "Microsoft YaHei", sans-serif; }
    * { box-sizing: border-box; }
    body { margin: 0; background: #0b1020; color: #e8eefc; overflow: hidden; }
    header { height: 64px; padding: 10px 18px; display: flex; align-items: center; gap: 16px;
      border-bottom: 1px solid #263252; background: #11182b; }
    .dot { width: 10px; height: 10px; border-radius: 50%; background: #8ea0c6; flex: none; }
    [data-status="running"] .dot, [data-status="pending"] .dot { background: #f2b84b; }
    [data-status="success"] .dot { background: #4fd29c; }
    [data-status="error"] .dot { background: #ff6b7d; }
    .summary { min-width: 0; flex: 1; }
    #message { font-weight: 700; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    #meta { color: #9bacce; font-size: 12px; margin-top: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    a { color: #8fc7ff; text-decoration: none; white-space: nowrap; }
    iframe { display: block; width: 100%; height: calc(100vh - 64px); border: 0; background: white; }
    #empty { height: calc(100vh - 64px); display: grid; place-items: center; color: #9bacce; }
  </style>
</head>
<body data-status="starting">
  <header>
    <span class="dot" aria-hidden="true"></span>
    <div class="summary"><div id="message">正在启动…</div><div id="meta"></div></div>
    <a id="direct" href="/report/index.html" target="_blank" hidden>单独打开报表</a>
  </header>
  <div id="empty">第一轮正式模拟完成后会自动显示报表</div>
  <iframe id="report" title="IGESS report" hidden></iframe>
  <script>
    const body = document.body;
    const message = document.querySelector('#message');
    const meta = document.querySelector('#meta');
    const report = document.querySelector('#report');
    const empty = document.querySelector('#empty');
    const direct = document.querySelector('#direct');
    let revision = -1;
    async function update() {
      try {
        const response = await fetch('/api/status', {cache: 'no-store'});
        const state = await response.json();
        body.dataset.status = state.status;
        message.textContent = state.message;
        const parts = [state.scenario_id, state.run_id, state.model_digest];
        if (state.changed_files?.length) parts.push(state.changed_files.join(', '));
        meta.textContent = parts.filter(Boolean).join(' · ');
        if (state.report_url && state.revision !== revision) {
          revision = state.revision;
          report.src = state.report_url + '?revision=' + encodeURIComponent(revision);
          report.hidden = false;
          empty.hidden = true;
          direct.hidden = false;
        }
      } catch (error) {
        body.dataset.status = 'error';
        message.textContent = '无法连接本地监听器，命令可能已经停止';
      }
    }
    update();
    setInterval(update, 750);
  </script>
</body>
</html>
"""


__all__ = [
    "LiveReportState",
    "LiveRun",
    "changed_files",
    "discover_watch_files",
    "fingerprint_files",
    "run_live_report",
    "start_live_server",
    "validate_live_run",
]
