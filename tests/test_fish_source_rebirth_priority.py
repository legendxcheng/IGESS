"""Source-eligible rebirths precede funding and preserve continuation receipts."""
import json

import pytest
import yaml

from igess.fish_source_engine import _unpack_session
from igess.fish_source_growth_policy import REBIRTH_POLICY, growth_options
from test_fish_growth_candidates import chooser
from test_fish_growth_priority import Weight, budget, decide, dto
from test_fish_source_joint import archive, initial, project, run


@pytest.mark.parametrize("turn", range(4))
def test_rebirth_precedes_funding_purchases_rewards_and_pending_collection(turn):
    runner, actions = chooser()
    runner.behavior_turn = turn
    runner.profile.behavior_weights.update(trash_man_rebirth=Weight(1), fund_trash_man_breakthrough=Weight('1e100'))
    runner.state['rebirth']['trashMan']['eligible'] = True
    runner.state['trashMan'].update(realmId=20, highestRealmId=20, currentRealm={'isMax':False,'breakthroughMaterialCost':dto(1)})
    runner.state['codex']['claimableRewards'] = [{'rewardId':1}]
    runner.pending_collect_slots = [1,2]
    runner.state['hall']['slotBalances'] = [{'slot':i,'money':dto(10)} for i in [1,2]]
    assert runner._choose() == ('trash_man_rebirth','',{'op':'rebirth_trash_man'})
    assert runner.pending_collect_slots == [1,2]
    assert runner.behavior_turn == turn
    result = decide(budget(),runner.state,growth_options(runner.state,actions),weights=runner.profile.behavior_weights,turn=turn)
    assert result['growthBehavior'] == 'trash_man_rebirth'


def test_both_rebirths_precede_other_work_in_stable_order():
    runner, _ = chooser()
    runner.profile.behavior_weights.update(trash_man_rebirth=Weight(1),strength_rebirth=Weight(1))
    runner.state['rebirth']['trashMan']['eligible'] = True
    runner.state['rebirth']['strength']['eligible'] = True
    assert runner._choose()[0] == 'trash_man_rebirth'
    runner.state['rebirth']['trashMan']['eligible'] = False
    assert runner._choose()[0] == 'strength_rebirth'


@pytest.mark.parametrize('reason',['disabled','missing','ineligible','cooldown'])
def test_rebirth_respects_profile_source_eligibility_and_rejection_recovery(reason):
    runner, _ = chooser()
    runner.state['rebirth']['trashMan']['eligible'] = reason != 'ineligible'
    if reason != 'missing':
        runner.profile.behavior_weights['trash_man_rebirth'] = Weight(0 if reason == 'disabled' else 1)
    if reason == 'cooldown':
        runner.blocked['rebirth_trash_man:'] = 60
    assert runner._choose()[0] == 'purchase_torpedo'
    if reason == 'cooldown':
        runner.state['time'] = 60
        assert runner._choose()[0] == 'trash_man_rebirth'


@pytest.mark.parametrize('cutoff',[1,5])
@pytest.mark.parametrize('realm',[3,4])
def test_source_rebirth_at_realm_four_and_resume_keeps_receipts(tmp_path,monkeypatch,cutoff,realm):
    state = archive(f'''
s.trashMan.unlocked=true
s.trashMan.realmId={realm}
s.trashMan.highestRealmId={realm}
s.wallet.material={{sign=1,coeff='1',exp=12}}
''')
    initial(monkeypatch,state)
    target = project(tmp_path,duration=25,weights={'trash_man_rebirth':'1','fund_trash_man_breakthrough':'1e100'})
    config_path = target / 'economy.yaml'
    config = yaml.safe_load(config_path.read_text(encoding='utf-8'))
    config['scenarios']['smoke']['record_interval_seconds'] = 1
    config_path.write_text(yaml.safe_dump(config),encoding='utf-8')
    _, expected, _ = run(target)
    events = expected('events.json')
    growth = [e for e in events if e['kind'] in {'rebirth_trash_man','start_breakthrough'}]
    rebirth_index = 1 if realm == 3 else 0
    assert growth[rebirth_index]['kind'] == 'rebirth_trash_man'
    receipt = json.loads(growth[rebirth_index]['details']['receipt'])
    assert receipt['realmBefore'] == receipt['requirement'] == 4
    assert growth[rebirth_index]['time_seconds'] == (10 if realm == 3 else 0)
    assert not any(e['kind']=='source_rejected' for e in events)
    assert expected('run_manifest.json')['source_runtime']['rebirth_policy'] == REBIRTH_POLICY
    first,before,_ = run(target,until_seconds=cutoff)
    _,after,_ = run(target,checkpoint_input=first/'final_checkpoint.json')
    assert before('events.json')+after('events.json') == events
    assert after('final_checkpoint.json')['behavior_state'] == expected('final_checkpoint.json')['behavior_state']
    assert _unpack_session(after('final_checkpoint.json')['engine_state']) == _unpack_session(expected('final_checkpoint.json')['engine_state'])
