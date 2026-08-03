from __future__ import annotations

from http import HTTPStatus
from http.client import HTTPConnection
import json
from pathlib import Path
import subprocess
from threading import BoundedSemaphore, Thread
from urllib.parse import urlencode

import pytest

from igess.operator_dashboard import (
    OperatorHTTPServer,
    WorkbenchState,
    WorkbenchView,
    _artifact_response,
    _handler,
    render_operator_home,
)
from igess.operator_export import (
    ToolkitExportError,
    export_operator_toolkit,
    scan_operator_candidate,
)
from igess.operator_runtime import (
    OperatorBundle,
    OperatorError,
    OperatorService,
    default_history_root,
    snapshot_json_directory,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "examples" / "shelldiver_v0" / "economy.yaml"
TABLES = ROOT / "examples" / "shelldiver_v0" / "luban_exports"
PYTHON311 = ROOT / ".tmp" / "py311-venv" / "Scripts" / "python.exe"


def _bundle(tmp_path: Path, *, version: str = "test-1") -> OperatorBundle:
    return OperatorBundle(
        root=tmp_path,
        tool_version=version,
        model_id="operator-test",
        engine_id="generic",
        config_path=CONFIG,
        schema_path=None,
        scenarios=("analytic_smoke",),
    )


def test_history_defaults_to_local_appdata(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    assert default_history_root("fish") == tmp_path / "IGESS Operator" / "fish" / "runs"


def test_snapshots_json_without_modifying_source(tmp_path: Path) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "snapshot"
    source.mkdir()
    path = source / "table.json"
    path.write_text('[{"id": 1}]\n', encoding="utf-8")
    before = path.stat()

    files = snapshot_json_directory(source, destination)

    after = path.stat()
    assert files[0].name == "table.json"
    assert files[0].sha256.startswith("sha256:")
    assert (destination / "table.json").read_bytes() == path.read_bytes()
    assert (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)


def test_operator_runs_reports_compares_and_keeps_input_out_of_history(tmp_path: Path) -> None:
    service = OperatorService(_bundle(tmp_path), tmp_path / "history")
    before = {path.name: path.stat().st_mtime_ns for path in TABLES.glob("*.json")}

    first = service.run(TABLES, "analytic_smoke")
    second = service.run(
        TABLES,
        "analytic_smoke",
        baseline_run_id=first.record.run_id,
    )

    assert first.record.status == "success"
    assert first.record.report_index.is_file()
    assert second.record.status == "success"
    assert second.comparison_index is not None and second.comparison_index.is_file()
    assert second.gates_ok is None
    metadata = service.run_metadata(second.record.run_id)
    assert metadata is not None
    assert metadata["tool_version"] == "test-1"
    assert metadata["gates"]["configured"] is False
    assert metadata["diagnostic_input_included"] is False
    assert not second.record.run_dir.joinpath("diagnostic-input").exists()
    assert {path.name: path.stat().st_mtime_ns for path in TABLES.glob("*.json")} == before

    status, content_type, body = _artifact_response(
        service,
        f"{second.record.run_id}/comparison/{first.record.run_id}/index.html",
    )
    assert status == HTTPStatus.OK
    assert content_type == "text/html"
    assert b"IGESS Comparison" in body


def test_operator_rejects_cross_version_comparison(tmp_path: Path) -> None:
    history = tmp_path / "history"
    old = OperatorService(_bundle(tmp_path, version="old"), history)
    baseline = old.run(TABLES, "analytic_smoke").record
    current = OperatorService(_bundle(tmp_path, version="new"), history)

    with pytest.raises(OperatorError, match="跨工具版本"):
        current.run(TABLES, "analytic_smoke", baseline_run_id=baseline.run_id)


def test_diagnostic_zip_only_includes_input_after_explicit_request(tmp_path: Path) -> None:
    import io
    import zipfile

    service = OperatorService(_bundle(tmp_path), tmp_path / "history")
    normal = service.run(TABLES, "analytic_smoke").record
    included = service.run(
        TABLES,
        "analytic_smoke",
        include_diagnostic_input=True,
    ).record

    with zipfile.ZipFile(io.BytesIO(service.diagnostic_zip(normal.run_id))) as archive:
        assert archive.namelist() == ["diagnostic.json"]
    with zipfile.ZipFile(io.BytesIO(service.diagnostic_zip(included.run_id))) as archive:
        assert "diagnostic.json" in archive.namelist()
        assert any(name.startswith("input/") for name in archive.namelist())


def test_failed_run_uses_sanitized_business_diagnostic_and_can_be_deleted(tmp_path: Path) -> None:
    tables = tmp_path / "bad-tables"
    tables.mkdir()
    (tables / "unrelated.json").write_text("[]\n", encoding="utf-8")
    service = OperatorService(_bundle(tmp_path), tmp_path / "history")

    result = service.run(tables, "analytic_smoke")

    assert result.record.status == "failed"
    assert result.diagnostic_code and result.diagnostic_code in result.record.message
    assert "Traceback" not in result.record.message
    assert str(tables) not in result.record.message
    service.delete_run(result.record.run_id)
    assert service.list_runs() == []


def test_workbench_only_exposes_planner_actions_and_manual_history_cleanup(tmp_path: Path) -> None:
    service = OperatorService(_bundle(tmp_path), tmp_path / "history")

    body = render_operator_home(service, WorkbenchView(), "token")

    assert "数值调优工作台" in body
    assert "运行并生成报表" in body
    assert "清空全部历史" in body
    assert "Agent Analyst" not in body
    assert "YAML" not in body
    assert "CLI" not in body


def test_workbench_http_is_readable_and_mutations_require_csrf(tmp_path: Path) -> None:
    service = OperatorService(_bundle(tmp_path), tmp_path / "history")
    server = OperatorHTTPServer(
        ("127.0.0.1", 0),
        _handler(
            service,
            WorkbenchState(),
            csrf_token="known-token",
            mutation_guard=BoundedSemaphore(1),
        ),
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    try:
        connection.request("GET", "/")
        response = connection.getresponse()
        body = response.read().decode("utf-8")
        assert response.status == HTTPStatus.OK
        assert "数值调优工作台" in body

        connection.request("GET", "/run")
        response = connection.getresponse()
        response.read()
        assert response.status == HTTPStatus.METHOD_NOT_ALLOWED

        encoded = urlencode({"run_id": "missing"})
        connection.request(
            "POST",
            "/delete",
            encoded,
            {"Content-Type": "application/x-www-form-urlencoded"},
        )
        response = connection.getresponse()
        response.read()
        assert response.status == HTTPStatus.FORBIDDEN
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.skipif(not PYTHON311.is_file(), reason="repository Python 3.11 build environment unavailable")
def test_exports_sourceless_python311_toolkit_and_preserves_unmanaged_files(tmp_path: Path) -> None:
    output = tmp_path / "distribution"
    output.mkdir()
    unmanaged = output / "owner-notes.txt"
    unmanaged.write_text("keep", encoding="utf-8")

    result = export_operator_toolkit(
        ROOT / "projects" / "fish",
        output,
        tool_version="fish-test",
        python_command=(str(PYTHON311),),
        source_root=ROOT,
    )

    assert result.tool_version == "fish-test"
    assert unmanaged.read_text(encoding="utf-8") == "keep"
    assert not list(output.rglob("*.py"))
    assert not list(output.rglob("*.pyi"))
    assert not list(output.rglob("*.map"))
    assert (output / "igess" / "operator_cli.pyc").is_file()
    assert (output / "bundle" / "schema.pyc").is_file()
    start_script = (output / "start.bat").read_text(encoding="utf-8-sig")
    assert 'py -3.11 -m igess.operator_cli --bundle "."' in start_script
    assert '--bundle "%~dp0"' not in start_script
    assert (output / "igess" / "reporting" / "assets" / "report.js").stat().st_size < (
        ROOT / "src" / "igess" / "reporting" / "assets" / "report.js"
    ).stat().st_size
    config = (output / "bundle" / "economy.yaml").read_text(encoding="utf-8")
    assert "__SELECTED_JSON_DIRECTORY__" in config
    assert str(ROOT) not in config

    probe = subprocess.run(
        [
            str(PYTHON311),
            "-c",
            "import igess.operator_runtime as runtime; print(runtime.OperatorBundle.load('.').tool_version)",
        ],
        cwd=output,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert probe.returncode == 0, probe.stderr
    assert probe.stdout.strip() == "fish-test"

    delivery_path = output / ".igess-delivery-manifest.json"
    delivery = json.loads(delivery_path.read_text(encoding="utf-8"))
    delivery["managed_files"].append("obsolete-managed.txt")
    delivery_path.write_text(json.dumps(delivery), encoding="utf-8")
    obsolete = output / "obsolete-managed.txt"
    obsolete.write_text("old", encoding="utf-8")

    rerun = export_operator_toolkit(
        ROOT / "projects" / "fish",
        output,
        tool_version="fish-test",
        python_command=(str(PYTHON311),),
        source_root=ROOT,
    )

    assert rerun.removed_files == ("obsolete-managed.txt",)
    assert not obsolete.exists()
    assert unmanaged.exists()


def test_candidate_scan_fails_closed_on_python_source(tmp_path: Path) -> None:
    (tmp_path / "leak.py").write_text("secret = True\n", encoding="utf-8")

    with pytest.raises(ToolkitExportError, match="禁止文件"):
        scan_operator_candidate(tmp_path)
