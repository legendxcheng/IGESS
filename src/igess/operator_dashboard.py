"""Loopback-only browser workbench for execution planners."""

from __future__ import annotations

from dataclasses import dataclass
import html
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import mimetypes
import os
from pathlib import Path, PurePosixPath
import secrets
from threading import BoundedSemaphore, Lock
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse
import webbrowser

from .operator_runtime import OperatorBundle, OperatorError, OperatorService, sanitize_diagnostic


_MAX_FORM_BYTES = 64 * 1024
_MAX_ARTIFACT_BYTES = 32 * 1024 * 1024
_POST_PATHS = frozenset({"/run", "/delete", "/clear"})


@dataclass(frozen=True, slots=True)
class WorkbenchView:
    tables_directory: str = ""
    scenario_id: str = ""
    notice: str = ""
    notice_kind: str = ""


class WorkbenchState:
    def __init__(self) -> None:
        self._lock = Lock()
        self._view = WorkbenchView()

    def read(self) -> WorkbenchView:
        with self._lock:
            return self._view

    def update(self, **changes: str) -> None:
        with self._lock:
            current = self._view
            self._view = WorkbenchView(
                tables_directory=changes.get("tables_directory", current.tables_directory),
                scenario_id=changes.get("scenario_id", current.scenario_id),
                notice=changes.get("notice", current.notice),
                notice_kind=changes.get("notice_kind", current.notice_kind),
            )


class OperatorHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def render_operator_home(
    service: OperatorService,
    view: WorkbenchView,
    csrf_token: str,
) -> str:
    scenarios = service.scenarios()
    selected = view.scenario_id if view.scenario_id in scenarios else scenarios[0]
    scenario_options = "".join(
        f'<option value="{_e(item)}"{" selected" if item == selected else ""}>{_e(item)}</option>'
        for item in scenarios
    )
    compatible = service.compatible_baselines(selected)
    latest_id = compatible[-1].run_id if compatible else ""
    baseline_options = ['<option value="">不比较</option>']
    baseline_options.extend(
        f'<option value="{_e(record.run_id)}"{" selected" if record.run_id == latest_id else ""}>'
        f'{_e(record.run_id)} · {_e(record.scenario_id)}</option>'
        for record in reversed(compatible)
    )
    notice = (
        f'<section class="notice {"failed" if view.notice_kind == "failed" else "ok"}">'
        f"{_e(view.notice)}</section>"
        if view.notice
        else ""
    )
    rows = []
    for record in reversed(service.list_runs()):
        metadata = service.run_metadata(record.run_id) or {}
        comparison = metadata.get("comparison")
        gates = metadata.get("gates")
        result_links = []
        if record.status == "success":
            result_links.append(
                f'<a href="/reports/{_e(record.run_id)}/index.html">查看报表</a>'
            )
        if isinstance(comparison, dict) and isinstance(comparison.get("index"), str):
            result_links.append(
                f'<a href="/artifacts/{_e(record.run_id)}/{_e(comparison["index"])}">查看对比</a>'
            )
        if isinstance(gates, dict):
            if gates.get("configured") is False:
                result_links.append('<span class="muted">未配置回归规则</span>')
            else:
                gate_text = "回归通过" if gates.get("ok") is True else "回归失败"
                result_links.append(f'<span class="{"ok" if gates.get("ok") is True else "failed"}">{gate_text}</span>')
        result_links.append(
            f'<a href="/diagnostics/{_e(record.run_id)}.zip">诊断包</a>'
        )
        rows.append(
            "<tr>"
            f"<td><code>{_e(record.run_id)}</code></td>"
            f"<td>{_e(record.scenario_id)}</td>"
            f'<td class="{"ok" if record.status == "success" else "failed"}">{_e(record.status)}</td>'
            f"<td>{_e(record.message)}</td>"
            f"<td>{' · '.join(result_links)}</td>"
            "<td>"
            '<form action="/delete" method="post">'
            f'{_csrf_input(csrf_token)}<input type="hidden" name="run_id" value="{_e(record.run_id)}">'
            '<button class="secondary" type="submit">删除</button></form>'
            "</td>"
            "</tr>"
        )
    history_rows = "".join(rows) or '<tr><td colspan="6">暂无运行记录。</td></tr>'
    size = _human_bytes(service.history_size_bytes())
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>IGESS 数值调优工作台</title>
  <style>
    :root {{ color-scheme: light; font-family: "Segoe UI", "Microsoft YaHei", sans-serif; color: #172033; background: #eef2f7; }}
    body {{ margin: 0; }} main {{ max-width: 1240px; margin: 0 auto; padding: 28px; }}
    header {{ display: flex; justify-content: space-between; align-items: end; gap: 24px; }}
    h1 {{ margin-bottom: 6px; }} .muted {{ color: #64748b; }}
    section {{ background: white; border: 1px solid #dbe3ed; border-radius: 10px; padding: 20px; margin: 16px 0; box-shadow: 0 2px 10px #0f172a0d; }}
    .grid {{ display: grid; grid-template-columns: minmax(320px, 2fr) minmax(220px, 1fr) minmax(280px, 1fr); gap: 16px; align-items: end; }}
    label {{ display: block; font-weight: 700; margin-bottom: 7px; }}
    input[type=text], select {{ box-sizing: border-box; width: 100%; min-height: 40px; border: 1px solid #aebdce; border-radius: 6px; padding: 8px 10px; background: white; }}
    button {{ border: 0; border-radius: 6px; padding: 10px 16px; background: #175cd3; color: white; font-weight: 700; cursor: pointer; }}
    button.secondary {{ background: #e8eef6; color: #334155; padding: 6px 10px; }}
    .run-button {{ width: 100%; min-height: 42px; }} .check {{ margin: 14px 0 0; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
    th, td {{ padding: 10px 8px; border-bottom: 1px solid #e5eaf1; text-align: left; vertical-align: top; }}
    td:nth-child(4) {{ max-width: 360px; overflow-wrap: anywhere; }}
    a {{ color: #175cd3; }} .ok {{ color: #087443; }} .failed {{ color: #b42318; }}
    .notice {{ font-weight: 700; }} .danger {{ border-color: #fecaca; }} code {{ overflow-wrap: anywhere; }}
    @media (max-width: 850px) {{ .grid {{ grid-template-columns: 1fr; }} main {{ padding: 16px; }} table {{ display: block; overflow-x: auto; }} }}
  </style>
</head>
<body>
<main>
  <header><div><h1>IGESS 数值调优工作台</h1><div class="muted">{_e(service.bundle.model_id)} · 工具版本 {_e(service.bundle.tool_version)} · 完全离线</div></div><div class="muted">历史占用 {size}</div></header>
  {notice}
  <section>
    <h2>运行模拟</h2>
    <form action="/run" method="post">
      {_csrf_input(csrf_token)}
      <div class="grid">
        <div><label for="tables">导表 JSON 目录</label><input id="tables" name="tables" type="text" value="{_e(view.tables_directory)}" placeholder="例如 D:\\GameData\\json" required></div>
        <div><label for="scenario">预设场景</label><select id="scenario" name="scenario">{scenario_options}</select></div>
        <div><label for="baseline">比较基线</label><select id="baseline" name="baseline">{''.join(baseline_options)}</select></div>
      </div>
      <label class="check"><input type="checkbox" name="include_input" value="yes"> 在诊断包中附带本次完整 JSON（默认不附带）</label>
      <p class="muted">运行开始时读取不可变快照；原导表目录始终只读。同一时刻只执行一个任务。</p>
      <button class="run-button" type="submit">运行并生成报表</button>
    </form>
  </section>
  <section>
    <h2>运行历史</h2>
    <table><thead><tr><th>运行</th><th>场景</th><th>状态</th><th>说明</th><th>结果</th><th></th></tr></thead><tbody>{history_rows}</tbody></table>
  </section>
  <section class="danger">
    <h2>历史清理</h2>
    <p>工具不会自动删除历史。以下操作会删除全部本地运行记录。</p>
    <form action="/clear" method="post">{_csrf_input(csrf_token)}<button type="submit">清空全部历史</button></form>
  </section>
</main>
</body>
</html>"""


def serve_operator_dashboard(
    bundle_root: str | Path,
    *,
    port: int = 0,
    open_browser: bool = True,
    history_root: str | Path | None = None,
) -> None:
    bundle = OperatorBundle.load(bundle_root)
    service = OperatorService(bundle, history_root)
    token = secrets.token_urlsafe(32)
    view_state = WorkbenchState()
    handler = _handler(
        service,
        view_state,
        csrf_token=token,
        mutation_guard=BoundedSemaphore(1),
    )
    server = OperatorHTTPServer(("127.0.0.1", port), handler)
    actual_port = int(server.server_address[1])
    url = f"http://127.0.0.1:{actual_port}/"
    print(f"IGESS operator workbench: {url}", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def _handler(
    service: OperatorService,
    view_state: WorkbenchState,
    *,
    csrf_token: str,
    mutation_guard: BoundedSemaphore,
):
    class OperatorHandler(BaseHTTPRequestHandler):
        server_version = "IGESSOperator/1"
        sys_version = ""

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler API.
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._send_html(render_operator_home(service, view_state.read(), csrf_token))
                return
            if parsed.path.startswith("/reports/"):
                relative = parsed.path.removeprefix("/reports/")
                status, content_type, body = _report_response(service, relative)
                self._send_bytes(status, content_type, body)
                return
            if parsed.path.startswith("/artifacts/"):
                status, content_type, body = _artifact_response(
                    service,
                    parsed.path.removeprefix("/artifacts/"),
                )
                self._send_bytes(status, content_type, body)
                return
            if parsed.path.startswith("/diagnostics/") and parsed.path.endswith(".zip"):
                run_id = unquote(parsed.path.removeprefix("/diagnostics/").removesuffix(".zip"))
                try:
                    body = service.diagnostic_zip(run_id)
                except OperatorError:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/zip")
                self.send_header(
                    "Content-Disposition",
                    f'attachment; filename="igess-diagnostic-{_safe_header(run_id)}.zip"',
                )
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if parsed.path in _POST_PATHS:
                self.send_response(HTTPStatus.METHOD_NOT_ALLOWED)
                self.send_header("Allow", "POST")
                self.end_headers()
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:  # noqa: N802 - stdlib handler API.
            parsed = urlparse(self.path)
            if parsed.path not in _POST_PATHS:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            try:
                form = self._read_form()
            except (UnicodeError, ValueError):
                self.send_error(HTTPStatus.BAD_REQUEST)
                return
            if not self._authorized(form):
                self.send_error(HTTPStatus.FORBIDDEN)
                return
            if not mutation_guard.acquire(blocking=False):
                self.send_error(HTTPStatus.TOO_MANY_REQUESTS)
                return
            try:
                self._perform(parsed.path, form)
            finally:
                mutation_guard.release()
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", "/")
            self.end_headers()

        def _perform(self, path: str, form: dict[str, list[str]]) -> None:
            tables = form.get("tables", [""])[0]
            scenario = form.get("scenario", [""])[0]
            try:
                if path == "/run":
                    baseline = form.get("baseline", [""])[0] or None
                    result = service.run(
                        tables,
                        scenario,
                        baseline_run_id=baseline,
                        include_diagnostic_input=form.get("include_input", [""])[0] == "yes",
                    )
                    notice = (
                        f"运行完成：{result.record.run_id}"
                        if result.record.status == "success"
                        else result.record.message
                    )
                    view_state.update(
                        tables_directory=tables,
                        scenario_id=scenario,
                        notice=notice,
                        notice_kind="ok" if result.record.status == "success" else "failed",
                    )
                elif path == "/delete":
                    service.delete_run(form.get("run_id", [""])[0])
                    view_state.update(notice="运行记录已删除。", notice_kind="ok")
                else:
                    deleted = service.clear_history()
                    view_state.update(notice=f"已删除 {deleted} 条运行记录。", notice_kind="ok")
            except OperatorError as error:
                view_state.update(
                    tables_directory=tables,
                    scenario_id=scenario,
                    notice=str(error),
                    notice_kind="failed",
                )
            except Exception as error:  # noqa: BLE001 - never expose a traceback to the planner.
                view_state.update(
                    tables_directory=tables,
                    scenario_id=scenario,
                    notice=f"工具内部错误：{sanitize_diagnostic(type(error).__name__)}",
                    notice_kind="failed",
                )

        def _read_form(self) -> dict[str, list[str]]:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            if length < 0 or length > _MAX_FORM_BYTES:
                raise ValueError("invalid form size")
            return parse_qs(self.rfile.read(length).decode("utf-8"), keep_blank_values=True)

        def _authorized(self, form: dict[str, list[str]]) -> bool:
            supplied = form.get("_csrf", [""])[0]
            return (
                _valid_local_authority(self.headers.get("Host"), self.server.server_port)
                and _same_origin(self.headers.get("Origin"), self.headers.get("Host"), self.server.server_port)
                and secrets.compare_digest(supplied, csrf_token)
            )

        def _send_html(self, body: str) -> None:
            self._send_bytes(HTTPStatus.OK, "text/html; charset=utf-8", body.encode("utf-8"))

        def _send_bytes(self, status: HTTPStatus, content_type: str, body: bytes) -> None:
            self.send_response(int(status))
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'",
            )
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

    return OperatorHandler


def _artifact_response(
    service: OperatorService,
    relative: str,
) -> tuple[HTTPStatus, str, bytes]:
    decoded = unquote(relative)
    if "\\" in decoded or "\x00" in decoded:
        return _not_found()
    parts = PurePosixPath(decoded).parts
    if len(parts) < 3 or any(part in {"", ".", ".."} for part in parts):
        return _not_found()
    run_id, family, *asset_parts = parts
    if family not in {"comparison", "gates"}:
        return _not_found()
    record = next((item for item in service.list_runs() if item.run_id == run_id), None)
    if record is None:
        return _not_found()
    try:
        body = _read_safe_file(
            record.run_dir,
            (family, *asset_parts),
            max_bytes=_MAX_ARTIFACT_BYTES,
        )
    except (OSError, RuntimeError, ValueError):
        return _not_found()
    content_type = mimetypes.guess_type(asset_parts[-1])[0] or "application/octet-stream"
    return HTTPStatus.OK, content_type, body


def _report_response(
    service: OperatorService,
    relative: str,
) -> tuple[HTTPStatus, str, bytes]:
    decoded = unquote(relative)
    if "\\" in decoded or "\x00" in decoded:
        return _not_found()
    parts = PurePosixPath(decoded).parts
    if len(parts) < 2 or any(part in {"", ".", ".."} for part in parts):
        return _not_found()
    run_id, *asset_parts = parts
    record = next((item for item in service.list_runs() if item.run_id == run_id), None)
    if record is None:
        return _not_found()
    try:
        body = _read_safe_file(
            record.report_dir,
            tuple(asset_parts),
            max_bytes=_MAX_ARTIFACT_BYTES,
        )
    except (OSError, RuntimeError, ValueError):
        return _not_found()
    content_type = mimetypes.guess_type(asset_parts[-1])[0] or "application/octet-stream"
    return HTTPStatus.OK, content_type, body


def _read_safe_file(root: Path, parts: tuple[str, ...], *, max_bytes: int) -> bytes:
    if not parts or any(not part or part in {".", ".."} for part in parts):
        raise ValueError("unsafe artifact path")
    resolved_root = root.resolve(strict=True)
    target = root.joinpath(*parts)
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise OSError("artifact path contains a link")
    resolved_target = target.resolve(strict=True)
    if not resolved_target.is_relative_to(resolved_root) or not resolved_target.is_file():
        raise OSError("artifact escaped its run root")
    with resolved_target.open("rb") as handle:
        before = os.fstat(handle.fileno())
        if before.st_size > max_bytes:
            raise OSError("artifact exceeds size limit")
        body = handle.read(max_bytes + 1)
        after = os.fstat(handle.fileno())
    if (
        len(body) > max_bytes
        or not os.path.samestat(before, after)
        or before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
    ):
        raise OSError("artifact changed while it was read")
    return body


def _not_found() -> tuple[HTTPStatus, str, bytes]:
    return HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", b"Not found"


def _valid_local_authority(authority: str | None, port: int) -> bool:
    if not authority:
        return False
    parsed = urlparse(f"//{authority}")
    try:
        parsed_port = parsed.port
        address = ipaddress.ip_address(parsed.hostname or "")
    except ValueError:
        return False
    return (
        parsed.username is None
        and parsed.password is None
        and parsed_port == port
        and address.is_loopback
    )


def _same_origin(origin: str | None, host: str | None, port: int) -> bool:
    if origin is None:
        return True
    parsed = urlparse(origin)
    return (
        parsed.scheme == "http"
        and not parsed.path.strip("/")
        and not parsed.query
        and not parsed.fragment
        and _valid_local_authority(parsed.netloc, port)
        and parsed.netloc.casefold() == (host or "").casefold()
    )


def _csrf_input(token: str) -> str:
    return f'<input type="hidden" name="_csrf" value="{_e(token)}">'


def _human_bytes(value: int) -> str:
    amount = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if amount < 1024 or unit == "GB":
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{amount:.1f} GB"


def _safe_header(value: str) -> str:
    return "".join(character for character in value if character.isalnum() or character in "_-")[:128] or "run"


def _e(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


__all__ = [
    "OperatorHTTPServer",
    "WorkbenchState",
    "WorkbenchView",
    "render_operator_home",
    "serve_operator_dashboard",
]
