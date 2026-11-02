"""Collect-all policy at the formal Lua simulation and recovery boundaries."""
import json
from decimal import Decimal

import pytest
import yaml

from igess.fish_source_engine import _unpack_session
from igess.fish_source_numbers import source_decimal
from igess.fish_source_runtime import FishSourceRejection, FishSourceRuntime
from test_fish_source_joint import SOURCE, archive, initial, project, run

pytestmark = pytest.mark.skipif(
    not (SOURCE / "simulation/cli.lua").is_file(), reason="Fish source checkout unavailable",
)


def collection_project(tmp_path, monkeypatch, *, duration=320, online=7200, tide_at=1000, gun=False):
    state = archive("""
s.fishHall.upgradeLevel=2
for i=1,3 do
    s.fish.items[i]={instanceId=i,fishId=101,mutationId=1,weightGram=1000,level=1,hallSlot=i}
end
s.fish.nextInstanceId=4
""")
    if gun:
        state["wallet"]["material"] = {"sign": 1, "coeff": "3", "exp": 2}
        state["combat"].update(ownedGunIds=[10001], equippedGunId=10001, lastSelectedGunId=10001)
    initial(monkeypatch, state)
    target = project(tmp_path, duration=duration)
    path = target / "economy.yaml"
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    config["engine"]["source_runtime"].update(idle_seconds=1, room_origin_seconds=tide_at)
    # Observe every second so uninterrupted and cut runs have identical source
    # advance boundaries, allowing an exact operation/receipt history comparison.
    config["scenarios"]["smoke"]["record_interval_seconds"] = 1
    profile = config["player_profiles"]["default"]
    config["session_patterns"][profile["session_pattern"]]["daily_online_seconds"] = online
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return target


def collected(events):
    return [(e["time_seconds"], int(e["item_id"])) for e in events if e["kind"] == "collect_slot"]


def test_collect_all_visits_each_producing_slot_once_per_cycle(tmp_path, monkeypatch):
    target = collection_project(tmp_path, monkeypatch)
    _, read, _ = run(target)
    events = read("events.json")
    assert collected(events) == [(1, 1), (3, 2), (5, 3), (301, 1), (303, 2), (305, 3)]
    assert not any(e["kind"] == "source_rejected" for e in events)
    final = read("timeline.json")[-1]["resources"]
    # Collection moves money; it must not count as additional production.
    assert Decimal(final["money"]) == Decimal(final["collected_money"])
    receipts = [json.loads(e["details"]["receipt"]) for e in events if e["kind"] == "collect_slot"]
    amounts = [source_decimal(receipt["moneyCollected"]) for receipt in receipts]
    assert sum(amounts) == Decimal(final["collected_money"])
    assert 0 < amounts[0] < amounts[1] < amounts[2]  # Production continues during collection.
    assert Decimal(final["generated_money"]) == Decimal(final["money"]) + Decimal(final["unclaimed_money"])
    assert Decimal(final["online_money_acquired_cumulative"]) == Decimal(final["generated_money"])
    metadata = read("run_manifest.json")["source_runtime"]
    assert metadata["collect_policy"] == "stable_slot_batch_v1"
    assert metadata["collect_slot_seconds"] == 2
    assert metadata["collect_interval_basis"] == "batch_start"


@pytest.mark.parametrize("cutoff", [1, 2, 3, 4, 5, 6, 7])
def test_collect_all_resume_preserves_commands_money_and_remaining_time(tmp_path, monkeypatch, cutoff):
    target = collection_project(tmp_path, monkeypatch, duration=12)
    _, expected, _ = run(target)
    first, before, _ = run(target, until_seconds=cutoff)
    _, after, _ = run(target, checkpoint_input=first / "final_checkpoint.json")
    assert before("events.json") + after("events.json") == expected("events.json")
    actual_checkpoint = after("final_checkpoint.json")
    expected_checkpoint = expected("final_checkpoint.json")
    assert actual_checkpoint["behavior_state"] == expected_checkpoint["behavior_state"]
    # Complete source operation / receipt history, not just the final wallet.
    assert _unpack_session(actual_checkpoint["engine_state"]) == _unpack_session(expected_checkpoint["engine_state"])
    assert after("timeline.json")[-1] == expected("timeline.json")[-1]


def test_rejected_collection_does_not_starve_remaining_slots(tmp_path, monkeypatch):
    target = collection_project(tmp_path, monkeypatch, duration=8)
    request = FishSourceRuntime.request
    attempted = []

    def reject_second_slot(self, payload, **kwargs):
        if payload["op"] == "collect_slot":
            attempted.append(payload["slot"])
            if payload["slot"] == 2:
                raise FishSourceRejection("fixture_collection_rejected")
        return request(self, payload, **kwargs)

    monkeypatch.setattr(FishSourceRuntime, "request", reject_second_slot)
    _, read, _ = run(target)
    assert attempted == [1, 2, 3]
    assert collected(read("events.json")) == [(1, 1), (5, 3)]
    rejected = [e for e in read("events.json") if e["kind"] == "source_rejected"]
    assert [(e["time_seconds"], e["details"]["code"]) for e in rejected] == [(3, "fixture_collection_rejected")]
    assert read("final_checkpoint.json")["behavior_state"]["pending_collect_slots"] == []


@pytest.mark.parametrize("boundary", ["tide", "logout"])
def test_collect_all_keeps_unvisited_slots_across_session_boundaries(tmp_path, monkeypatch, boundary):
    if boundary == "tide":
        target = collection_project(tmp_path, monkeypatch, duration=130, tide_at=4, gun=True)
        expected_collections = [(1, 1), (4, 2), (6, 3)]
    else:
        target = collection_project(tmp_path, monkeypatch, duration=86404, online=4)
        expected_collections = [(1, 1), (86400, 2), (86402, 3)]
    _, expected, _ = run(target)
    assert collected(expected("events.json")) == expected_collections
    first, before, _ = run(target, until_seconds=4)
    assert before("final_checkpoint.json")["behavior_state"]["pending_collect_slots"] == [2, 3]
    _, after, _ = run(target, checkpoint_input=first / "final_checkpoint.json")
    assert collected(before("events.json") + after("events.json")) == expected_collections
    assert after("final_checkpoint.json")["behavior_state"] == expected("final_checkpoint.json")["behavior_state"]
    assert _unpack_session(after("final_checkpoint.json")["engine_state"]) == _unpack_session(expected("final_checkpoint.json")["engine_state"])
    assert after("timeline.json")[-1] == expected("timeline.json")[-1]
