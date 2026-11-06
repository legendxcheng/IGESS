"""Check candidate intent against real Lua purchase receipts and replay."""
import json

import pytest
import yaml

from igess.fish_source_engine import _unpack_session
from igess.fish_source_growth_policy import growth_options
from igess.fish_source_runtime import FishSourceRejection, FishSourceRuntime
from test_fish_source_joint import SOURCE, archive, initial, project, run


def late_player():
    return archive("""
s.wallet.material={sign=1,coeff='1',exp=15}
s.torpedo.ownedIds={1,2,3,4,5,6,7,8};s.torpedo.selectedId=8
s.trashMan.unlocked=true
""")


def candidate_project(tmp_path, monkeypatch):
    initial(monkeypatch, late_player())
    target = project(tmp_path, duration=250, weights={
        "purchase_torpedo": "1e100", "manual_throw": "1",
        "exercise_barbell": "1", "upgrade_fish_hall": "1",
    })
    path = target / "selected/tbtorpedo.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    for row in rows:
        row["isOpen"] = row["id"] <= 15
        row["price"] = {"sign": 1, "digits": "100", "scale": 0}
    path.write_text(json.dumps(rows), encoding="utf-8")
    path = target / "economy.yaml"
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    config["engine"]["source_runtime"]["room_origin_seconds"] = 1000
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return target


@pytest.mark.parametrize("cutoff", [5, 10, 65])
def test_source_buys_nine_through_fifteen_then_other_actions_and_resumes(tmp_path, monkeypatch, cutoff):
    target = candidate_project(tmp_path, monkeypatch)
    _, expected, _ = run(target)
    events = expected("events.json")
    purchases = [json.loads(e["details"]["receipt"])["torpedoId"] for e in events if e["kind"] == "purchase_torpedo"]
    assert purchases == list(range(9, 16))
    kinds = {e["kind"] for e in events}
    assert {"complete_throw", "start_exercise", "upgrade_hall"} <= kinds
    assert "source_rejected" not in kinds
    first, before, _ = run(target, until_seconds=cutoff)
    _, after, _ = run(target, checkpoint_input=first / "final_checkpoint.json")
    assert before("events.json") + after("events.json") == events
    assert after("final_checkpoint.json")["behavior_state"] == expected("final_checkpoint.json")["behavior_state"]
    assert _unpack_session(after("final_checkpoint.json")["engine_state"]) == _unpack_session(expected("final_checkpoint.json")["engine_state"])


def test_source_rejection_is_recorded_and_only_same_target_retries_after_cooldown(tmp_path, monkeypatch):
    target = candidate_project(tmp_path, monkeypatch)
    request = FishSourceRuntime.request
    attempts = []

    def reject_once(self, payload, **kwargs):
        if payload["op"] == "purchase_torpedo":
            attempts.append(payload["torpedoId"])
            if len(attempts) == 1:
                raise FishSourceRejection("fixture_purchase_rejected")
        return request(self, payload, **kwargs)

    monkeypatch.setattr(FishSourceRuntime, "request", reject_once)
    _, read, _ = run(target)
    events = read("events.json")
    assert attempts == [9, *range(9, 16)]
    rejected = [e for e in events if e["kind"] == "source_rejected"]
    assert len(rejected) == 1 and "fixture_purchase_rejected" in str(rejected[0])
    first_purchase = next(e for e in events if e["kind"] == "purchase_torpedo")
    assert first_purchase["time_seconds"] >= 60
    assert any(e["kind"] in {"prepare_throw", "start_exercise", "upgrade_hall"}
               and e["time_seconds"] < first_purchase["time_seconds"] for e in events)


@pytest.mark.parametrize("owns_closed", [False, True])
def test_closed_predecessor_quote_matches_source_rejection_and_owned_history(tmp_path, owns_closed):
    target = project(tmp_path)
    path = target / "selected/tbtorpedo.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    next(r for r in rows if r["id"] == 9)["isOpen"] = False
    path.write_text(json.dumps(rows), encoding="utf-8")
    player = late_player()
    if owns_closed:
        player["torpedo"]["ownedIds"].append(9)
    with FishSourceRuntime(SOURCE, target / "selected") as host:
        host.create(start_at=0, initial_state=player, in_fishing_area=True, random_seed=42)
        quotes = host.request({"op": "query_actions"})
        assert 9 not in {q["torpedoId"] for q in quotes["torpedoes"]}
        assert next(q for q in quotes["torpedoes"] if q["torpedoId"] == 10)["previousTorpedoId"] == 9
        current = host.request({"op": "query"})
        targets = {o.target for o in growth_options(current, quotes) if o.behavior == "purchase_torpedo"}
        assert targets == ({"10"} if owns_closed else set())
        payload = {"op": "purchase_torpedo", "torpedoId": 10, "requestId": "buy-ten", "revision": current["revision"]}
        if owns_closed:
            host.request(payload)
            current = host.request({"op": "query"})
            # Same cached quote list, fresh ownership: now 11 is legal.
            quotes_after = host.request({"op": "query_actions"})
            assert quotes_after["torpedoes"] == quotes["torpedoes"]
            assert {o.target for o in growth_options(current, quotes_after) if o.behavior == "purchase_torpedo"} == {"11"}
        else:
            with pytest.raises(FishSourceRejection, match="torpedo_progression_previous_not_owned"):
                host.request(payload)
