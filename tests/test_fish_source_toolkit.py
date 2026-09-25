"""The shipped workbench must execute source Lua without either source checkout."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from igess.authoring.service import AuthoringService
from igess.operator_export import (
    ToolkitExportError,
    export_operator_toolkit,
    scan_operator_candidate,
)

ROOT = Path(__file__).resolve().parents[1]
PYTHON311 = ROOT / ".tmp/py311-venv/Scripts/python.exe"
SOURCE = Path("E:/fish-oasis")
pytestmark = pytest.mark.skipif(
    not PYTHON311.is_file() or not (SOURCE / "simulation/cli.lua").is_file()
    or shutil.which("lua55") is None,
    reason="Fish source and Windows Python/Lua build environment unavailable",
)


@pytest.fixture(scope="module")
def source_bundle(tmp_path_factory):
    folder = tmp_path_factory.mktemp("source-toolkit") / "bundle"
    export_operator_toolkit(
        ROOT / "projects/fish_source", folder, tool_version="source-test",
        python_command=(str(PYTHON311),), source_root=ROOT,
    )
    return folder


def test_source_toolkit_runs_relocated_without_lua_on_path(source_bundle, tmp_path):
    relocated = tmp_path / "relocated"
    shutil.copytree(source_bundle, relocated)
    assert (relocated / "bundle/fish-runtime/runtime.luac").is_file()
    assert not [p for p in relocated.rglob("*") if p.suffix in {".py", ".pyi", ".lua", ".map"}]
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
    probe = subprocess.run([
        str(PYTHON311), "-E", "-c", r'''
import json, shutil, sys
from pathlib import Path
from igess.operator_runtime import OperatorBundle, OperatorService
from igess.fish_source_runtime import FishSourceRuntime
assert shutil.which('lua55') is None
bundle = OperatorBundle.load('.')
assert bundle.engine_id == 'fish_source'
service = OperatorService(bundle, sys.argv[2])
run = service.run(sys.argv[1], 'smoke').record
assert run.status == 'success', run.message
assert run.report_index.is_file()
manifest = json.loads((run.output_dir / 'run_manifest.json').read_text())
assert manifest['engine_id'] == 'fish_source'
assert manifest['source_runtime']['code_sha256']
root = Path('bundle/fish-runtime').resolve()
kwargs = dict(lua_executable=str(root / 'lua55.exe'))
with FishSourceRuntime(root, sys.argv[1], **kwargs) as host:
    state = host.create(start_at=100, fast_advance=True)
    host.request({'op': 'start_exercise', 'requestId': 'exercise:1', 'revision': state['revision']})
    host.request({'op': 'advance', 'time': 101})
    checkpoint = host.checkpoint()
    expected = host.request({'op': 'query'})
with FishSourceRuntime(root, sys.argv[1], **kwargs) as host:
    assert host.restore(checkpoint) == expected
print(json.dumps({'output_dir': str(run.output_dir), 'report': str(run.report_index)}))
''', str(SOURCE / "igess_export/json"), str(tmp_path / "history")],
        cwd=relocated, env=environment, capture_output=True, text=True, encoding="utf-8", timeout=60,
        check=False,
    )
    assert probe.returncode == 0, probe.stdout + probe.stderr
    result = json.loads(probe.stdout)
    events = json.loads((Path(result["output_dir"]) / "events.json").read_text())
    assert any(event["kind"] == "complete_throw" for event in events)
    packaged = json.loads((relocated / "bundle/fish-runtime/runtime.json").read_text())
    assert packaged["numeric_input"] == "selected-json-only"
    assert not any(name.startswith("Script.Table.") for name in packaged["modules"])


def test_packaged_day_matches_source_formal_run(source_bundle, tmp_path):
    project = tmp_path / "source-project"
    project.mkdir()
    for name in ("Datas", "luban_exports"):
        shutil.copytree(ROOT / "projects/fish_source" / name, project / name)
    config = yaml.safe_load((ROOT / "projects/fish_source/economy.yaml").read_text(encoding="utf-8"))
    config["engine"]["source_runtime"]["project_root"] = str(SOURCE)
    config["engine"]["source_runtime"]["data_root"] = str(SOURCE / "igess_export/json")
    (project / "economy.yaml").write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    reference = AuthoringService(project).simulate("day_1_growth")
    assert reference.ok, reference.details
    probe = subprocess.run([
        str(PYTHON311), "-E", "-c",
        ("from igess.operator_runtime import OperatorBundle,OperatorService; import sys; "
        "r=OperatorService(OperatorBundle.load('.'),sys.argv[2]).run(sys.argv[1],'day_1_growth').record; "
        "assert r.status == 'success', r.message; print(r.output_dir)"),
        str(SOURCE / "igess_export/json"), str(tmp_path / "history"),
    ], cwd=source_bundle, capture_output=True, text=True, encoding="utf-8", timeout=120, check=False)
    assert probe.returncode == 0, probe.stdout + probe.stderr
    candidate = Path(probe.stdout.strip())
    original = Path(reference.result["output_dir"])
    for name in ("timeline.json", "events.json", "source_progression.json", "source_behavior.json"):
        assert (candidate / name).read_bytes() == (original / name).read_bytes(), name


def test_source_toolkit_audit_rejects_lua_source_in_bytecode_slot(source_bundle, tmp_path):
    copied = tmp_path / "candidate"
    shutil.copytree(source_bundle, copied)
    (copied / "bundle/fish-runtime/runtime.luac").write_bytes(b'print("source leak")')
    with pytest.raises(ToolkitExportError):
        scan_operator_candidate(copied)
