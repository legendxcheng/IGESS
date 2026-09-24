"""Source Fish is verified through the existing formal authoring entry."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

from igess.authoring.service import AuthoringService

ROOT = Path(__file__).resolve().parents[1]
FISH_SOURCE = Path("E:/fish-oasis")
pytestmark = pytest.mark.skipif(
    not (FISH_SOURCE / "simulation" / "cli.lua").is_file(),
    reason="Fish source checkout is not available",
)


def _project(tmp_path: Path) -> Path:
    origin = ROOT / "projects" / "fish"
    project = tmp_path / "fish"
    project.mkdir()
    shutil.copytree(origin / "Datas", project / "Datas")
    shutil.copytree(origin / "luban_exports", project / "luban_exports")
    shutil.copytree(origin / "production_snapshot" / "json", project / "production_snapshot" / "json")
    config = yaml.safe_load((origin / "economy.yaml").read_text(encoding="utf-8"))
    config["model"]["engine_id"] = "fish_source"
    config["engine"] = {
        "source_runtime": {
            "project_root": str(FISH_SOURCE),
            "data_root": "production_snapshot/json",
            "lua_executable": "lua55",
            "in_fishing_area": True,
            "landing_distance_cm": 100,
            "collect_interval_seconds": 300,
            "idle_seconds": 30,
        },
    }
    config["behavior_policies"]["source_priority_v1"] = {"type": "source_priority_v1"}
    for profile in config["player_profiles"].values():
        profile["behavior_policy"] = "source_priority_v1"
        profile.pop("behavior_target_policies", None)
    (project / "economy.yaml").write_text(
        yaml.safe_dump(config, allow_unicode=True), encoding="utf-8",
    )
    return project


def test_formal_source_smoke_uses_lua_receipts_and_writes_report(tmp_path: Path) -> None:
    project = _project(tmp_path)
    response = AuthoringService(project).simulate("smoke")

    assert response.ok, response.details
    assert response.result["engine_id"] == "fish_source"
    output = Path(response.result["output_dir"])
    rows = json.loads((output / "timeline.json").read_text(encoding="utf-8"))
    events = json.loads((output / "events.json").read_text(encoding="utf-8"))
    manifest = json.loads((output / "run_manifest.json").read_text(encoding="utf-8"))
    assert rows[-1]["resources"]["money"] == "0"
    assert rows[-1]["resources"]["unclaimed_money"] != "0"
    assert rows[-1]["resources"]["generated_money"] == rows[-1]["resources"]["unclaimed_money"]
    assert rows[-1]["generators_owned"]["deployed_fish"] == 1
    assert any(event["kind"] == "complete_throw" for event in events)
    assert all("receipt" in event["details"] for event in events)
    assert manifest["source_runtime"]["code_sha256"]
    assert manifest["source_runtime"]["integration_code_sha256"]
    assert manifest["source_runtime"]["selected_export_sha256"]
    assert manifest["source_runtime"]["timings_seconds"]["adapter_total"] > 0
    assert "source_progression.json" in manifest["artifacts"]
    assert "source_behavior.json" in manifest["artifacts"]
    progression = json.loads((output / "source_progression.json").read_text(encoding="utf-8"))
    assert progression["profiles"]["default"][-1]["fish_luck"] == rows[-1]["resources"]["fish_luck"]
    behavior = json.loads((output / "source_behavior.json").read_text(encoding="utf-8"))
    assert behavior["profiles"]["default"]["accepted_commands"]["complete_throw"] == 1
    assert (output / "final_checkpoint.json").is_file()
    assert Path(response.result["report_index"]).is_file()
    report_data = json.loads(
        (Path(response.result["report_index"]).parent / "report_data.json").read_text(encoding="utf-8")
    )
    assert "source_progression" in report_data["artifacts"]
    assert "source_behavior" in report_data["artifacts"]
    assert "luck_progression" not in report_data["artifacts"]


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


def test_formal_source_funds_breakthrough_before_source_training(tmp_path: Path) -> None:
    project = _project(tmp_path)
    config_path = project / "economy.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["engine"]["source_runtime"]["advance_mode"] = "equivalent_batch_v1"
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")

    response = AuthoringService(project).simulate("day_1_growth")

    assert response.ok, response.details
    behavior = json.loads(
        (Path(response.result["output_dir"]) / "source_behavior.json").read_text(encoding="utf-8")
    )
    assert behavior["profiles"]["default"]["accepted_commands"]["start_breakthrough"] >= 2
