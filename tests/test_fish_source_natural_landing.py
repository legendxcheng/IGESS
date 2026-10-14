"""Natural throws are verified at the source session and formal-run seams."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from igess.authoring.service import AuthoringService
from igess.fish_source_runtime import FishSourceRuntime

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get("FISH_SOURCE_ROOT", str(ROOT.parent / "fish-oasis")))
pytestmark = pytest.mark.skipif(not (SOURCE / "simulation/cli.lua").exists(), reason="paired Fish source unavailable")


def project(tmp_path):
    target = tmp_path / "fish_source"
    target.mkdir()
    for directory in ("Datas", "luban_exports"):
        shutil.copytree(ROOT / "projects/fish_source" / directory, target / directory)
    shutil.copyfile(ROOT / "projects/fish_source/economy.yaml", target / "economy.yaml")
    config = yaml.safe_load((target / "economy.yaml").read_text(encoding="utf-8"))
    config["engine"]["source_runtime"].update(project_root=str(SOURCE), data_root=str(SOURCE / "igess_export/json"))
    config["engine"]["source_runtime"].pop("landing_distance_cm", None)
    (target / "economy.yaml").write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    return target


def test_formal_throw_uses_source_natural_target_and_real_flight_time(tmp_path):
    result = AuthoringService(project(tmp_path)).simulate("smoke")
    assert result.ok, result.details
    output = Path(result.result["output_dir"])
    events = json.loads((output / "events.json").read_text(encoding="utf-8"))
    prepared = next(e for e in events if e["kind"] == "prepare_throw")
    plan = json.loads(prepared["details"]["receipt"])["naturalLanding"]
    finalized = next(e for e in events if e["kind"] == "finalize_throw_landing")
    receipt = json.loads(finalized["details"]["receipt"])
    assert receipt["targetDistanceCm"] == plan["distanceCm"]
    assert finalized["time_seconds"] - prepared["time_seconds"] >= plan["flightSeconds"]
    assert not any(e["kind"] == "source_rejected" for e in events)
    manifest = json.loads((output / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_runtime"]["landing_policy"] == "source_natural_v1"
    progression = json.loads((output / "source_progression.json").read_text(encoding="utf-8"))
    assert progression["profiles"]["default"][0]["treasure_beast_unlocked"] == "0"


def initial_state(strength="3000000000"):
    code = ('package.path="./?.lua;./proj/?.lua;"..package.path; '
            'local s=require("Script.Domain.Player.PlayerArchiveSchema").New(0); '
            'local ok,dto=require("Script.Domain.Player.BigNumberSaveAdapter").ToDTO('
            f'require("Script.Core.BigNumber").new("{strength}"),{{allowNegative=false}}); '
            'assert(ok); s.wallet.strength=dto; '
            'io.write(require("simulation.Json").Encode(s))')
    return json.loads(subprocess.check_output(["lua55", "-e", code], cwd=SOURCE, text=True))


@pytest.mark.parametrize("distance,unlocked", [(21000, False), (21001, True)])
def test_actual_impact_boundary_and_source_checkpoint_restore(distance, unlocked):
    args = dict(project_root=SOURCE, data_root=SOURCE / "igess_export/json", lua_executable="lua55")
    with FishSourceRuntime(**args) as original, FishSourceRuntime(**args) as resumed:
        state = original.create(start_at=0, initial_state=initial_state(), in_fishing_area=True, random_seed=42)
        assert state["trashMan"]["unlocked"] is False
        plan = original.request({"op": "prepare_throw", "requestId": "boundary"})["naturalLanding"]
        original.request({"op": "begin_throw_flight", "requestId": "boundary"})
        original.request({"op": "advance", "time": 10})
        original.request({"op": "select_throw_landing", "requestId": "boundary", "distanceCm": distance})
        assert original.request({"op": "query"})["trashMan"]["unlocked"] is False
        assert resumed.restore(original.checkpoint()) == original.request({"op": "query"})
        for op in ("finalize_throw_landing", "complete_throw", "complete_throw"):
            left = original.request({"op": op, "requestId": "boundary"})
            assert resumed.request({"op": op, "requestId": "boundary"}) == left
        assert (left["summary"]["trashQuantity"] > 0) is unlocked
        state = original.request({"op": "query"})
        assert state["trashMan"]["unlocked"] is unlocked
        assert state == resumed.request({"op": "query"})
        assert plan["distanceCm"] > distance
        if unlocked:
            rebirth = original.request({"op": "rebirth_strength", "requestId": "reset-strength", "revision": state["revision"]})
            assert rebirth["newCompletedCount"] == 1
            assert original.request({"op": "query"})["trashMan"]["unlocked"] is True
            with FishSourceRuntime(**args) as after_rebirth:
                assert after_rebirth.restore(original.checkpoint()) == original.request({"op": "query"})


def high_strength_project(tmp_path):
    target = project(tmp_path)
    # A separate test source identity accelerates the otherwise long growth
    # path. The selected production checkout and its export stay untouched.
    source = tmp_path / "source-fixture"
    for directory in ("proj/Script", "simulation"):
        shutil.copytree(SOURCE / directory, source / directory)
    gameplay = source / "proj/Script/Config/FishGameplayConfig.lua"
    gameplay.write_text(gameplay.read_text(encoding="utf-8").replace("initialStrength = 2,", "initialStrength = 3000000000,"), encoding="utf-8")
    config = yaml.safe_load((target / "economy.yaml").read_text(encoding="utf-8"))
    config["engine"]["source_runtime"]["project_root"] = str(source)
    config["player_profiles"]["default"]["behavior_weights"] = {"manual_throw": "1"}
    config["scenarios"]["smoke"]["duration_hours"] = "0.01"
    (target / "economy.yaml").write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    return target


def test_formal_report_records_actual_treasure_beast_unlock(tmp_path):
    result = AuthoringService(high_strength_project(tmp_path)).simulate("smoke")
    assert result.ok, result.details
    report = json.loads((Path(result.result["report_index"]).parent / "report_data.json").read_text(encoding="utf-8"))
    rows = report["fish_progression"]["persistent"]["profiles"]["default"]["rows"]
    unlocked = [row for row in rows if row["progression_category"] == "treasure_beast"]
    assert len(unlocked) == 1
    assert unlocked[0]["wall_time_seconds"] > 0
    assert unlocked[0]["active_time_seconds"] == unlocked[0]["wall_time_seconds"]
    assert unlocked[0]["area_index"] >= 4
    assert unlocked[0]["metric_before"]["exact_value"] == "0"
    assert unlocked[0]["metric_after"]["exact_value"] == "1"


def test_formal_truncation_keeps_pending_flight_without_early_rewards(tmp_path):
    target = high_strength_project(tmp_path)
    config_path = target / "economy.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["scenarios"]["smoke"]["duration_hours"] = str(1 / 3600)
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    first = AuthoringService(target).simulate("smoke")
    assert first.ok, first.details
    output = Path(first.result["output_dir"])
    checkpoint_path = output / "final_checkpoint.json"
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert checkpoint["behavior_state"]["pending_throw"]["landing_at"] > 1
    events = json.loads((output / "events.json").read_text(encoding="utf-8"))
    assert not any(e["kind"] in {"complete_throw", "treasure_beast_unlocked"} for e in events)
    resumed = AuthoringService(target).simulate("smoke", checkpoint_input=checkpoint_path)
    assert resumed.ok, resumed.details
    restored = json.loads((Path(resumed.result["output_dir"]) / "final_checkpoint.json").read_text(encoding="utf-8"))
    assert restored["behavior_state"]["pending_throw"] == checkpoint["behavior_state"]["pending_throw"]
