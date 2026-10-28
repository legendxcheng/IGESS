"""Final chain and recovery checks at the approved public/formal boundaries."""
import json
import os
import shutil
import subprocess
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from igess.authoring.service import AuthoringService
from igess.fish_source_runtime import FishSourceRuntime

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get('FISH_SOURCE_ROOT', str(ROOT.parent / 'fish-oasis')))


def archive(body=''):
    script = "package.path='./?.lua;./proj/?.lua;'..package.path\nlocal s=assert(require('Script.Domain.Player.PlayerArchiveSchema').New(0))\n" + body + "\nio.write(require('simulation.Json').Encode(s))"
    return json.loads(subprocess.check_output(['lua55', '-e', script], cwd=SOURCE, text=True, encoding='utf-8'))


def project(tmp_path, duration=90, weights=None):
    target = tmp_path / 'fish_source'
    target.mkdir()
    for name in ('Datas', 'luban_exports'):
        shutil.copytree(ROOT / 'projects/fish_source' / name, target / name)
    shutil.copytree(SOURCE / 'igess_export/json', target / 'selected')
    config = yaml.safe_load((ROOT / 'projects/fish_source/economy.yaml').read_text(encoding='utf-8'))
    config['engine']['source_runtime'].update(project_root=str(SOURCE), data_root='selected')
    config['scenarios']['smoke'].update(duration_hours=str(duration / 3600), record_interval_seconds=5)
    config['player_profiles']['default']['behavior_weights'] = weights or {}
    (target / 'economy.yaml').write_text(yaml.safe_dump(config), encoding='utf-8')
    return target


def initial(monkeypatch, state):
    create = FishSourceRuntime.create
    def seeded(self, **kwargs):
        kwargs['initial_state'] = state
        return create(self, **kwargs)
    monkeypatch.setattr(FishSourceRuntime, 'create', seeded)


def run(target, **kwargs):
    result = AuthoringService(target).simulate('smoke', **kwargs)
    assert result.ok, result.details
    output = Path(result.result['output_dir'])
    read = lambda name: json.loads((output / name).read_text(encoding='utf-8'))
    report = json.loads((Path(result.result['report_index']).parent / 'report_data.json').read_text(encoding='utf-8'))
    return output, read, report


@pytest.mark.parametrize('count', [50, 51, 200])
def test_formal_inventory_uses_capacity_and_sees_later_page_deployment(tmp_path, monkeypatch, count):
    state = archive(f"""
for i=1,{count} do s.fish.items[i]={{instanceId=i,fishId=101,mutationId=1,weightGram=1000,level=1,hallSlot=i=={count} and 1 or 0}} end
s.fish.nextInstanceId={count + 1}
""")
    initial(monkeypatch, state)
    target = project(tmp_path, weights={'manual_throw': '1', 'sell_fish': '1'})
    _, read, _ = run(target)
    events = read('events.json')
    first = next(e for e in events if e['kind'] in {'prepare_throw', 'sell_fish'})
    assert first['kind'] == ('sell_fish' if count == 200 else 'prepare_throw')
    assert read('timeline.json')[0]['generators_owned']['deployed_fish'] == 1
    assert not any(e['kind'] == 'source_rejected' for e in events)
    if count == 200:
        assert read('timeline.json')[0]['resources']['treasure_beast_unlocked'] == '0'
        assert Decimal(read('timeline.json')[-1]['resources']['online_fish_sale_material_cumulative']) > 0


def test_formal_huge_codex_reward_remains_exact_in_wallet_and_report(tmp_path, monkeypatch):
    amount = '1' + '0' * 118 + '7'
    initial(monkeypatch, archive("s.collection.unlockedKeys={'101:1'}"))
    target = project(tmp_path, duration=2)
    path = target / 'selected/tbcodexfishunlockreward.json'
    rows = json.loads(path.read_text(encoding='utf-8'))
    next(r for r in rows if r['id'] == 10101)['rewardAmount'] = {'sign': 1, 'digits': amount, 'scale': 0}
    path.write_text(json.dumps(rows), encoding='utf-8')
    _, read, report = run(target)
    final = read('timeline.json')[-1]['resources']
    assert Decimal(final['money']) == Decimal(amount)
    assert Decimal(final['online_codex_money_cumulative']) == Decimal(amount)
    assert report['fish_progression']['balance']['profiles']['default']['remaining_rows'][-1]['money_remaining']['exact_value'] == amount


def test_formal_blocked_eggs_batch_matches_accurate_artifacts_and_restores(tmp_path, monkeypatch):
    state = archive("""
for i=1,200 do s.fish.items[i]={instanceId=i,fishId=101,mutationId=1,weightGram=1000,level=1,hallSlot=i==1 and 1 or 0} end
s.fish.nextInstanceId=201
s.eggs.items={{instanceId=1,eggId=101,rarityId=1,mutationId=1,acquiredAt=0,hatchAt=30,rootSeed=77},
 {instanceId=2,eggId=101,rarityId=1,mutationId=1,acquiredAt=0,hatchAt=150,rootSeed=78}}
s.eggs.nextInstanceId=3
""")
    initial(monkeypatch, state)
    target = project(tmp_path, duration=180)
    path = target / 'economy.yaml'
    config = yaml.safe_load(path.read_text(encoding='utf-8'))
    config['engine']['source_runtime']['advance_mode'] = 'accurate'
    path.write_text(yaml.safe_dump(config), encoding='utf-8')
    _, exact, _ = run(target)
    config['engine']['source_runtime']['advance_mode'] = 'equivalent_batch_v1'
    path.write_text(yaml.safe_dump(config), encoding='utf-8')
    _, batch, _ = run(target)
    for name in ('timeline.json', 'events.json', 'source_progression.json', 'source_behavior.json'):
        assert exact(name) == batch(name), name
    final = batch('timeline.json')[-1]['resources']
    assert final['egg_capacity_blocked'] == '1' and final['egg_inventory_count'] == '2'
    samples = {row['time_seconds']: row['resources'] for row in batch('timeline.json')}
    assert samples[25]['egg_capacity_blocked'] == '0'
    assert samples[30]['egg_capacity_blocked'] == '1'
    assert not any(e['kind'] == 'egg_hatched' for e in batch('events.json'))
    segment, _, _ = run(target, until_seconds=90)
    _, restored, _ = run(target, checkpoint_input=segment / 'final_checkpoint.json')
    assert restored('timeline.json')[-1] == batch('timeline.json')[-1]
    assert restored('final_checkpoint.json')['behavior_state'] == batch('final_checkpoint.json')['behavior_state']


def test_formal_wallet_one_below_huge_quote_never_submits_purchase(tmp_path, monkeypatch):
    wallet = '1' + '0' * 118 + '6'
    state = archive()
    state['wallet']['money'] = {'sign': 1, 'coeff': wallet, 'exp': 0}
    initial(monkeypatch, state)
    target = project(tmp_path, duration=31, weights={'synthesize_barbell': '1'})
    path = target / 'selected/tbbarbell.json'
    rows = json.loads(path.read_text(encoding='utf-8'))
    for row in rows:
        row['price'] = {'sign': 1, 'digits': wallet[:-1] + '7', 'scale': 0}
    path.write_text(json.dumps(rows), encoding='utf-8')
    _, read, _ = run(target)
    assert not any(e['kind'] in {'synthesize_barbell', 'source_rejected'} for e in read('events.json'))
    assert Decimal(read('timeline.json')[-1]['resources']['money']) == Decimal(wallet)


@pytest.mark.parametrize('cutoff', [60, 200])
def test_restored_report_retains_first_times_and_exact_online_scope(tmp_path, monkeypatch, cutoff):
    state = archive("""
local rules=assert(require('Script.Domain.Gun.GunRules').Default())
for _,key in ipairs(rules.rewards[101].keys) do s.collection.unlockedKeys[#s.collection.unlockedKeys+1]=key end
s.wallet.material={sign=1,coeff='9',exp=2}
""")
    rewards = json.loads((SOURCE / 'igess_export/json/tbcodexfishunlockreward.json').read_text(encoding='utf-8'))
    state['collection']['claimedFishUnlockRewardIds'] = [r['id'] for r in rewards if f"{r['fishId']}:{r['mutationId']}" in state['collection']['unlockedKeys']]
    initial(monkeypatch, state)
    target = project(tmp_path, duration=300)
    path = target / 'economy.yaml'
    config = yaml.safe_load(path.read_text(encoding='utf-8'))
    config['engine']['source_runtime']['room_origin_seconds'] = 10
    config['session_patterns'][config['player_profiles']['default']['session_pattern']]['daily_online_seconds'] = 150
    path.write_text(yaml.safe_dump(config), encoding='utf-8')
    _, full, full_report = run(target)
    first, _, _ = run(target, until_seconds=cutoff)
    _, restored, report = run(target, checkpoint_input=first / 'final_checkpoint.json')
    expected = full('source_behavior.json')['profiles']['default']['first_times']
    assert 'normal_codex_completed' not in expected  # Already complete in the starting archive.
    assert expected['gun_claimed']['time_seconds'] == 0
    assert expected['fish_tide_participated']['time_seconds'] == 10
    assert restored('source_behavior.json')['profiles']['default']['first_times'] == expected
    actions = report['fish_progression']['actions']['default']
    assert actions == restored('source_behavior.json')['profiles']['default']
    assert actions['first_times'] == expected
    assert 'claim_gun_reward' not in actions['accepted_commands']
    core = report['fish_progression']['core']['profiles']['default']
    assert core['summary']['active_duration_seconds']['exact_value'] == ('90' if cutoff == 60 else '0')
    assert core['rows'][-1]['active_time_seconds'] == 150
    assert core['rows'][-1]['active_time_seconds'] == full_report['fish_progression']['core']['profiles']['default']['rows'][-1]['active_time_seconds']


def test_free_codex_gun_recurring_tide_hatching_and_asset_reconciliation(tmp_path, monkeypatch):
    state = archive("""
local rules=assert(require('Script.Domain.Gun.GunRules').Default())
for _,key in ipairs(rules.rewards[101].keys) do
 if key~='103:1' then s.collection.unlockedKeys[#s.collection.unlockedKeys+1]=key end
end
""")
    target = project(tmp_path, duration=245, weights={'manual_throw': '1'})
    rewards_path = target / 'selected/tbcodexfishunlockreward.json'
    rewards = json.loads(rewards_path.read_text(encoding='utf-8'))
    state['collection']['claimedFishUnlockRewardIds'] = [r['id'] for r in rewards if f"{r['fishId']}:{r['mutationId']}" in state['collection']['unlockedKeys']]
    final_member = next(r for r in rewards if r['id'] == 10103)
    final_member.update(rewardType='material', rewardAmount={'sign': 1, 'digits': '300', 'scale': 0})
    rewards_path.write_text(json.dumps(rewards), encoding='utf-8')
    for name, key, selected in [('tbfishtideeggraritypool', 'eggRarityId', 1), ('tbfishtideeggmutationpool', 'mutationId', 2)]:
        path = target / f'selected/{name}.json'
        rows = json.loads(path.read_text(encoding='utf-8'))
        # A controlled selected export preserves the real source RNG/grant path.
        for row in rows:
            if row['poolId'] == 1 and row[key] != selected:
                row['weight'] = 0
        path.write_text(json.dumps(rows), encoding='utf-8')
    path = target / 'selected/tbegg.json'
    eggs = json.loads(path.read_text(encoding='utf-8'))
    next(r for r in eggs if r['id'] == 102)['hatchSeconds'] = 30
    path.write_text(json.dumps(eggs), encoding='utf-8')
    path = target / 'economy.yaml'
    config = yaml.safe_load(path.read_text(encoding='utf-8'))
    config['engine']['source_runtime']['room_origin_seconds'] = 60
    path.write_text(yaml.safe_dump(config), encoding='utf-8')
    initial(monkeypatch, state)
    _, read, report = run(target)
    events = read('events.json')
    completed = next(e for e in events if e['kind'] == 'complete_throw')
    assert json.loads(completed['details']['receipt'])['summary']['collectionKey'] == '103:1'
    behavior = read('source_behavior.json')['profiles']['default']
    assert behavior['first_times']['normal_codex_completed']['time_seconds'] == completed['time_seconds']
    claim = next(e for e in events if e['kind'] == 'claim_gun_reward')
    equip = next(e for e in events if e['kind'] == 'equip_gun')
    assert completed['time_seconds'] < claim['time_seconds'] < equip['time_seconds'] < 60
    rounds = behavior['tide_rounds']
    assert len(rounds) == 1 and rounds[0]['phase'] == 'completed'
    assert rounds[0]['occupied_seconds'] == 120 and len(rounds[0]['reloads']) == 6
    assert rounds[0]['admitted_egg_count'] == rounds[0]['hatched_egg_count'] == 5
    assert all(e['time_seconds'] == 180 for e in events if e['kind'] == 'egg_admitted')
    assert all(e['time_seconds'] == 210 for e in events if e['kind'] == 'egg_hatched')
    assert any(e['kind'] == 'claim_fish_reward' and e['time_seconds'] >= 210 for e in events)
    assert not any(e['kind'] in {'prepare_throw', 'start_exercise'} and 60 <= e['time_seconds'] < 180 for e in events)
    final = read('timeline.json')[-1]['resources']
    assert Decimal(final['online_tide_reload_material_cumulative']) == 300
    costs = sum(Decimal(r['cost']['coeff']).scaleb(r['cost']['exp']) for r in rounds[0]['reloads'])
    assert Decimal(final['online_tide_reload_material_cumulative']) == costs
    assert Decimal(final['material']) == Decimal(final['online_resource_acquired_cumulative']) - 300
    assert Decimal(final['money']) + Decimal(final['unclaimed_money']) == Decimal(final['generated_money']) + Decimal(final['online_codex_money_cumulative'])
    assert final['egg_inventory_count'] == '0' and final['egg_hatched_count'] == '5'
    assert int(final['fish_inventory_count']) == int(final['total_throws']) + 5
    assert report['fish_progression']['actions']['default']['tide_rounds'] == rounds
    assert not any(r['progression_category'] in {'codex_fish_unlocked', 'claim_fish_reward', 'egg_hatched'} for r in report['fish_progression']['persistent']['profiles']['default']['rows'])
    growth = report['fish_progression']['persistent']['profiles']['default']['rows']
    completed_growth = next(r for r in growth if r['progression_category'] == 'normal_codex_completed')
    gun_growth = next(r for r in growth if r['progression_category'] == 'gun_owned')
    assert completed_growth['wall_time_seconds'] == completed['time_seconds']
    assert gun_growth['wall_time_seconds'] == claim['time_seconds']
    hatch_growth = [r for r in growth if r['source_event_kind'] == 'codex_fish_unlocked' and r['wall_time_seconds'] == 210]
    assert hatch_growth and all('new_fish_variant' in r['progression_categories'] for r in hatch_growth)
    assert not any(r['source_event_kind'] == 'codex_fish_unlocked' and r['wall_time_seconds'] == 180 for r in growth)
    checkpoint = None
    segment_events = []
    segment_growth = []
    for until in (completed['time_seconds'], 40, 120, 200, 212, 245):
        segment, segment_read, segment_report = run(target, until_seconds=until, checkpoint_input=checkpoint)
        checkpoint = segment / 'final_checkpoint.json'
        segment_events.extend(segment_read('events.json'))
        segment_growth.extend(segment_report['fish_progression']['persistent']['profiles']['default']['rows'])
    assert segment_read('timeline.json')[-1] == read('timeline.json')[-1]
    assert segment_read('final_checkpoint.json')['behavior_state'] == read('final_checkpoint.json')['behavior_state']
    assert segment_report['fish_progression']['actions']['default']['first_times'] == behavior['first_times']
    accepted = lambda rows: [e for e in rows if e['details'].get('source') != 'observation' and e['kind'] not in {'gun_milestone', 'egg_admitted', 'egg_hatched'}]
    assert accepted(segment_events) == accepted(events)
    facts = lambda rows: [(r.get('event_identity'), r['source_event_kind'], r['item_id'],
                           r['active_time_seconds'], r.get('progression_categories')) for r in rows]
    assert facts(segment_growth) == facts(growth)


def test_formal_partial_egg_notice_failure_is_a_failed_run_with_source_evidence(tmp_path, monkeypatch):
    state = archive("""
s.wallet.material={sign=1,coeff='3',exp=2}
s.combat.ownedGunIds={10001};s.combat.equippedGunId=10001;s.combat.lastSelectedGunId=10001
""")
    initial(monkeypatch, state)
    target = project(tmp_path, duration=121)
    source = tmp_path / 'fault-source'
    for name in ('proj/Script', 'simulation'):
        shutil.copytree(SOURCE / name, source / name)
    # A private test source installs a failing external notification adapter;
    # the production host and selected production JSON remain unchanged.
    path = source / 'simulation/Host.lua'
    contents = path.read_text(encoding='utf-8')
    contents = contents.rsplit('return Host', 1)[0] + '''
local open = Host.Open
Host.Open = function(options)
    local calls = 0
    options.EggNotify = function() calls = calls + 1; return calls ~= 3 end
    return open(options)
end
return Host
'''
    path.write_text(contents, encoding='utf-8')
    path = target / 'economy.yaml'
    config = yaml.safe_load(path.read_text(encoding='utf-8'))
    config['engine']['source_runtime']['project_root'] = str(source)
    path.write_text(yaml.safe_dump(config), encoding='utf-8')
    result = AuthoringService(target).simulate('smoke')
    assert not result.ok and result.code == 'fish_source_tide_incomplete'
    assert result.result['status'] == 'failed'
    assert 'egg_notification_pending' in result.message
    assert '"admitted": true' in result.message
    assert '"phase": "granting"' in result.message
    assert '"instanceIds": [3]' in result.message
    statuses = list((target / 'runs').rglob('run_status.json'))
    assert len(statuses) == 1
    assert json.loads(statuses[0].read_text(encoding='utf-8'))['status'] == 'failed'


def test_formal_older_inventory_projection_is_rejected_before_run(tmp_path):
    target = project(tmp_path, duration=1)
    source = tmp_path / 'old-source'
    for name in ('proj/Script', 'simulation'):
        shutil.copytree(SOURCE / name, source / name)
    cli = source / 'simulation/cli.lua'
    cli.write_text(cli.read_text(encoding='utf-8').replace('        inventoryProjectionVersion = 1,\n', ''), encoding='utf-8')
    path = target / 'economy.yaml'
    config = yaml.safe_load(path.read_text(encoding='utf-8'))
    config['engine']['source_runtime']['project_root'] = str(source)
    path.write_text(yaml.safe_dump(config), encoding='utf-8')
    response = AuthoringService(target).simulate('smoke')
    assert not response.ok and response.code == 'fish_source_capability_missing'
    assert not list((target / 'runs').glob('*'))
