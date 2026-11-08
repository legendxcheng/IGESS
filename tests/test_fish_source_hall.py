"""The simulated player uses the production one-click potential command."""
import json

import pytest

from igess.fish_source_engine import _unpack_session
from igess.fish_source_runtime import FishSourceRejection, FishSourceRuntime
from test_fish_source_joint import SOURCE, archive, initial, project, run
from test_fish_source_sales import sales, sales_project


def test_source_plan_is_read_only_exact_stable_and_command_replays():
    state = archive("""
for i=1,7 do
    s.fish.items[i]={instanceId=i,fishId=102,mutationId=1,weightGram=1000,level=1,hallSlot=i<=5 and i or 0}
end
s.fish.items[1].fishId=101
s.fish.items[1].level=100
s.fish.items[6].fishId=101
s.fish.items[6].mutationId=3
s.fish.items[7].fishId=1301
s.fish.nextInstanceId=8
""")
    with FishSourceRuntime(SOURCE, SOURCE / 'igess_export/json') as host:
        host.create(start_at=0, initial_state=state, random_seed=42)
        before = host.request({'op': 'query'})
        history = host.checkpoint()['history']
        plan = host.request({'op': 'query_actions'})['bestPotentialLayout']
        assert plan['selectedInstanceIds'] == [7, 6, 2, 3, 4]
        assert host.request({'op': 'query'}) == before
        assert host.checkpoint()['history'] == history
        plan['selectedInstanceIds'].clear()
        assert host.request({'op': 'query_actions'})['bestPotentialLayout']['selectedCount'] == 5
        request = {'op': 'apply_best_potential_layout', 'requestId': 'potential-1'}
        receipt = host.request(request)
        after = host.request({'op': 'query'})
        assert after['wallet'] == before['wallet']
        assert not host.request({'op': 'query_actions'})['bestPotentialLayout']['changed']
        assert host.request(request) == receipt
        assert host.request({'op': 'query'}) == after
        checkpoint = host.checkpoint()
    with FishSourceRuntime(SOURCE, SOURCE / 'igess_export/json') as host:
        assert host.restore(checkpoint) == after
        assert host.request(request) == receipt
        assert host.request({'op': 'query'}) == after


@pytest.mark.parametrize('cutoff', [1, 2, 4])
def test_replacement_precedes_sale_and_resumes_without_repeating(tmp_path, monkeypatch, cutoff):
    target = sales_project(tmp_path, monkeypatch, count=31, body='''
s.fish.items[1].fishId=101
s.fish.items[1].level=100
s.fish.items[31].fishId=1301
''')
    _, full, _ = run(target)
    first, before, _ = run(target, until_seconds=cutoff)
    _, after, _ = run(target, checkpoint_input=first / 'final_checkpoint.json')
    events = full('events.json')
    layout = [e for e in events if e['kind'] == 'apply_best_potential_layout']
    assert len(layout) == 1
    assert [s['instanceId'] for s in sales(events)] == [1]
    assert next(e for e in events if e['kind'] in {'apply_best_potential_layout', 'sell_fish'}) == layout[0]
    assert before('events.json') + after('events.json') == events
    assert after('final_checkpoint.json')['behavior_state'] == full('final_checkpoint.json')['behavior_state']
    assert _unpack_session(after('final_checkpoint.json')['engine_state']) == _unpack_session(full('final_checkpoint.json')['engine_state'])


def test_rejected_layout_protects_selected_backpack_candidate(tmp_path, monkeypatch):
    target = sales_project(tmp_path, monkeypatch, count=31, body='''
s.fish.items[31].fishId=1301
''')
    request = FishSourceRuntime.request
    def reject(self, payload, **kwargs):
        if payload['op'] == 'apply_best_potential_layout':
            raise FishSourceRejection('fixture_layout_rejected')
        return request(self, payload, **kwargs)
    monkeypatch.setattr(FishSourceRuntime, 'request', reject)
    _, read, _ = run(target)
    assert [s['instanceId'] for s in sales(read('events.json'))] == [6]
    assert len([e for e in read('events.json') if e['kind'] == 'source_rejected']) == 1


def test_upgrade_targets_selected_deployed_fish_only(tmp_path, monkeypatch):
    state = archive('''
s.wallet.money={sign=1,coeff='1',exp=6}
for i=1,6 do
    s.fish.items[i]={instanceId=i,fishId=i==1 and 101 or 102,mutationId=1,weightGram=1000,level=1,hallSlot=i<=5 and i or 0}
end
s.fish.nextInstanceId=7
''')
    initial(monkeypatch, state)
    target = project(tmp_path, duration=20, weights={'upgrade_fish': '1'})
    _, read, _ = run(target)
    assert read('run_manifest.json')['source_profiles']['default']['initial_loadout']['hallPolicy'] == 'source_best_potential_layout_v1'
    upgrades = [json.loads(e['details']['receipt']) for e in read('events.json') if e['kind'] == 'upgrade_fish']
    assert upgrades and all(r['instanceId'] != 1 for r in upgrades)


def test_whale_uses_same_beast_first_source_plan():
    with FishSourceRuntime(SOURCE, SOURCE / 'igess_export/json') as host:
        host.create(start_at=0, initial_loadout_mode='whale_qinglong_29')
        plan = host.request({'op': 'query_actions'})['bestPotentialLayout']
        assert plan['selectedInstanceIds'] == [1, 2, 3, 4, 5]
        host.request({'op': 'apply_best_potential_layout', 'requestId': 'beasts'})
        state = host.request({'op': 'query'})
        assert len([f for f in state['inventory']['items'] if f['hallSlot']]) == 5
        assert not host.request({'op': 'query_actions'})['bestPotentialLayout']['changed']
