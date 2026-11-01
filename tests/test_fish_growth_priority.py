"""Growth-first admission preserves source spending and resumable decisions."""
from decimal import Decimal
import json

import pytest
import yaml

from igess.fish_source_growth_policy import GrowthOption, GrowthTideBudget, growth_options
from igess.fish_source_engine import _unpack_session
from test_fish_source_joint import archive, initial, project, run


def dto(value):
    value = Decimal(str(value))
    return {"sign": 0 if value == 0 else 1, "coeff": ''.join(map(str, value.as_tuple().digits)), "exp": value.as_tuple().exponent}


class Weight:
    def __init__(self, value): self.value = value
    def to_decimal_string(self): return str(self.value)


def option(cost, behavior="upgrade_fish_hall", target=""):
    return GrowthOption(behavior, target, {"op": "upgrade_hall"}, {"resource": "material", "cost": dto(cost)})


def state(wallet=500, reload=50):
    return {"wallet": {"material": dto(wallet)}, "guns": {"owned": [{"id": 1, "reloadResourceCost": dto(reload)}],
            "combat": {"equippedGunId": 1}}, "tides": {"policy": {"reloads": 6}}}


def budget():
    return GrowthTideBudget()


def decide(b, s, options, *, remaining=7200, allowed=lambda *_: True, weights=None, turn=0):
    return b.skip(s, options, weights or {o.behavior: Weight(1) for o in options}, allowed, turn, remaining)


@pytest.mark.parametrize("wallet,blocked", [(1199, True), (1200, False), (1201, False), (0, True)])
def test_entire_tide_cost_at_quarter_wallet_boundary(wallet, blocked):
    result = decide(budget(), state(wallet), [])
    assert bool(result) == blocked
    if blocked:
        assert result["reason"] == "tide_material_budget_exceeded"
        assert result["tideMaterialCost"] == "300"


def test_ready_growth_still_precedes_tide_and_disabled_growth_does_not():
    assert decide(budget(), state(1200), [option(500)])["reason"] == "growth_action_ready"
    assert decide(budget(), state(1200), [option(500)], allowed=lambda *_: False) is None
    assert decide(budget(), state(1200), [option(500)], weights={"upgrade_fish_hall": Weight(0)}) is None


def test_remote_goals_and_income_history_do_not_change_wallet_limit():
    assert decide(budget(), state(1200), [option(10000000)]) is None
    assert decide(budget(), state(1199), [option(10000000)])["reason"] == "tide_material_budget_exceeded"


def test_budget_recomputed_after_spending_and_gun_change():
    b = budget()
    assert decide(b, state(1200), []) is None
    assert decide(b, state(900), [])["reason"] == "tide_material_budget_exceeded"
    assert decide(b, state(1200, reload=51), [])["reason"] == "tide_material_budget_exceeded"
    assert decide(b, state(1224, reload=51), []) is None


def test_free_tide_and_exact_large_fractional_boundary():
    assert decide(budget(), state(0, reload=0), []) is None
    # Beyond Decimal's default precision: equality is allowed, one unit below is not.
    reload = int("1" + "0" * 100) + 1
    threshold = reload * 24
    assert decide(budget(), state(str(threshold), reload=str(reload)), []) is None
    assert decide(budget(), state(str(threshold - 1), reload=str(reload)), []) is not None
    assert decide(budget(), state("2.4", reload="0.1"), []) is None
    assert decide(budget(), state("2.39999999999999999999999999999999999999", reload="0.1"), []) is not None


def observed_budget(gained=600, codex=0):
    b = budget()
    b.observe(0, {"material": Decimal(0), "codex_material": Decimal(0)})
    b.observe(600, {"material": Decimal(gained), "codex_material": Decimal(codex)})
    return b


def test_both_guards_apply_independently():
    # Cheap tide fits 25%, but the nearby growth target still needs its funds.
    b = observed_budget()
    assert decide(b, state(1200), [option(3000)])["reason"] == "growth_material_reserved"
    assert decide(b, state(1200), [option(3001)]) is None
    # A remote goal or absent observations must never bypass the wallet limit.
    assert decide(b, state(1199), [option(100000)])["reason"] == "tide_material_budget_exceeded"
    assert decide(budget(), state(1199), [])["reason"] == "tide_material_budget_exceeded"


def test_reserve_excludes_codex_and_respects_remaining_online_time():
    assert decide(observed_budget(600, 600), state(1200), [option(1500)]) is None
    assert decide(observed_budget(), state(1200), [option(1800)], remaining=600)["reason"] == "growth_material_reserved"
    assert decide(observed_budget(), state(1200), [option(1801)], remaining=600) is None


def test_reserve_uses_legal_next_target_and_preserves_window_on_resume():
    b = observed_budget()
    assert decide(b, state(1200), [option(10000, "purchase_torpedo", "9"), option(1500, "purchase_torpedo", "10")]) is None
    options = [option(2000, "purchase_torpedo", "2"), option(1800)]
    weights = {"purchase_torpedo": Weight(100), "upgrade_fish_hall": Weight(1)}
    result = decide(b, state(1200), options, weights=weights)
    assert result["growthTarget"] == "2"
    restored = GrowthTideBudget(b.save())
    assert decide(restored, state(1200), options, weights=weights) == result
    for t in (1200, 1800, 2400, 3000):
        totals = {"material": Decimal(t), "codex_material": Decimal(0)}
        b.observe(t, totals); restored.observe(t, totals)
    assert b.save() == restored.save() and b.samples[0][0] == 1200


@pytest.mark.parametrize("locked", ["locked", "recovering", "training", "max"])
def test_breakthrough_requires_source_prerequisites(locked):
    s = {"rebirth": {"strength": {"eligible": False}, "trashMan": {"eligible": False}},
         "trashMan": {"unlocked": locked != "locked", "realmId": 1, "highestRealmId": 2 if locked == "recovering" else 1,
                      "breakthrough": {"active": locked == "training"}, "currentRealm": {"isMax": locked == "max", "breakthroughMaterialCost": dto(100)}},
         "torpedo": {"ownedIds": []}, "barbell": {"owned": []}}
    assert not growth_options(s, {"torpedoes": [], "barbells": []})


def growth_project(tmp_path, monkeypatch):
    s = archive("""
s.wallet.material={sign=1,coeff='232',exp=1}
s.combat.ownedGunIds={10001};s.combat.equippedGunId=10001;s.combat.lastSelectedGunId=10001
""")
    initial(monkeypatch, s)
    target = project(tmp_path, duration=721, weights={"upgrade_fish_hall": "100"})
    path = target / "economy.yaml"
    config = yaml.safe_load(path.read_text())
    config["scenarios"]["smoke"]["record_interval_seconds"] = 1
    path.write_text(yaml.safe_dump(config))
    return target


@pytest.mark.parametrize("cutoff", [1, 600, 650])
def test_formal_growth_then_tide_and_resume_preserve_source_receipts(tmp_path, monkeypatch, cutoff):
    target = growth_project(tmp_path, monkeypatch)
    _, expected, _ = run(target)
    events = expected("events.json")
    assert len([e for e in events if e["kind"] == "upgrade_hall"]) == 3
    starts = [e for e in events if e["kind"] == "start_tide"]
    assert [e["time_seconds"] for e in starts] == [600]
    skipped = [json.loads(e["details"]["receipt"]) for e in events if e["kind"] == "tide_observed" and e["time_seconds"] == 0]
    assert skipped[0]["reason"] == "growth_action_ready"
    assert not any(e["kind"] == "source_rejected" for e in events)
    assert expected("timeline.json")[-1]["resources"]["online_tide_reload_material_cumulative"] == "300"
    first, before, _ = run(target, until_seconds=cutoff)
    _, after, _ = run(target, checkpoint_input=first / "final_checkpoint.json")
    combined = before("events.json") + after("events.json")
    if cutoff == 650:
        # Ending a segment emits one final in-progress tide observation. The
        # continuous run has no transition at this second; keep every other row.
        extra = [e for e in combined if e["kind"] == "tide_observed" and e["time_seconds"] == cutoff]
        assert len(extra) == 1
        receipt = json.loads(extra[0]["details"]["receipt"])
        assert receipt["phase"] == "participating" and receipt["occupied_seconds"] == 50
        combined = [e for e in combined if e is not extra[0]]
    assert combined == events
    assert after("final_checkpoint.json")["behavior_state"] == expected("final_checkpoint.json")["behavior_state"]
    assert _unpack_session(after("final_checkpoint.json")["engine_state"]) == _unpack_session(expected("final_checkpoint.json")["engine_state"])
    assert expected("run_manifest.json")["source_runtime"]["tide_admission_policy"]["max_material_fraction"] == "0.25"
