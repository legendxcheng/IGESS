"""Purchased permanent benefits use production grants and survive real restore."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from igess.authoring.service import AuthoringService
from igess.fish_source_runtime import FishSourceRuntime, FishSourceRuntimeError
from igess.fish_source_engine import _unpack_session
from test_fish_source_formal import FISH_SOURCE, _project

pytestmark = pytest.mark.skipif(
    not (FISH_SOURCE / "simulation/cli.lua").is_file(), reason="Fish source unavailable",
)


def test_source_grants_selected_catalog_and_restores_without_regrant_history():
    rows = json.loads((FISH_SOURCE / "igess_export/json/tbitemgm.json").read_text("utf-8"))
    expected = sorted(r["id"] for r in rows if r["isPrivilege"] and not r["isTimedBuff"] and r["isForSale"])
    with FishSourceRuntime(FISH_SOURCE, FISH_SOURCE / "igess_export/json") as runtime:
        initial = runtime.create(start_at=0, permanent_privilege_mode="all_on_sale")
        benefits = runtime.request({"op": "query_permanent_privileges"})
        assert benefits["grantedItemIds"] == expected
        assert all(not item["receipt"]["alreadyOwned"] for item in benefits["items"])
        assert benefits["modifiers"]["FishHallMoneyMultiplier"] == 2
        assert benefits["modifiers"]["TrashMaterialMultiplier"] == 2
        assert benefits["modifiers"]["ThrowSpeedMultiplier"] == 2
        assert benefits["modifiers"]["ExerciseSpeedMultiplier"] == 1
        assert benefits["autoThrowUnlocked"] is True
        assert benefits["collectAllMoneyUnlocked"] is False
        assert initial["wallet"]["money"]["sign"] == 0
        assert initial["wallet"]["material"]["sign"] == 0
        assert runtime.checkpoint()["history"] == []
        runtime.request({"op": "go_offline"})
        runtime.request({"op": "advance", "time": 86400})
        assert runtime.request({"op": "query_permanent_privileges"}) == benefits
        state = runtime.request({"op": "query"})
        checkpoint = runtime.checkpoint()
    with FishSourceRuntime(FISH_SOURCE, FISH_SOURCE / "igess_export/json") as restored:
        assert restored.restore(checkpoint) == state
        assert restored.request({"op": "query_permanent_privileges"}) == benefits
        assert restored.checkpoint() == checkpoint


def test_source_rejects_unknown_privilege_mode():
    with FishSourceRuntime(FISH_SOURCE, FISH_SOURCE / "igess_export/json") as runtime:
        with pytest.raises(FishSourceRuntimeError, match="simulation_permanent_privilege_mode_invalid"):
            runtime.create(start_at=0, permanent_privilege_mode="free_multiplier")


def test_purchased_throw_speed_changes_real_source_flight():
    plans = []
    for mode in (None, "all_on_sale"):
        with FishSourceRuntime(FISH_SOURCE, FISH_SOURCE / "igess_export/json") as runtime:
            runtime.create(start_at=0, random_seed=2031507854,
                           in_fishing_area=True, permanent_privilege_mode=mode)
            plans.append(runtime.request({"op": "prepare_throw", "requestId": "benefit-check"}))
    free, paid = plans
    assert free["throwSpeedMultiplier"] == 1 and paid["throwSpeedMultiplier"] == 2
    assert free["naturalLanding"]["distanceCm"] == paid["naturalLanding"]["distanceCm"]
    # The host rounds each flight up to a whole millisecond.
    free_ms = round(free["naturalLanding"]["flightSeconds"] * 1000)
    paid_ms = round(paid["naturalLanding"]["flightSeconds"] * 1000)
    assert paid_ms == (free_ms + 1) // 2
    assert paid["fishLuck"] == free["fishLuck"]  # In-sale privileges do not include Fish Luck.


def test_paid_formal_run_matches_continuation_and_cannot_resume_as_free(tmp_path):
    project = _project(tmp_path)
    path = project / "economy.yaml"
    config = yaml.safe_load(path.read_text("utf-8"))
    config["engine"]["source_runtime"]["advance_mode"] = "equivalent_batch_v1"
    for scenario in ("smoke", "smoke_all_permanent"):
        config["scenarios"][scenario]["duration_hours"] = "0.1666666666666667"
        config["scenarios"][scenario]["record_interval_seconds"] = 300
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    service = AuthoringService(project)
    def run(scenario, **kwargs):
        response = service.simulate(scenario, **kwargs)
        assert response.ok, response.details
        output = Path(response.result["output_dir"])
        return output, lambda name: json.loads((output / name).read_text("utf-8"))
    full, full_read = run("smoke_all_permanent")
    partial, part_read = run("smoke_all_permanent", until_seconds=31)
    continued, continued_read = run("smoke_all_permanent", checkpoint_input=partial / "final_checkpoint.json")
    a, b = full_read("final_checkpoint.json"), continued_read("final_checkpoint.json")
    assert a["behavior_state"] == b["behavior_state"]
    assert full_read("timeline.json")[-1] == continued_read("timeline.json")[-1]
    assert _unpack_session(a["engine_state"]) == _unpack_session(b["engine_state"])
    benefits = full_read("run_manifest.json")["source_profiles"]["default"]["permanent_privileges"]
    rows = json.loads((project / "production_snapshot/json/tbitemgm.json").read_text("utf-8"))
    expected = sorted(r["id"] for r in rows if r["isPrivilege"] and not r["isTimedBuff"] and r["isForSale"])
    assert benefits["mode"] == "all_on_sale" and benefits["grantedItemIds"] == expected
    assert a["root_random_seed"] == 2031507854
    assert _unpack_session(a["engine_state"])["origin"]["permanentPrivilegeMode"] == "all_on_sale"
    response = service.simulate("month_1_growth", checkpoint_input=partial / "final_checkpoint.json", until_seconds=600)
    assert not response.ok
    assert "fish_source_checkpoint_privileges_mismatch" in str(response)
    _, free_read = run("smoke")
    assert free_read("final_checkpoint.json")["root_random_seed"] == a["root_random_seed"]
    assert free_read("run_manifest.json")["source_profiles"]["default"]["permanent_privileges"]["mode"] == "none"
    assert full_read("timeline.json")[-1]["resources"] != free_read("timeline.json")[-1]["resources"]
