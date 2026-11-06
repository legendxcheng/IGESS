"""Longer scenarios reuse compatible source checkpoints through real workers."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from igess.authoring.service import AuthoringService
from igess.dashboard import render_dashboard_home
from igess.dashboard_tasks import DashboardTaskRunner
from igess.fish_source_engine import _unpack_session
from igess.workflows import WorkflowService
from test_fish_source_formal import FISH_SOURCE, _project
from test_authoring_cli import run_cli, json_result

pytestmark = pytest.mark.skipif(
    not (FISH_SOURCE / "simulation/cli.lua").is_file(), reason="Fish source checkout is not available",
)


def project(tmp_path):
    target = _project(tmp_path)
    path = target / "economy.yaml"
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    config["engine"]["source_runtime"]["advance_mode"] = "equivalent_batch_v1"
    config["session_patterns"]["authoring_default"]["daily_online_seconds"] = 60
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return target


def read(output, name):
    return json.loads((output / name).read_text(encoding="utf-8"))


def normalize_scenario(value):
    # Earlier lifecycle facts keep their original scenario identity.
    if isinstance(value, dict):
        return {k: normalize_scenario(v) for k, v in value.items() if k != "scenario_id"}
    if isinstance(value, list):
        return [normalize_scenario(item) for item in value]
    return value


@pytest.mark.parametrize("cutoff", [10, 86400])
def test_longer_scenario_matches_continuous_run_through_fresh_worker(tmp_path, cutoff):
    target = project(tmp_path)
    service = AuthoringService(target)
    first = service.simulate("day_1_growth", until_seconds=cutoff)
    assert first.ok, first.details
    first_output = Path(first.result["output_dir"])
    original_checkpoint = (first_output / "final_checkpoint.json").read_bytes()
    full = service.simulate("day_2_growth")
    assert full.ok, full.details
    full_output = Path(full.result["output_dir"])
    workflow = WorkflowService(target)
    page = render_dashboard_home(workflow, None, None)
    assert 'name="resume_run_id"' in page
    assert first.result["run_id"] in page
    runner = DashboardTaskRunner(workflow, None, None)
    try:
        result = runner.run("simulate", "day_2_growth", resume_run_id=first.result["run_id"])
    finally:
        runner.close()
    assert result["state"] == "success", result
    output = workflow.registry.runs_root / result["run_id"] / "output"
    window = read(output, "run_manifest.json")["execution_window"]
    assert window["start_seconds"] == cutoff
    assert window["end_seconds"] == 172800
    assert window["checkpoint_scenario_id"] == "day_1_growth"
    checkpoint = read(output, "final_checkpoint.json")
    reference = read(full_output, "final_checkpoint.json")
    assert normalize_scenario(checkpoint["behavior_state"]) == normalize_scenario(reference["behavior_state"])
    assert read(output, "timeline.json")[-1] == read(full_output, "timeline.json")[-1]
    # Source session contains the final archive, RNG and pending side effects.
    restored_session = _unpack_session(checkpoint["engine_state"])
    full_session = _unpack_session(reference["engine_state"])
    assert {k: v for k, v in restored_session.items() if k != "history"} == {
        k: v for k, v in full_session.items() if k != "history"
    }
    if cutoff == 86400:
        assert restored_session["history"] == full_session["history"]
    assert (first_output / "final_checkpoint.json").read_bytes() == original_checkpoint
    report = json.loads((output.parent / "report/report_data.json").read_text(encoding="utf-8"))
    assert report["fish_progression"]["execution_window"] == window
    assert "续跑区间" in (output.parent / "report/index.html").read_text(encoding="utf-8")
    events = read(output, "events.json")
    assert all(e["time_seconds"] >= cutoff for e in events)


@pytest.mark.parametrize("change", ["sampling", "shorter", "data"])
def test_continuation_rejects_incompatible_inputs(tmp_path, change):
    target = project(tmp_path)
    path = target / "economy.yaml"
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    if change == "sampling":
        config["scenarios"]["day_2_growth"]["record_interval_seconds"] = 1
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    start, end = ("day_2_growth", "day_1_growth") if change == "shorter" else ("day_1_growth", "day_2_growth")
    first = AuthoringService(target).simulate(start, until_seconds=10)
    assert first.ok, first.details
    if change == "data":
        table = target / "production_snapshot/json/tbfishhallupgrade.json"
        rows = json.loads(table.read_text(encoding="utf-8"))
        rows[0]["upgradePrice"]["scale"] += 1
        table.write_text(json.dumps(rows), encoding="utf-8")
    result = AuthoringService(target).simulate(
        end, resume_run_id=first.result["run_id"], until_seconds=20,
    )
    assert not result.ok
    expected = "checkpoint_model_digest_mismatch" if change == "data" else "fish_source_checkpoint_scope_mismatch"
    diagnostic = read(target / ".igess/diagnostics", result.result["run_id"] + ".json")
    assert expected in str(result.to_payload()) + diagnostic["primary_error"]["message"]


def test_history_continuation_rejects_unknown_or_missing_checkpoint(tmp_path):
    workflow = WorkflowService(project(tmp_path))
    for run_id in ("../other-project/run", "missing"):
        with pytest.raises(ValueError, match="successful run"):
            workflow.checkpoint_for_run(run_id)


def test_weekly_cli_chain_matches_four_week_continuous_run(tmp_path):
    # Real Lua, real CLI processes and real week boundaries; shorter daily
    # sessions bound test cost without shortening the shipped scenario horizons.
    target = project(tmp_path)
    runs_root = tmp_path / "dashboard history"
    workflow = WorkflowService(target, runs_root=runs_root)
    scenarios = ("week_1_growth", "week_2_growth", "week_3_growth", "month_1_growth")
    assert set(scenarios) <= set(workflow.available_scenarios("economy.yaml"))
    previous_id = None
    checkpoints = []
    for week, scenario in enumerate(scenarios, 1):
        args = ["model", "simulate", "--project", str(target), "--scenario", scenario,
                "--runs-root", str(runs_root), "--json"]
        if previous_id is not None:
            args.extend(["--resume-run-id", previous_id])
        result = run_cli(*args)
        payload = json_result(result)
        assert result.returncode == 0, payload
        output = Path(payload["result"]["output_dir"])
        assert output.parent.parent == runs_root
        window = read(output, "run_manifest.json")["execution_window"]
        assert window["start_seconds"] == (week - 1) * 7 * 86400
        assert window["end_seconds"] == week * 7 * 86400
        if previous_id is not None:
            assert window["checkpoint_scenario_id"] == scenarios[week - 2]
        assert all(e["time_seconds"] >= window["start_seconds"] for e in read(output, "events.json"))
        checkpoint_path = output / "final_checkpoint.json"
        checkpoints.append((checkpoint_path, checkpoint_path.read_bytes()))
        previous_id = payload["result"]["run_id"]
        assert workflow.checkpoint_for_run(previous_id) == checkpoint_path

    full = AuthoringService(target).simulate("month_1_growth")
    assert full.ok, full.details
    full_output = Path(full.result["output_dir"])
    checkpoint = read(output, "final_checkpoint.json")
    reference = read(full_output, "final_checkpoint.json")
    assert normalize_scenario(checkpoint["behavior_state"]) == normalize_scenario(reference["behavior_state"])
    assert _unpack_session(checkpoint["engine_state"]) == _unpack_session(reference["engine_state"])
    assert read(output, "timeline.json")[-1] == read(full_output, "timeline.json")[-1]
    for path, original in checkpoints:
        assert path.read_bytes() == original
