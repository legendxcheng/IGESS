"""Purchased inventory, source-derived rates/stats, and cross-process replay."""
import json
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from igess.authoring.service import AuthoringService
from igess.fish_source_engine import _unpack_session
from igess.fish_source_loadout import choose_loadout_hall_action
from igess.fish_source_numbers import source_decimal
from igess.fish_source_runtime import FishSourceRuntime, FishSourceRuntimeError
from test_fish_source_formal import FISH_SOURCE, _project


def test_whale_start_has_real_inventory_and_no_fabricated_reference_attack():
    with FishSourceRuntime(FISH_SOURCE, FISH_SOURCE / 'igess_export/json') as runtime:
        state = runtime.create(start_at=0, initial_loadout_mode='whale_qinglong_29',
                               permanent_privilege_mode='all_on_sale')
        loadout = runtime.request({'op': 'query_initial_loadout'})
        assert loadout['gunId'] == 10103 and loadout['fishCount'] == 29
        assert len(state['inventory']['items']) == 29
        assert all(f['fishId'] == 2004 and f['hallSlot'] == 0 for f in state['inventory']['items'])
        assert state['guns']['combat']['ownedGunIds'] == [10103]
        assert source_decimal(state['guns']['owned'][0]['attack']) == 0
        assert state['wallet']['money']['sign'] == state['wallet']['material']['sign'] == 0
        checkpoint = runtime.checkpoint()
        assert checkpoint['history'] == []
        assert runtime.request({'op': 'query_initial_loadout'}) == loadout
        assert runtime.checkpoint() == checkpoint
    with FishSourceRuntime(FISH_SOURCE, FISH_SOURCE / 'igess_export/json') as runtime:
        assert runtime.restore(checkpoint) == state
        assert runtime.request({'op': 'query_initial_loadout'}) == loadout
        runtime.request({'op': 'go_offline'})
        assert runtime.request({'op': 'query_initial_loadout'}) == loadout


def test_unknown_loadout_rejected():
    with FishSourceRuntime(FISH_SOURCE, FISH_SOURCE / 'igess_export/json') as runtime:
        with pytest.raises(FishSourceRuntimeError, match='simulation_loadout_mode_invalid'):
            runtime.create(start_at=0, initial_loadout_mode='free_money')


def test_hall_policy_reserves_reference_and_replaces_it_before_selling():
    def dto(n): return {'sign': 1, 'coeff': str(n), 'exp': 0}
    state = {'inventory': {'items': [
        {'instanceId': 1, 'hallSlot': 0}, {'instanceId': 30, 'hallSlot': 1},
        {'instanceId': 31, 'hallSlot': 0},
    ]}, 'hall': {'currentLevel': {'capacity': 5}}}
    actions = {'hallCandidates': [
        {'instanceId': 1, 'isBeast': True, 'currentRate': dto(0)},
        {'instanceId': 30, 'isBeast': False, 'currentRate': dto(10)},
        {'instanceId': 31, 'isBeast': False, 'currentRate': dto(20)},
    ]}
    allowed = lambda *_: True
    assert choose_loadout_hall_action(state, actions, allowed)[2] == {'op': 'withdraw_fish', 'instanceId': 30}
    state['inventory']['items'][1]['hallSlot'] = 0
    assert choose_loadout_hall_action(state, actions, allowed)[2] == {'op': 'deploy_fish', 'instanceId': 31, 'slot': 1}
    state['inventory']['items'][2]['hallSlot'] = 1
    assert choose_loadout_hall_action(state, actions, allowed)[2] == {'op': 'deploy_fish', 'instanceId': 1, 'slot': 2}


def test_whale_formal_source_stats_and_continuation(tmp_path, monkeypatch):
    from igess.fish_source_growth_policy import GrowthTideBudget
    original_skip = GrowthTideBudget.skip
    def without_near_term_reserve(self, *args, **kwargs):
        reason = original_skip(self, *args, **kwargs)
        return None if reason and reason.get('reason') == 'growth_material_reserved' else reason
    # Isolate ammunition/restore from growth reservation; other admission and
    # real source wallet debits remain active. Production runs do not patch it.
    monkeypatch.setattr(GrowthTideBudget, 'skip', without_near_term_reserve)
    project = _project(tmp_path)
    config_path = project / 'economy.yaml'
    cfg = yaml.safe_load(config_path.read_text(encoding='utf-8'))
    cfg['engine']['source_runtime']['advance_mode'] = 'equivalent_batch_v1'
    cfg['scenarios']['smoke_whale']['duration_hours'] = '0.3333333333333333'
    # Fixture only: make the first normal codex gun reachable with one common
    # fish, so this short test exercises actual paid-gun reloads and delivery.
    codex = project / 'production_snapshot/json/tbcodexfishunlockreward.json'
    rows = json.loads(codex.read_text(encoding='utf-8'))
    rows = [r for r in rows if not (102 <= r['fishId'] <= 108 and r['mutationId'] == 1)]
    codex.write_text(json.dumps(rows), encoding='utf-8')
    # Keep this fixture's first paid magazine affordable under real admission.
    for filename, field in [('tbgun.json', 'reloadResourceCost'), ('tbegg.json', 'baseHp')]:
        table = project / 'production_snapshot/json' / filename
        rows = json.loads(table.read_text(encoding='utf-8'))
        for row in rows:
            row[field] = {'sign': 1, 'digits': '1', 'scale': 0}
        table.write_text(json.dumps(rows), encoding='utf-8')
    config_path.write_text(yaml.safe_dump(cfg), encoding='utf-8')
    service = AuthoringService(project)
    def run(**kwargs):
        response = service.simulate('smoke_whale', **kwargs)
        assert response.ok, response.details
        output = Path(response.result['output_dir'])
        return output, lambda name: json.loads((output / name).read_text(encoding='utf-8'))
    _, full = run()
    partial, _ = run(until_seconds=187)
    _, resumed = run(checkpoint_input=partial / 'final_checkpoint.json')
    cp = full('final_checkpoint.json')
    other = resumed('final_checkpoint.json')
    assert cp['behavior_state'] == other['behavior_state']
    def coalesced(session):
        # A cutoff inside an advance inserts one extra advance boundary; retain
        # every action/receipt and the last response of adjacent advance calls.
        result = dict(session)
        history = []
        for entry in session['history']:
            if (history and json.loads(entry['input'])['op'] == 'advance'
                    and json.loads(history[-1]['input'])['op'] == 'advance'):
                history[-1] = entry
            else:
                history.append(entry)
        result['history'] = history
        return result
    assert coalesced(_unpack_session(cp['engine_state'])) == coalesced(_unpack_session(other['engine_state']))
    assert full('timeline.json')[-1] == resumed('timeline.json')[-1]
    manifest = full('run_manifest.json')['source_profiles']['default']
    assert manifest['initial_loadout']['fishCount'] == 29
    assert 'gun_owned:10103' in manifest['collection_growth']['initial_gun_facts']
    behavior = full('source_behavior.json')['profiles']['default']
    assert behavior['rejected_commands'] == {}
    completed = [r for r in behavior['tide_rounds'] if r['phase'] == 'completed']
    assert completed
    for tide in completed:
        assert tide['ammunition']['gunId'] == 10103
        assert tide['totalMaterialSpent'] == tide['ammunition']['materialCost']
    with FishSourceRuntime(FISH_SOURCE, project / 'production_snapshot/json') as runtime:
        state = runtime.restore(_unpack_session(cp['engine_state']))
        deployed = [f for f in state['inventory']['items'] if f['hallSlot'] > 0]
        normal = [f for f in deployed if f['fishId'] != 2004]
        beasts = [f for f in deployed if f['fishId'] == 2004]
        assert len(normal) == 1 and normal[0]['hallSlot'] == 1 and len(beasts) > 0
        assert sum(f['fishId'] == 2004 for f in state['inventory']['items']) == 29
        multiplier = Decimal('2.5') + Decimal('0.1') * (len(beasts) - 1)
        assert all(source_decimal(f['authoritativeMultiplier']) == multiplier for f in beasts)
        assert all(source_decimal(f['authoritativeRate']) > 0 for f in beasts)
        guns = state['guns']['owned']
        amr = next(g for g in guns if g['id'] == 10103)
        best = max((g for g in guns if g['id'] != 10103), key=lambda g: source_decimal(g['attack']))
        assert source_decimal(amr['attack']) == source_decimal(best['attack']) * Decimal('2.5')
        assert amr['reloadResourceCost'] == best['reloadResourceCost']
        assert state['guns']['combat']['equippedGunId'] == 10103
        quote = runtime.request({'op': 'query_tide', 'roundId': 'whale-test'})
        assert quote['attack'] == amr['attack'] and quote['reloadCost'] == amr['reloadResourceCost']
        assert quote['reloadCount'] >= 1
    with FishSourceRuntime(FISH_SOURCE, project / 'production_snapshot/json') as runtime:
        assert runtime.restore(_unpack_session(other['engine_state'])) == state
    response = service.simulate('month_1_all_permanent', checkpoint_input=partial / 'final_checkpoint.json', until_seconds=600)
    assert not response.ok and 'fish_source_checkpoint_loadout_mismatch' in str(response)
