"""Codex slice through the formal run seam and its saved artifacts."""
import json
import os
import shutil
from decimal import Decimal
from pathlib import Path

import yaml
from igess.authoring.service import AuthoringService

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get('FISH_SOURCE_ROOT', str(ROOT.parent / 'fish-oasis')))


def test_formal_codex_claims_are_explicit_one_second_actions_and_separate_income(tmp_path):
    project = tmp_path / 'fish_source'
    shutil.copytree(ROOT / 'projects/fish_source', project, ignore=shutil.ignore_patterns('runs'))
    path = project / 'economy.yaml'
    config = yaml.safe_load(path.read_text(encoding='utf-8'))
    config['engine']['source_runtime'].update(project_root=str(SOURCE), data_root=str(SOURCE / 'igess_export/json'))
    config['scenarios']['smoke']['duration_hours'] = '0.05'  # Includes claims after five throws.
    config['scenarios']['smoke']['record_interval_seconds'] = 1
    config['player_profiles']['default']['behavior_weights'] = {'manual_throw': '1'}
    path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding='utf-8')
    response = AuthoringService(project).simulate('smoke')
    assert response.ok, response.details
    output = Path(response.result['output_dir'])
    events = json.loads((output / 'events.json').read_text(encoding='utf-8'))
    claims = [e for e in events if e['kind'] == 'claim_fish_reward']
    assert claims
    assert all(json.loads(e['details']['receipt'])['persistence'] ==
               dict(ok=True, code='ok', dirty=False, retryable=False) for e in claims)
    ids = [json.loads(e['details']['receipt'])['rewardId'] for e in claims]
    assert len(ids) == len(set(ids))
    unlocks = [e for e in events if e['kind'] == 'codex_fish_unlocked']
    assert unlocks
    assert unlocks[0]['time_seconds'] < claims[0]['time_seconds']
    next_event = events[events.index(claims[0]) + 1]
    assert next_event['time_seconds'] >= claims[0]['time_seconds'] + 1
    rows = json.loads((output / 'timeline.json').read_text(encoding='utf-8'))
    final = rows[-1]['resources']
    awarded = sum(Decimal(g['amount']['coeff']) * 10 ** g['amount']['exp']
                  for e in claims for g in json.loads(e['details']['receipt'])['grants'] if g['type'] == 'money')
    assert Decimal(final['online_codex_money_cumulative']) == awarded > 0
    assert Decimal(final['online_money_acquired_cumulative']) == awarded + Decimal(final['generated_money'])
    report = json.loads((Path(response.result['report_index']).parent / 'report_data.json').read_text(encoding='utf-8'))
    balance = report['fish_progression']['balance']['profiles']['default']
    assert balance['cumulative_rows'][-1]['codex_money_cumulative']['exact_value'] == str(awarded)
    resumed = AuthoringService(project).simulate('smoke', checkpoint_input=output / 'final_checkpoint.json')
    assert resumed.ok, resumed.details
    resumed_rows = json.loads((Path(resumed.result['output_dir']) / 'timeline.json').read_text(encoding='utf-8'))
    assert resumed_rows[-1] == rows[-1]

def test_codex_session_survives_source_isolated_runtime_package(tmp_path):
    from igess.fish_source_package import build_fish_source_package
    from igess.fish_source_runtime import FishSourceRuntime
    packaged = tmp_path / 'runtime'
    build_fish_source_package(SOURCE, packaged, 'lua55')
    data = SOURCE / 'igess_export/json'
    with FishSourceRuntime(SOURCE, data) as source, FishSourceRuntime(packaged, data) as runtime:
        assert runtime.create(start_at=0, random_seed=42, in_fishing_area=True) == source.create(
            start_at=0, random_seed=42, in_fishing_area=True)
        for payload in (
            {'op': 'prepare_throw', 'requestId': 'catch'},
            {'op': 'begin_throw_flight', 'requestId': 'catch'},
            {'op': 'advance', 'time': 1},
            {'op': 'select_throw_landing', 'requestId': 'catch', 'distanceCm': 100},
            {'op': 'finalize_throw_landing', 'requestId': 'catch'},
            {'op': 'complete_throw', 'requestId': 'catch'},
        ):
            assert runtime.request(payload) == source.request(payload)
        codex = runtime.request({'op': 'query_codex'})
        assert codex == source.request({'op': 'query_codex'})
        reward = codex['claimableRewards'][0]['rewardId']
        claim = {'op': 'claim_fish_reward', 'requestId': 'claim', 'rewardId': reward, 'revision': 0}
        receipt = runtime.request(claim)
        assert receipt == source.request(claim)
        assert receipt['persistence'] == dict(ok=True, code='ok', dirty=False, retryable=False)
        assert runtime.request({'op': 'query'}) == source.request({'op': 'query'})
