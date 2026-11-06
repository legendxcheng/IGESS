"""Daily admission uses earned source income, not a starting wallet or future income."""
from decimal import Decimal, localcontext
import json

import pytest
import yaml

from igess.fish_source_growth_policy import GrowthTideBudget
from igess.fish_source_engine import _unpack_session
from igess.fish_source_numbers import source_decimal
from test_fish_growth_priority import dto
from test_fish_source_joint import archive, initial, project, run, configure_tide_fixture


def totals(income=0, spent=0):
    return {"material": Decimal(str(income)), "tide_reload_material": Decimal(str(spent))}


def quote(cost=300):
    return {"available": True, "materialCost": dto(cost)}


def test_daily_budget_exact_limit_actual_spending_and_new_income():
    b = GrowthTideBudget()
    b.observe_daily(0, totals(10000, 1000))  # Baseline is not today's income.
    assert b.skip_daily(quote())["dailyMaterialBudget"] == "0.00"
    assert b.skip_daily(quote(0)) is None
    b.observe_daily(600, totals(12000, 1000))
    assert b.skip_daily(quote()) is None  # 300 == 2000 * 15%.
    b.observe_daily(600, totals(12000, 1300))
    result = b.skip_daily(quote())
    assert result["reason"] == "tide_daily_income_budget_exceeded"
    assert result["dailyTideMaterialSpent"] == "300"
    b.observe_daily(1200, totals(13999, 1300))
    assert b.skip_daily(quote()) is not None
    b.observe_daily(1200, totals(14000, 1300))
    assert b.skip_daily(quote()) is None
    # Re-observation and a restored no-op retry never charge twice.
    restored = GrowthTideBudget(json.loads(json.dumps(b.save())))
    restored.observe_daily(1200, totals(14000, 1300))
    assert restored.save() == b.save()
    b.observe_daily(1300, totals(14000, 1000))  # A source refund frees budget.
    assert b.daily["spent"] == "0"


def test_wall_day_reset_and_resume_do_not_carry_budget_or_reset_on_reconnect():
    b = GrowthTideBudget()
    b.observe_daily(0, totals())
    b.observe_daily(7200, totals(10000, 900))
    b.observe_daily(8000, totals(10000, 900))  # Offline counters unchanged.
    assert b.daily["spent"] == "900"
    b.observe_daily(86399, totals(10000, 900))
    assert b.skip_daily(quote(600)) is None
    b.observe_daily(86400, totals(10000, 900))
    restored = GrowthTideBudget(b.save())
    assert restored.daily["day_index"] == 1
    assert restored.skip_daily(quote())["dailyOnlineMaterialIncome"] == "0"
    restored.observe_daily(87000, totals(12000, 900))
    assert restored.skip_daily(quote()) is None


def test_daily_fraction_preserves_large_and_fractional_exact_boundaries():
    with localcontext() as ctx:
        ctx.prec = 200
        income = Decimal('1' + '0' * 100 + '7')
        cost = income * Decimal('0.15')
        above = cost + Decimal('0.000000000000000000001')
    b = GrowthTideBudget()
    b.observe_daily(0, totals())
    b.observe_daily(600, totals(income))
    assert b.skip_daily(quote(cost)) is None
    assert b.skip_daily(quote(above)) is not None


@pytest.mark.parametrize('cutoff', [650, 86400])
def test_formal_source_income_daily_limit_and_cross_process_recovery(tmp_path, monkeypatch, cutoff):
    state = archive("""
s.wallet.material={sign=1,coeff='12',exp=2}
s.collection.unlockedKeys={'101:1'}
s.combat.ownedGunIds={10001};s.combat.equippedGunId=10001;s.combat.lastSelectedGunId=10001
""")
    initial(monkeypatch, state)
    target = project(tmp_path, duration=87001)
    configure_tide_fixture(target)
    config_path = target / 'economy.yaml'
    config = yaml.safe_load(config_path.read_text(encoding='utf-8'))
    config['session_patterns']['authoring_default']['daily_online_seconds'] = 721
    # Align the post-tide cutoff with a continuous observation so exact replay
    # history is comparable, rather than adding an extra advance only on resume.
    config['scenarios']['smoke']['record_interval_seconds'] = 50
    config_path.write_text(yaml.safe_dump(config), encoding='utf-8')
    path = target / 'selected/tbcodexfishunlockreward.json'
    rows = json.loads(path.read_text(encoding='utf-8'))
    for row in rows:
        row.update(rewardType='money', rewardAmount={'sign': 1, 'digits': '1', 'scale': 0})
        if row['fishId'] == 101 and row['mutationId'] == 1:
            row.update(rewardType='material', rewardAmount={'sign': 1, 'digits': '2000', 'scale': 0})
    path.write_text(json.dumps(rows), encoding='utf-8')
    _, full, _ = run(target)
    behavior = full('source_behavior.json')['profiles']['default']
    completed = [r for r in behavior['tide_rounds'] if r['phase'] == 'completed']
    assert [r['openedAt'] for r in completed] == [600]
    assert source_decimal(completed[0]['totalMaterialSpent']) == 300
    for at in [0, 86400, 87000]:
        skipped = next(r for r in behavior['tide_rounds'] if r['openedAt'] == at)
        assert skipped['reason'] == 'tide_daily_income_budget_exceeded'
        assert skipped['dailyOnlineMaterialIncome'] == '0'
    assert full('timeline.json')[-1]['resources']['online_tide_reload_material_cumulative'] == '300'
    first, before, _ = run(target, until_seconds=cutoff)
    if cutoff == 650:
        assert before('final_checkpoint.json')['behavior_state']['pending_tide'] is None
        assert before('final_checkpoint.json')['behavior_state']['growth_tide_budget']['daily']['spent'] == '300'
    _, after, _ = run(target, checkpoint_input=first / 'final_checkpoint.json')
    assert after('final_checkpoint.json')['behavior_state'] == full('final_checkpoint.json')['behavior_state']
    assert _unpack_session(after('final_checkpoint.json')['engine_state']) == _unpack_session(full('final_checkpoint.json')['engine_state'])
    # A post-tide cutoff adds no duplicate observation or payment.
    events = before('events.json') + after('events.json')
    assert events == full('events.json')
    assert full('run_manifest.json')['source_runtime']['tide_admission_policy']['max_daily_income_fraction'] == '0.15'
