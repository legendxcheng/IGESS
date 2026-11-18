"""Concentrated upgrades spend source-quoted money in a three-second batch."""
import json

import pytest
import yaml

from igess.fish_source_engine import _unpack_session
from igess.fish_source_growth_policy import fish_upgrade_quote, reserve_money_for_barbell
from igess.fish_source_numbers import source_decimal
from igess.fish_source_runtime import FishSourceRejection, FishSourceRuntime
from test_fish_growth_priority import Weight, dto
from test_fish_source_joint import SOURCE, archive, initial, project, run


def reservation(price, *, money=100, unclaimed=50, cps=2, enabled=True, allowed=True):
    state = {"wallet": {"money": dto(money)}, "unclaimedMoney": dto(unclaimed),
             "hall": {"currentRatePerSecond": dto(cps)}, "barbell": {"owned": [{"barbellId": 1}]}}
    actions = {"barbells": [{"barbellId": 10, "cost": dto(1)},
                            {"barbellId": 2, "cost": dto(price)}]}
    return reserve_money_for_barbell(state, actions, {"synthesize_barbell": Weight(int(enabled))}, lambda *_: allowed)


@pytest.mark.parametrize("price,expected", [(3749, True), (3750, True), (3751, False)])
def test_barbell_threshold_includes_wallet_and_unclaimed_and_uses_numeric_next(price, expected):
    assert reservation(price) is expected


def test_barbell_zero_cps_disabled_blocked_and_exact_large_boundary():
    assert reservation(150, cps=0)
    assert not reservation(151, cps=0)
    assert not reservation(100, enabled=False)
    assert not reservation(100, allowed=False)
    money = 10**110 + 7
    assert reservation(money + 1800, money=money, unclaimed=0, cps=1)
    assert not reservation(money + 1801, money=money, unclaimed=0, cps=1)
    assert not reserve_money_for_barbell(
        {"barbell": {"owned": []}}, {"barbells": []}, {"synthesize_barbell": Weight(1)}, lambda *_: True,
    )


def test_only_top_two_ordinary_selected_deployed_fish_can_receive_money():
    state = {"wallet": {"money": dto(10)}, "inventory": {"items": [
        {"instanceId": key, "hallSlot": key} for key in (1, 2, 3, 4)]}}
    actions = {"bestPotentialLayout": {"selectedInstanceIds": [4, 3, 2, 1]},
               "hallCandidates": [{"instanceId": key, "isBeast": key == 4} for key in (1, 2, 3, 4)],
               "fishUpgrades": [{"instanceId": key, "cost": dto(cost)} for key, cost in [(1, 1), (2, 5), (3, 10)]]}
    allowed = lambda *_: True
    assert fish_upgrade_quote(state, actions, allowed)["instanceId"] == 3
    state["wallet"]["money"] = dto(9)
    assert fish_upgrade_quote(state, actions, allowed)["instanceId"] == 2
    state["wallet"]["money"] = dto(4)
    assert fish_upgrade_quote(state, actions, allowed) is None
    state["wallet"]["money"] = dto(100)
    actions["fishUpgrades"] = actions["fishUpgrades"][:1]  # Both main fish at max level.
    assert fish_upgrade_quote(state, actions, allowed) is None
    actions["fishUpgrades"].append({"instanceId": 3, "cost": dto(10)})
    state["inventory"]["items"][2]["hallSlot"] = 0  # Selected but pending a rejected layout.
    assert fish_upgrade_quote(state, actions, allowed) is None
    state["inventory"]["items"][2]["hallSlot"] = 3
    assert fish_upgrade_quote(state, actions, lambda *_: False) is None


def upgrade_project(tmp_path, monkeypatch, *, duration=12, barbell_price=None, boundary=1000, online=7200, weak_level=1):
    state = archive('''
s.wallet.money={sign=1,coeff='1',exp=2}
s.fish.items={
 {instanceId=1,fishId=101,mutationId=1,weightGram=1000,level=1,hallSlot=3},
 {instanceId=2,fishId=102,mutationId=1,weightGram=1000,level=1,hallSlot=2},
 {instanceId=3,fishId=201,mutationId=1,weightGram=1000,level=1,hallSlot=1}}
s.fish.nextInstanceId=4
''')
    state["fish"]["items"][0]["level"] = weak_level
    initial(monkeypatch, state)
    weights = {"upgrade_fish": "1"}
    if barbell_price is not None:
        weights["synthesize_barbell"] = "100"
    target = project(tmp_path, duration=duration, weights=weights)
    path = target / "economy.yaml"
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    config["engine"]["source_runtime"].update(idle_seconds=1, room_origin_seconds=boundary)
    config["scenarios"]["smoke"]["record_interval_seconds"] = 1
    profile = config["player_profiles"]["default"]
    config["session_patterns"][profile["session_pattern"]]["daily_online_seconds"] = online
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    if barbell_price is not None:
        path = target / "selected/tbbarbell.json"
        rows = json.loads(path.read_text(encoding="utf-8"))
        for row in rows:
            if row["id"] != 1:
                row["price"] = {"sign": 1, "digits": str(barbell_price), "scale": 0}
        path.write_text(json.dumps(rows), encoding="utf-8")
    return target


def upgrades(read):
    return [e for e in read("events.json") if e["kind"] == "upgrade_fish"]


def test_batch_spends_all_affordable_money_through_source_and_takes_three_seconds(tmp_path, monkeypatch):
    target = upgrade_project(tmp_path, monkeypatch, duration=3)
    _, read, _ = run(target)
    events = upgrades(read)
    assert len(events) > 2 and {e["time_seconds"] for e in events} == {0}
    assert [e["item_id"] for e in events[:2]] == ["3", "3"]
    assert {e["item_id"] for e in events} == {"2", "3"}
    checkpoint = read("final_checkpoint.json")
    assert checkpoint["behavior_state"]["pending_action"] is None
    session = _unpack_session(checkpoint["engine_state"])
    with FishSourceRuntime(SOURCE, target / "selected") as host:
        final = host.restore(session)
        quotes = host.request({"op": "query_actions"})
        assert fish_upgrade_quote(final, quotes, lambda *_: True) is None
        assert next(f for f in final["inventory"]["items"] if f["instanceId"] == 1)["level"] == 1
        assert source_decimal(final["wallet"]["money"]) < 100
    assert read("run_manifest.json")["source_runtime"]["fish_upgrade_policy"]["batch_seconds"] == 3


def test_high_level_low_potential_fish_with_highest_current_cps_is_never_upgraded(tmp_path, monkeypatch):
    target = upgrade_project(tmp_path, monkeypatch, duration=3, weak_level=80)
    # Verify the counterexample with source quotes, not a Python copy of growth.
    with FishSourceRuntime(SOURCE, target / "selected") as host:
        host.create(start_at=0)
        actions = host.request({"op": "query_actions"})
        current = {row["instanceId"]: source_decimal(row["currentRate"]) for row in actions["hallCandidates"]}
        assert current[1] > current[3] > current[2]
        assert actions["bestPotentialLayout"]["selectedInstanceIds"][:2] == [3, 2]
    _, read, _ = run(target)
    assert upgrades(read) and {e["item_id"] for e in upgrades(read)} == {"2", "3"}
    with FishSourceRuntime(SOURCE, target / "selected") as host:
        final = host.restore(_unpack_session(read("final_checkpoint.json")["engine_state"]))
        assert next(f for f in final["inventory"]["items"] if f["instanceId"] == 1)["level"] == 80


@pytest.mark.parametrize("cutoff", [1, 2, 3])
def test_batch_cutoff_replays_source_spending_once_and_only_resumes_remaining_time(tmp_path, monkeypatch, cutoff):
    target = upgrade_project(tmp_path, monkeypatch)
    _, expected, _ = run(target)
    first, before, _ = run(target, until_seconds=cutoff)
    _, after, _ = run(target, checkpoint_input=first / "final_checkpoint.json")
    if cutoff < 3:
        assert before("final_checkpoint.json")["behavior_state"]["pending_action"]["end_at"] == 3
    assert before("events.json") + after("events.json") == expected("events.json")
    assert after("final_checkpoint.json")["behavior_state"] == expected("final_checkpoint.json")["behavior_state"]
    assert _unpack_session(after("final_checkpoint.json")["engine_state"]) == _unpack_session(expected("final_checkpoint.json")["engine_state"])
    assert after("timeline.json")[-1] == expected("timeline.json")[-1]


def test_near_barbell_blocks_batch_but_far_barbell_does_not_interrupt_it(tmp_path, monkeypatch):
    target = upgrade_project(tmp_path, monkeypatch, duration=3, barbell_price=75000)
    # Initial hall CPS is 2+3+35=40, so 75,000 is initially over 30 minutes.
    # Upgrading the strongest fish moves it inside 30 minutes; finish this batch.
    _, read, _ = run(target)
    assert len(upgrades(read)) > 2
    path = target / "selected/tbbarbell.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    for row in rows:
        if row["id"] != 1:
            row["price"] = {"sign": 1, "digits": "72000", "scale": 0}
    path.write_text(json.dumps(rows), encoding="utf-8")
    _, read, _ = run(target)
    assert upgrades(read) == []


def test_rejection_ends_batch_and_next_legal_fish_can_upgrade(tmp_path, monkeypatch):
    target = upgrade_project(tmp_path, monkeypatch)
    request = FishSourceRuntime.request
    def reject(self, payload, **kwargs):
        if payload["op"] == "upgrade_fish" and payload["instanceId"] == 3:
            raise FishSourceRejection("fixture_upgrade_rejected")
        return request(self, payload, **kwargs)
    monkeypatch.setattr(FishSourceRuntime, "request", reject)
    _, read, _ = run(target)
    assert len([e for e in read("events.json") if e["kind"] == "source_rejected"]) == 1
    assert upgrades(read) and {e["item_id"] for e in upgrades(read)} == {"2"}


@pytest.mark.parametrize("kind", ["tide", "logout"])
def test_batch_does_not_start_without_three_seconds_before_boundary(tmp_path, monkeypatch, kind):
    target = upgrade_project(tmp_path, monkeypatch, duration=2,
                             boundary=2 if kind == "tide" else 1000,
                             online=2 if kind == "logout" else 7200)
    _, read, _ = run(target)
    assert upgrades(read) == []
