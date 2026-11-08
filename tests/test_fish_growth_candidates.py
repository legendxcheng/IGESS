"""Candidate selection must not let later purchases starve legal progression."""
from types import SimpleNamespace

import pytest

from igess.engines import EngineAdapterError
from igess.fish_source_engine import _ProfileRun
from igess.fish_source_growth_policy import growth_options, target_order
from test_fish_growth_priority import Weight, budget, decide, dto, state, option


def chooser(ids=range(1, 16), owned=range(1, 9)):
    runner = object.__new__(_ProfileRun)
    runner.state = state(wallet=1000, reload=25)
    runner.state.update({
        "time": 0, "codex": {"claimableRewards": []},
        "inventory": {"items": [], "total": 0, "capacity": 200},
        "hall": {"slotBalances": [], "currentLevel": {"capacity": 5}},
        "rebirth": {"strength": {"eligible": False}, "trashMan": {"eligible": False}},
        "trashMan": {"unlocked": True, "realmId": 1, "highestRealmId": 1,
                     "breakthrough": {"active": False}, "currentRealm": {"isMax": True}},
        "torpedo": {"ownedIds": list(owned)}, "barbell": {"owned": []},
    })
    runner.state["guns"]["rewards"] = []
    runner.state["guns"]["owned"][0]["attack"] = dto(1)
    ids = list(ids)
    quotes = [{"torpedoId": i, "previousTorpedoId": ids[n - 1] if n else 0,
               "resource": "material", "cost": dto(100)} for n, i in enumerate(ids)]
    actions = {"torpedoes": quotes, "barbells": [], "fishUpgrades": [],
               "bestPotentialLayout": {"changed": False, "selectedInstanceIds": []}}
    runner.runtime = SimpleNamespace(request=lambda _: actions)
    runner.inputs = SimpleNamespace(collect_interval_seconds=300, fishing_area=True)
    runner.profile = SimpleNamespace(behavior_weights={
        "purchase_torpedo": Weight("1e100"), "manual_throw": Weight(1), "exercise_barbell": Weight(1),
    })
    runner.pending_collect_slots = []
    runner.last_collect = 0
    runner.blocked = {}
    runner.behavior_turn = 0
    return runner, actions


def test_real_chooser_buys_nine_before_ten():
    runner, _ = chooser()
    assert runner._choose() == ("purchase_torpedo", "9", {"op": "purchase_torpedo", "torpedoId": 9})


def test_tide_ready_target_matches_legal_purchase():
    runner, actions = chooser()
    result = decide(budget(), runner.state, growth_options(runner.state, actions))
    assert result["growthTarget"] == "9"


def test_cooling_down_predecessor_does_not_enable_later_purchase_or_block_tide():
    runner, actions = chooser()
    runner.blocked["purchase_torpedo:9"] = 60
    assert runner._choose()[0] == "manual_throw"
    assert decide(budget(), runner.state, growth_options(runner.state, actions), allowed=runner._allowed) is None
    runner.state["time"] = 60
    assert runner._choose()[1] == "9"


def test_remote_legal_predecessor_does_not_override_wallet_budget():
    runner, actions = chooser()
    next(q for q in actions["torpedoes"] if q["torpedoId"] == 9)["cost"] = dto(1500)
    result = decide(budget(), runner.state, growth_options(runner.state, actions))
    assert result is None
    assert runner._choose()[0] == "manual_throw"


def test_noncontiguous_catalog_and_historical_ownership_follow_source_predecessor():
    runner, actions = chooser(ids=[1, 9, 20, 100], owned=[1, 20])
    # Both 9 and 100 are legal: no requirement to fill every historical gap.
    assert {o.target for o in growth_options(runner.state, actions)} == {"9", "100"}
    assert runner._choose()[1] == "9"
    # A closed, unowned predecessor is absent from shop quotes, but still required.
    actions["torpedoes"] = [q for q in actions["torpedoes"] if q["torpedoId"] != 9]
    runner.state["torpedo"]["ownedIds"] = [1]
    assert not growth_options(runner.state, actions)


def test_barbells_use_numeric_order_without_changing_other_target_protocols():
    runner, actions = chooser(ids=[], owned=[])
    runner.state["wallet"]["money"] = dto(1000)
    actions["barbells"] = [{"barbellId": i, "resource": "money", "cost": dto(100)} for i in [10, 9]]
    runner.profile.behavior_weights["synthesize_barbell"] = Weight(100)
    assert runner._choose() == ("synthesize_barbell", "9", {"op": "synthesize_barbell", "barbellId": 9})
    result = decide(budget(), runner.state, growth_options(runner.state, actions))
    assert result["growthTarget"] == "9"


def test_target_order_is_numeric_for_catalogs_only():
    assert target_order("purchase_torpedo", "9") < target_order("purchase_torpedo", "10")
    assert target_order("upgrade_fish", "fish:opaque") == (1, "fish:opaque")
    assert target_order("upgrade_fish", "10") < target_order("upgrade_fish", "9")


def test_missing_source_prerequisite_is_explicit_not_guessed():
    runner, actions = chooser()
    del actions["torpedoes"][0]["previousTorpedoId"]
    with pytest.raises(EngineAdapterError, match="previousTorpedoId"):
        growth_options(runner.state, actions)
