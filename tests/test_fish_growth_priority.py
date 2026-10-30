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


def budget(gained=600, codex=0):
    result = GrowthTideBudget()
    result.observe(0, {"material": Decimal(0), "codex_material": Decimal(0)})
    result.observe(600, {"material": Decimal(gained), "codex_material": Decimal(codex)})
    return result


def decide(b, s, options, *, remaining=7200, allowed=lambda *_: True, weights=None, turn=0):
    return b.skip(s, options, weights or {o.behavior: Weight(1) for o in options}, allowed, turn, remaining)


@pytest.mark.parametrize("cost,reason", [(500, "growth_action_ready"), (2300, "growth_material_reserved"), (2301, None)])
def test_ready_and_exact_thirty_minute_boundary(cost, reason):
    result = decide(budget(), state(), [option(cost)])
    assert (result or {}).get("reason") == reason


def test_one_time_rewards_no_income_and_remaining_session_do_not_lock_remote_goals():
    assert decide(budget(600, 600), state(), [option(600)]) is None
    assert decide(GrowthTideBudget(), state(), [option(600)]) is None
    assert decide(budget(), state(), [option(1101)], remaining=600) is None
    assert decide(budget(), state(), [option(1100)], remaining=600)["reason"] == "growth_material_reserved"


def test_disabled_and_rejected_growth_does_not_reserve_or_block_tides():
    assert decide(budget(), state(), [option(500)], allowed=lambda *_: False) is None
    assert decide(budget(), state(), [option(500)], weights={"upgrade_fish_hall": Weight(0)}) is None


def test_existing_weights_and_turn_select_one_target_without_summing_lines():
    options = [option(900), option(1000, "purchase_torpedo", "2"), option(1100, "purchase_torpedo", "3")]
    weights = {"upgrade_fish_hall": Weight(1), "purchase_torpedo": Weight(100)}
    result = decide(budget(), state(), options, weights=weights)
    assert result["growthTarget"] == "2" and result["reservedMaterial"] == "1000"
    # A remote next target cannot cause reservation for a later, cheaper target.
    assert decide(budget(), state(), [option(10000, "purchase_torpedo", "2"), option(700, "purchase_torpedo", "3")]) is None


def test_large_exact_dto_boundary_and_restored_income_window():
    wallet = "1" + "0" * 100
    cost = str(int(wallet) + 1800)
    b = budget()
    expected = decide(b, state(wallet), [option(cost)])
    assert expected["reason"] == "growth_material_reserved"
    assert decide(b, state(wallet), [option(str(int(cost) + 1))]) is None
    restored = GrowthTideBudget(b.save())
    assert decide(restored, state(wallet), [option(cost)]) == expected
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
s.wallet.material={sign=1,coeff='42',exp=1}
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
    assert len([e for e in events if e["kind"] == "upgrade_hall"]) == 2
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
    assert expected("run_manifest.json")["source_runtime"]["tide_admission_policy"]["horizon_online_seconds"] == 1800
