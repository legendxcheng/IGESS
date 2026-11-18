"""Source Fish is verified through the existing formal authoring entry."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest
import yaml

from igess.authoring.service import AuthoringService
from igess.fish_source_runtime import (
    FishSourceRuntime,
    data_snapshot_digest,
    source_code_digest,
)

ROOT = Path(__file__).resolve().parents[1]
FISH_SOURCE = Path(os.environ.get("FISH_SOURCE_ROOT", str(ROOT.parent / "fish-oasis")))
pytestmark = pytest.mark.skipif(
    not (FISH_SOURCE / "simulation" / "cli.lua").is_file(),
    reason="Fish source checkout is not available",
)


def _project(tmp_path: Path, *, duration_hours: str = "0.025") -> Path:
    origin = ROOT / "projects" / "fish_source"
    project = tmp_path / "fish_source"
    project.mkdir()
    shutil.copytree(origin / "Datas", project / "Datas")
    shutil.copytree(origin / "luban_exports", project / "luban_exports")
    shutil.copytree(FISH_SOURCE / "igess_export/json", project / "production_snapshot" / "json")
    config = yaml.safe_load((origin / "economy.yaml").read_text(encoding="utf-8"))
    config["engine"]["source_runtime"].update(
        project_root=str(FISH_SOURCE), data_root="production_snapshot/json", advance_mode="accurate",
    )
    config["scenarios"]["smoke"]["duration_hours"] = duration_hours
    (project / "economy.yaml").write_text(
        yaml.safe_dump(config, allow_unicode=True), encoding="utf-8",
    )
    return project


def test_source_model_status_accepts_the_current_source_policy(tmp_path: Path) -> None:
    project = _project(tmp_path)
    # Preserve the shipped exact-decimal quoting through the authoring seam.
    config = (ROOT / "projects/fish_source/economy.yaml").read_text(encoding="utf-8")
    (project / "economy.yaml").write_text(
        config.replace("../../../fish-oasis", FISH_SOURCE.as_posix()), encoding="utf-8",
    )
    response = AuthoringService(project).status()
    assert response.ok, response.result
    assert response.result["state"] == "ready"
    assert not (project / "runs").exists()


def test_formal_source_smoke_uses_lua_receipts_and_writes_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Include the first deployment and its production after a full throw group.
    project = _project(tmp_path, duration_hours="0.05")
    freeze_source = FishSourceRuntime._freeze_source

    def checked_freeze(runtime: FishSourceRuntime) -> Path:
        frozen = freeze_source(runtime)
        # Independently read the files consumed by Lua: in-memory hashing must
        # preserve the existing fingerprint format and match the actual copy.
        assert source_code_digest(frozen) == runtime.source_digest
        assert data_snapshot_digest(frozen / "selected_data") == runtime.data_digest
        return frozen

    monkeypatch.setattr(FishSourceRuntime, "_freeze_source", checked_freeze)
    response = AuthoringService(project).simulate("smoke")

    assert response.ok, response.details
    assert response.result["engine_id"] == "fish_source"
    output = Path(response.result["output_dir"])
    rows = json.loads((output / "timeline.json").read_text(encoding="utf-8"))
    events = json.loads((output / "events.json").read_text(encoding="utf-8"))
    manifest = json.loads((output / "run_manifest.json").read_text(encoding="utf-8"))
    assert rows[-1]["resources"]["unclaimed_money"] != "0"
    from decimal import Decimal
    assert Decimal(rows[-1]["resources"]["generated_money"]) == Decimal(rows[-1]["resources"]["unclaimed_money"]) + Decimal(rows[-1]["resources"]["collected_money"])
    assert Decimal(rows[-1]["resources"]["online_money_acquired_cumulative"]) == Decimal(rows[-1]["resources"]["generated_money"]) + Decimal(rows[-1]["resources"]["online_codex_money_cumulative"])
    assert rows[-1]["generators_owned"]["deployed_fish"] >= 1
    assert any(event["kind"] == "complete_throw" for event in events)
    assert all("receipt" in event["details"] for event in events if event["kind"] == "complete_throw")
    assert manifest["source_runtime"]["code_sha256"]
    assert manifest["source_runtime"]["integration_code_sha256"]
    assert manifest["source_runtime"]["selected_export_sha256"]
    assert manifest["source_runtime"]["timings_seconds"]["adapter_total"] > 0
    assert "source_progression.json" in manifest["artifacts"]
    assert "source_behavior.json" in manifest["artifacts"]
    progression = json.loads((output / "source_progression.json").read_text(encoding="utf-8"))
    assert progression["profiles"]["default"][-1]["fish_luck"] == rows[-1]["resources"]["fish_luck"]
    behavior = json.loads((output / "source_behavior.json").read_text(encoding="utf-8"))
    throws = sum(event["kind"] == "complete_throw" for event in events)
    assert behavior["profiles"]["default"]["accepted_commands"]["complete_throw"] == throws
    assert (output / "final_checkpoint.json").is_file()
    assert Path(response.result["report_index"]).is_file()
    report_data = json.loads(
        (Path(response.result["report_index"]).parent / "report_data.json").read_text(encoding="utf-8")
    )
    assert "source_progression" in report_data["artifacts"]
    assert "source_behavior" in report_data["artifacts"]
    assert "luck_progression" not in report_data["artifacts"]
    assert report_data["fish_progression"]["available"] is True
    assert report_data["fish_progression"]["core"]["profiles"]["default"]["rows"]
    assert report_data["overview"]["throw_count"]["exact_value"] == str(throws)
    balance = report_data["fish_progression"]["balance"]["profiles"]["default"]
    assert balance["rate_rows"]
    assert balance["cumulative_rows"][-1]["money_acquired_cumulative"]["chart_value"] > 0


def test_formal_source_checkpoint_resumes_and_data_change_invalidates_it(tmp_path: Path) -> None:
    project = _project(tmp_path)
    first = AuthoringService(project).simulate("smoke")
    assert first.ok, first.details
    first_output = Path(first.result["output_dir"])
    checkpoint = first_output / "final_checkpoint.json"
    resumed = AuthoringService(project).simulate("smoke", checkpoint_input=checkpoint)
    assert resumed.ok, resumed.details
    resumed_rows = json.loads((Path(resumed.result["output_dir"]) / "timeline.json").read_text())
    first_rows = json.loads((first_output / "timeline.json").read_text())
    assert resumed_rows[-1] == first_rows[-1]

    hall = project / "production_snapshot" / "json" / "tbfishhallupgrade.json"
    rows = json.loads(hall.read_text(encoding="utf-8"))
    rows[0]["upgradePrice"]["scale"] += 1
    hall.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    changed = AuthoringService(project).simulate("smoke", checkpoint_input=checkpoint)
    assert not changed.ok
    assert changed.result["status"] == "failed"
    assert changed.result["model_digest"] != first.result["model_digest"]


def test_formal_source_rejects_unmodeled_multiplier_before_run(tmp_path: Path) -> None:
    project = _project(tmp_path)
    config_path = project / "economy.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["player_profiles"]["default"]["source_efficiency"]["offline"] = "1.2"
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")

    response = AuthoringService(project).simulate("smoke")
    assert not response.ok
    assert response.code == "fish_source_profile_unsupported"


def test_formal_source_rejects_legacy_target_policy_before_run(tmp_path: Path) -> None:
    project = _project(tmp_path)
    config_path = project / "economy.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["player_profiles"]["default"]["behavior_target_policies"] = {
        "sell_fish": "keep_deployed_and_top_quality",
    }
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")

    response = AuthoringService(project).simulate("smoke")
    assert not response.ok
    assert response.code == "fish_source_target_policy_unsupported"


def test_formal_source_missing_runtime_fails_before_reserving_run(tmp_path: Path) -> None:
    project = _project(tmp_path)
    config_path = project / "economy.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["engine"]["source_runtime"]["project_root"] = str(project / "missing-source")
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")

    response = AuthoringService(project).simulate("smoke")
    assert not response.ok
    assert response.code == "fish_source_root_missing"
    assert not list((project / "runs").glob("*"))


def test_formal_source_batch_mode_matches_exact_session_observations(tmp_path: Path) -> None:
    project = _project(tmp_path)
    config_path = project / "economy.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["scenarios"]["smoke"]["duration_hours"] = "0.05"
    config["scenarios"]["smoke"]["record_interval_seconds"] = 10
    config["engine"]["source_runtime"]["collect_interval_seconds"] = 60
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    exact = AuthoringService(project).simulate("smoke")
    assert exact.ok, exact.details

    config["engine"]["source_runtime"]["advance_mode"] = "equivalent_batch_v1"
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    batched = AuthoringService(project).simulate("smoke")
    assert batched.ok, batched.details
    for name in ("timeline.json", "events.json", "source_progression.json", "source_behavior.json"):
        exact_data = json.loads((Path(exact.result["output_dir"]) / name).read_text(encoding="utf-8"))
        batched_data = json.loads((Path(batched.result["output_dir"]) / name).read_text(encoding="utf-8"))
        assert batched_data == exact_data, name


@pytest.mark.parametrize("strength,expected", [("2", False), ("3000000000", True)])
def test_formal_source_funds_breakthrough_only_after_actual_landing(tmp_path, monkeypatch, strength, expected):
    import subprocess
    project = _project(tmp_path)
    script = "package.path='./?.lua;./proj/?.lua;'..package.path; local s=require('Script.Domain.Player.PlayerArchiveSchema').New(0); io.write(require('simulation.Json').Encode(s))"
    state = json.loads(subprocess.check_output(['lua55', '-e', script], cwd=FISH_SOURCE, text=True))
    state['wallet']['strength'] = {'sign': 1, 'coeff': strength.rstrip('0'), 'exp': len(strength)-len(strength.rstrip('0'))}
    state['wallet']['material'] = {'sign': 1, 'coeff': '1', 'exp': 6}
    create = FishSourceRuntime.create
    def fixture(self, **kwargs):
        kwargs['initial_state'] = state
        return create(self, **kwargs)
    monkeypatch.setattr(FishSourceRuntime, 'create', fixture)
    path = project / 'economy.yaml'
    config = yaml.safe_load(path.read_text(encoding='utf-8'))
    config['engine']['source_runtime']['advance_mode'] = 'equivalent_batch_v1'
    config['player_profiles']['default']['behavior_weights'] = {'manual_throw': '1', 'fund_trash_man_breakthrough': '10'}
    config['scenarios']['smoke']['duration_hours'] = '0.05'
    path.write_text(yaml.safe_dump(config), encoding='utf-8')
    response = AuthoringService(project).simulate('smoke')
    assert response.ok, response.details
    events = json.loads((Path(response.result['output_dir']) / 'events.json').read_text(encoding='utf-8'))
    funding = [e for e in events if e['kind'] == 'start_breakthrough']
    assert bool(funding) is expected
    if expected:
        unlock = next(e for e in events if e['kind'] == 'treasure_beast_unlocked')
        assert all(e['time_seconds'] >= unlock['time_seconds'] for e in funding)
        receipt = json.loads(funding[0]['details']['receipt'])
        assert receipt['materialSpent']['sign'] == 1
    assert not any(e['kind'] == 'source_rejected' for e in events)


def test_formal_source_online_sampling_preserves_gameplay_and_crosses_sessions(tmp_path: Path) -> None:
    project = _project(tmp_path)
    config_path = project / "economy.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["engine"]["source_runtime"]["advance_mode"] = "equivalent_batch_v1"
    config["scenarios"]["smoke"]["duration_hours"] = "48"
    config["scenarios"]["smoke"]["record_interval_seconds"] = 86400
    profile = config["player_profiles"]["default"]
    config["session_patterns"][profile["session_pattern"]]["daily_online_seconds"] = 350
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    sparse = AuthoringService(project).simulate("smoke")
    assert sparse.ok, sparse.details

    config["engine"]["source_runtime"]["sampling_time_basis"] = "online"
    config["scenarios"]["smoke"]["record_interval_seconds"] = 300
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    dense = AuthoringService(project).simulate("smoke")
    assert dense.ok, dense.details
    sparse_output, dense_output = (Path(run.result["output_dir"]) for run in (sparse, dense))

    def read(output: Path, name: str):
        return json.loads((output / name).read_text(encoding="utf-8"))

    rows = read(dense_output, "timeline.json")
    times = {row["time_seconds"] for row in rows}
    assert {0, 300, 350, 86400, 86650, 86750, 172800} <= times
    assert not any(350 < time < 86400 or 86750 < time < 172800 for time in times)
    assert rows[-1] == read(sparse_output, "timeline.json")[-1]
    for name in ("events.json", "source_behavior.json"):
        assert read(dense_output, name) == read(sparse_output, name), name
    checkpoint = read(dense_output, "final_checkpoint.json")
    assert checkpoint["behavior_state"]["active_time_seconds"] == 700
    assert checkpoint["behavior_state"]["online_acquisition"]["money"] == rows[-1]["resources"]["online_money_acquired_cumulative"]
    report = read(Path(dense.result["report_index"]).parent, "report_data.json")
    assert "300 秒采样" in report["fish_progression"]["notes"]["core"]
