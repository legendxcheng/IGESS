"""Gun progression verified through the public session and formal workflow."""
from pathlib import Path
import json
import os
import shutil
import subprocess

import pytest
import yaml

from igess.authoring.service import AuthoringService
from igess.fish_source_runtime import FishSourceRuntime, FishSourceRejection

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get('FISH_SOURCE_ROOT', str(ROOT.parent / 'fish-oasis')))
pytestmark = pytest.mark.skipif(not (SOURCE / 'simulation/cli.lua').exists(), reason='paired Fish checkout required')


def initial_state():
    script = """package.path='./?.lua;./proj/?.lua;'..package.path
local state=assert(require('Script.Domain.Player.PlayerArchiveSchema').New(0))
local rules=assert(require('Script.Domain.Gun.GunRules').Default())
for _,id in ipairs({101,102}) do
 for _,key in ipairs(rules.rewards[id].keys) do
  state.collection.unlockedKeys[#state.collection.unlockedKeys+1]=key
 end
end
io.write(require('simulation.Json').Encode(state))
"""
    result = subprocess.run(['lua55', '-'], input=script, text=True, encoding='utf-8', cwd=SOURCE, capture_output=True, check=True)
    return json.loads(result.stdout)


def test_gun_claim_equipment_and_mutation_restore_across_processes():
    with FishSourceRuntime(SOURCE, SOURCE / 'igess_export/json') as original:
        state = original.create(start_at=0, initial_state=initial_state())
        assert state['guns']['tideEligible'] is False
        assert state['guns']['rewards'][1]['claimed'] is True
        original.request({'op':'claim_gun_reward','rewardId':101,'requestId':'claim'})
        assert original.request({'op':'query'})['guns']['combat']['equippedGunId'] == 0
        original.request({'op':'equip_gun','gunId':10001,'requestId':'equip'})
        checkpoint = original.checkpoint()
        expected = original.request({'op':'query'})
    with FishSourceRuntime(SOURCE, SOURCE / 'igess_export/json') as restored:
        assert restored.restore(checkpoint) == expected
        assert restored.request({'op':'query'})['guns']['tideEligible'] is True
        restored.request({'op':'claim_gun_reward','rewardId':101,'requestId':'claim'})
        with pytest.raises(FishSourceRejection, match='already_claimed'):
            restored.request({'op':'claim_gun_reward','rewardId':101,'requestId':'new'})


@pytest.mark.parametrize("pending_fish_rewards", [False, True])
def test_formal_run_claims_then_equips_and_reports_permanent_milestones(tmp_path, monkeypatch, pending_fish_rewards):
    project = tmp_path / 'fish_source'
    shutil.copytree(ROOT / 'projects/fish_source', project, ignore=shutil.ignore_patterns('runs'))
    config_path = project / 'economy.yaml'
    config = yaml.safe_load(config_path.read_text(encoding='utf-8'))
    config['engine']['source_runtime']['project_root'] = str(SOURCE)
    config['engine']['source_runtime']['data_root'] = str(SOURCE / 'igess_export/json')
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding='utf-8')
    fixture = initial_state()
    # This slice starts after historical single-fish claims, so its short window
    # isolates the separate gun claim/equip actions rather than the reward queue.
    unlocked = set(fixture['collection']['unlockedKeys'])
    reward_rows = json.loads((SOURCE / 'igess_export/json/tbcodexfishunlockreward.json').read_text(encoding='utf-8'))
    eligible_fish_rewards = sorted(
        row['id'] for row in reward_rows if f"{row['fishId']}:{row['mutationId']}" in unlocked
    )
    if not pending_fish_rewards:
        fixture['collection']['claimedFishUnlockRewardIds'] = eligible_fish_rewards
    else:
        config['scenarios']['smoke']['duration_hours'] = str((len(eligible_fish_rewards) + 4) / 3600)
        config_path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding='utf-8')
    create = FishSourceRuntime.create
    def create_with_codex(self, **kwargs):
        kwargs['initial_state'] = fixture
        return create(self, **kwargs)
    monkeypatch.setattr(FishSourceRuntime, 'create', create_with_codex)
    response = AuthoringService(project).simulate('smoke')
    assert response.ok, response.details
    output = Path(response.result['output_dir'])
    events = json.loads((output / 'events.json').read_text(encoding='utf-8'))
    claim = next(e for e in events if e['kind'] == 'claim_gun_reward')
    equip = next(e for e in events if e['kind'] == 'equip_gun')
    fish_claims = [e for e in events if e['kind'] == 'claim_fish_reward']
    expected_claims = eligible_fish_rewards if pending_fish_rewards else []
    assert [json.loads(e['details']['receipt'])['rewardId'] for e in fish_claims] == expected_claims
    assert [e['time_seconds'] for e in fish_claims] == list(range(1, len(expected_claims) + 1))
    assert claim['time_seconds'] == 0 and equip['time_seconds'] == len(expected_claims) + 1
    behavior = json.loads((output / 'source_behavior.json').read_text(encoding='utf-8'))['profiles']['default']
    milestones = behavior['gun_milestones']
    assert {m['kind'] for m in milestones} >= {'normal_codex_completed','gun_claimed','gun_equipped','gun_upgraded','fish_tide_unlocked'}
    assert len({m['identity'] for m in milestones}) == len(milestones)
    assert behavior['accepted_commands']['claim_gun_reward'] == 1
    report = json.loads((Path(response.result['report_index']).parent / 'report_data.json').read_text(encoding='utf-8'))
    displayed = report['fish_progression']['actions']['default']['gun_milestones']
    assert len(displayed) == len(milestones)
    system_rows = report['fish_progression']['persistent']['profiles']['default']['rows']
    assert len([row for row in system_rows if row['progression_category'] == 'fish_tide_unlocked']) == 1
    assert not any(row['progression_category'] == 'gun_owned' for row in system_rows)

    resumed = AuthoringService(project).simulate('smoke', checkpoint_input=output / 'final_checkpoint.json')
    assert resumed.ok, resumed.details
    resumed_events = json.loads((Path(resumed.result['output_dir']) / 'events.json').read_text(encoding='utf-8'))
    assert not any(e['kind'] in {'gun_milestone', 'claim_gun_reward', 'equip_gun'} for e in resumed_events)
