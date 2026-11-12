"""Monthly card source transactions, daily claims and cross-process recovery."""
import json
from pathlib import Path

import pytest
import yaml

from igess.authoring.service import AuthoringService
from igess.fish_source_engine import _unpack_session
from igess.fish_source_runtime import FishSourceRuntime, FishSourceRuntimeError
from test_fish_source_formal import FISH_SOURCE, _project

pytestmark = pytest.mark.skipif(
    not (FISH_SOURCE / "simulation/cli.lua").is_file(), reason="Fish source unavailable",
)


def query(runtime):
    return runtime.request({"op": "query_monthly_card"})


def jump(runtime, at):
    runtime.request({"op": "go_offline"})
    runtime.request({"op": "advance", "time": at})
    runtime.request({"op": "go_online"})


@pytest.mark.parametrize("mode", [None, "monthly_once"])
def test_monthly_query_is_read_only_offline_and_restorable(mode):
    with FishSourceRuntime(FISH_SOURCE, FISH_SOURCE / "igess_export/json") as runtime:
        runtime.create(start_at=0, monthly_card_mode=mode)
        before = query(runtime)
        runtime.request({"op": "go_offline"})
        checkpoint = runtime.checkpoint()
        assert query(runtime) == before
        assert runtime.checkpoint() == checkpoint
        with pytest.raises(FishSourceRuntimeError, match="simulation_player_offline"):
            runtime.request({"op": "claim_monthly_card"})
        checkpoint = runtime.checkpoint()
    with FishSourceRuntime(FISH_SOURCE, FISH_SOURCE / "igess_export/json") as restored:
        state = restored.restore(checkpoint)
        assert state["online"] is False
        assert query(restored) == before
        assert restored.checkpoint() == checkpoint
        restored.request({"op": "go_online"})
        if mode:
            assert restored.request({"op": "claim_monthly_card"})["success"]
            assert query(restored)["nativeInventory"] == [{"itemId": 8310011, "count": 4}]


def test_month1_final_offline_snapshot_writes_manifest_report_and_checkpoint(tmp_path):
    project = _project(tmp_path)
    path = project / "economy.yaml"
    config = yaml.safe_load(path.read_text("utf-8"))
    # Keep the actual Month1 boundary and purchase preset; shorten online work
    # only in this fixture to reach the failing finalisation path quickly.
    config["session_patterns"]["authoring_default"]["daily_online_seconds"] = 2
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    response = AuthoringService(project).simulate("month_1_monthly_all_permanent")
    assert response.ok, response
    output = Path(response.result["output_dir"])
    manifest = json.loads((output / "run_manifest.json").read_text("utf-8"))
    final = manifest["source_profiles"]["default"]["monthly_card_final"]
    assert final["snapshot"]["serverTime"] == 28 * 86400
    assert final["nativeInventory"] == [{"itemId": 8310011, "count": 58}]
    checkpoint = json.loads((output / "final_checkpoint.json").read_text("utf-8"))
    with FishSourceRuntime(FISH_SOURCE, FISH_SOURCE / "igess_export/json") as runtime:
        assert runtime.restore(_unpack_session(checkpoint["engine_state"]))["online"] is False
        assert query(runtime) == final
    assert Path(response.result["report_index"]).is_file()


def test_monthly_card_claims_expiry_and_real_process_restore():
    with FishSourceRuntime(FISH_SOURCE, FISH_SOURCE / "igess_export/json") as runtime:
        runtime.create(start_at=0, monthly_card_mode="monthly_once", permanent_privilege_mode="all_on_sale")
        initial = query(runtime)
        assert initial["ledger"]["cards"]["2"]["purchaseCount"] == 1
        assert initial["ledger"]["cards"]["2"]["expiresAt"] == 30 * 86400
        assert initial["nativeInventory"] == [{"itemId": 8310011, "count": 2}]
        assert initial["modifiers"]["ExerciseSpeedMultiplier"] == 2
        assert runtime.checkpoint()["history"] == []  # queries never replay
        for day in range(28):
            if day:
                jump(runtime, day * 86400)
            assert runtime.request({"op": "claim_monthly_card"})["success"]
            before = query(runtime)
            assert runtime.request({"op": "claim_monthly_card"})["success"]
            assert query(runtime) == before  # same day has no duplicate grant
        assert query(runtime)["nativeInventory"] == [{"itemId": 8310011, "count": 58}]
        checkpoint = runtime.checkpoint()
        observed = runtime.request({"op": "query"})
        purchased = query(runtime)
    with FishSourceRuntime(FISH_SOURCE, FISH_SOURCE / "igess_export/json") as restored:
        assert restored.restore(checkpoint) == observed
        assert query(restored) == purchased
        assert restored.checkpoint() == checkpoint
        jump(restored, 30 * 86400 - 1)
        assert query(restored)["modifiers"]["ExerciseSpeedMultiplier"] == 2
        jump(restored, 30 * 86400)
        assert query(restored)["modifiers"]["ExerciseSpeedMultiplier"] == 1
        with pytest.raises(FishSourceRuntimeError, match="card_expired"):
            restored.request({"op": "claim_monthly_card"})


def test_monthly_card_changes_real_exercise_cycles_and_business_day_boundary():
    outcomes = []
    for mode in (None, "monthly_once"):
        with FishSourceRuntime(FISH_SOURCE, FISH_SOURCE / "igess_export/json") as runtime:
            runtime.create(start_at=0, monthly_card_mode=mode, fast_advance=True)
            start = runtime.request({"op": "start_exercise", "requestId": "start"})
            runtime.request({"op": "advance", "time": 60})
            stop = runtime.request({"op": "stop_exercise", "requestId": "stop"})
            outcomes.append((start, stop))
            if mode:
                runtime.request({"op": "claim_monthly_card"})
                jump(runtime, 57600 - 1)  # source UTC+8 business day
                card = next(c for c in query(runtime)["snapshot"]["cards"] if c["cardId"] == 2)
                assert not card["canClaim"]
                jump(runtime, 57600)
                assert runtime.request({"op": "claim_monthly_card"})["success"]
                assert query(runtime)["nativeInventory"][0]["count"] == 6
    free, paid = outcomes
    assert paid[0]["timeCost"] * 2 == free[0]["timeCost"]
    assert paid[0]["strengthPerExercise"] == free[0]["strengthPerExercise"]
    assert paid[1]["completedCycles"] == free[1]["completedCycles"] * 2


def test_monthly_formal_smoke_and_continuation(tmp_path):
    project = _project(tmp_path)
    service = AuthoringService(project)
    scenario = "smoke_monthly_all_permanent"

    def run(**kwargs):
        response = service.simulate(scenario, **kwargs)
        assert response.ok, response
        output = Path(response.result["output_dir"])
        return output, lambda name: json.loads((output / name).read_text("utf-8"))

    full, read = run()
    partial, _ = run(until_seconds=31)
    _, resumed = run(checkpoint_input=partial / "final_checkpoint.json")
    a, b = read("final_checkpoint.json"), resumed("final_checkpoint.json")
    assert a["behavior_state"] == b["behavior_state"]
    assert _unpack_session(a["engine_state"]) == _unpack_session(b["engine_state"])
    assert read("timeline.json")[-1] == resumed("timeline.json")[-1]
    profile = read("run_manifest.json")["source_profiles"]["default"]
    assert profile["monthly_card_final"]["nativeInventory"] == [{"itemId": 8310011, "count": 4}]
    assert profile["monthly_card"]["modifiers"]["ExerciseSpeedMultiplier"] == 2
    assert set(profile["monthly_card_final"]["ledger"]["cards"]) == {"2"}
    rows = json.loads((project / "production_snapshot/json/tbitemgm.json").read_text("utf-8"))
    expected = sorted(r["id"] for r in rows if r["isPrivilege"] and not r["isTimedBuff"] and r["isForSale"])
    assert profile["permanent_privileges"]["grantedItemIds"] == expected
    response = service.simulate("month_1_all_permanent", checkpoint_input=partial / "final_checkpoint.json", until_seconds=600)
    assert not response.ok and "fish_source_checkpoint_monthly_card_mismatch" in str(response)
