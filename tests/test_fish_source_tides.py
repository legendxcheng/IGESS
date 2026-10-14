"""Single tide at the public source session and formal workflow boundaries."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from igess.authoring.service import AuthoringService
from igess.fish_source_runtime import FishSourceRuntime

ROOT=Path(__file__).resolve().parents[1]
SOURCE=Path(os.environ.get('FISH_SOURCE_ROOT',str(ROOT.parent/'fish-oasis')))

def initial_state():
    script="""package.path='./?.lua;./proj/?.lua;'..package.path
local s=assert(require('Script.Domain.Player.PlayerArchiveSchema').New(0))
s.wallet.material={sign=1,coeff='3',exp=2}
s.combat.ownedGunIds={10001};s.combat.equippedGunId=10001;s.combat.lastSelectedGunId=10001
s.fish.items={{instanceId=1,fishId=101,mutationId=1,weightGram=1000,level=1,hallSlot=1}}
s.fish.nextInstanceId=2
io.write(require('simulation.Json').Encode(s))"""
    return json.loads(subprocess.check_output(['lua55','-e',script],cwd=SOURCE,text=True,encoding='utf-8'))

def test_mid_tide_replay_preserves_costs_and_five_random_eggs():
    with FishSourceRuntime(SOURCE,SOURCE/'igess_export/json') as original:
        original.create(start_at=0,initial_state=initial_state(),random_seed=37)
        admitted=original.request({'op':'start_tide','roundId':'round:1'})
        assert admitted['success'] and len(admitted['reloads'])==6
        original.request({'op':'advance','time':60})
        checkpoint=original.checkpoint()
        before=original.request({'op':'query'})
        assert before['eggs']['items']==[]
        original.request({'op':'advance','time':120})
        completed=original.request({'op':'complete_tide','roundId':'round:1'})
        expected=original.request({'op':'query'})
    with FishSourceRuntime(SOURCE,SOURCE/'igess_export/json') as restored:
        assert restored.restore(checkpoint)==before
        assert restored.request({'op':'start_tide','roundId':'round:1'})['materialSpent']['sign']==0
        restored.request({'op':'advance','time':120})
        assert restored.request({'op':'complete_tide','roundId':'round:1'})==completed
        assert restored.request({'op':'query'})==expected
        assert len(expected['eggs']['items'])==5 and expected['wallet']['material']['sign']==0

def project(tmp_path,duration):
    target=tmp_path/'fish_source';target.mkdir()
    for name in ('Datas','luban_exports'):
        shutil.copytree(ROOT/'projects/fish_source'/name,target/name)
    config=yaml.safe_load((ROOT/'projects/fish_source/economy.yaml').read_text(encoding='utf-8'))
    config['engine']['source_runtime'].update(project_root=str(SOURCE),data_root=str(SOURCE/'igess_export/json'),single_tide_at_seconds=0)
    config['scenarios']['smoke']['duration_hours']=str(duration/3600)
    (target/'economy.yaml').write_text(yaml.safe_dump(config,allow_unicode=True),encoding='utf-8')
    return target

@pytest.mark.parametrize('duration',[60,120])
def test_formal_single_tide_occupies_time_and_reports_actual_cost(tmp_path,monkeypatch,duration):
    create=FishSourceRuntime.create
    def fixture(self,**kwargs):
        kwargs['initial_state']=initial_state()
        return create(self,**kwargs)
    monkeypatch.setattr(FishSourceRuntime,'create',fixture)
    target=project(tmp_path,duration)
    response=AuthoringService(target).simulate('smoke')
    assert response.ok,response.details
    output=Path(response.result['output_dir'])
    events=json.loads((output/'events.json').read_text(encoding='utf-8'))
    starts=[e for e in events if e['kind']=='start_tide']
    assert len(starts)==1
    assert not any(e['kind'] in {'prepare_throw','start_exercise','collect_slot','claim_fish_reward'} for e in events)
    last=json.loads((output/'timeline.json').read_text(encoding='utf-8'))[-1]
    assert last['resources']['online_tide_reload_material_cumulative']=='300'
    assert last['resources']['online_resource_acquired_cumulative']=='0'
    assert last['resources']['online_money_acquired_cumulative']!='0'
    checkpoint=json.loads((output/'final_checkpoint.json').read_text(encoding='utf-8'))
    if duration==60:
        assert checkpoint['behavior_state']['pending_tide']['endsAt']==120
        assert last['resources']['egg_inventory_count']=='0'
    else:
        assert checkpoint['behavior_state']['pending_tide'] is None
        assert last['resources']['egg_inventory_count']=='5'
    behavior=json.loads((output/'source_behavior.json').read_text(encoding='utf-8'))['profiles']['default']
    assert behavior['tide_rounds'][0]['roundId']=='controlled:0'
    assert behavior['tide_rounds'][0]['occupied_seconds']==duration
    manifest=json.loads((output/'run_manifest.json').read_text(encoding='utf-8'))
    assert manifest['source_runtime']['tide_policy']['reloads']==6
    report=json.loads((Path(response.result['report_index']).parent/'report_data.json').read_text(encoding='utf-8'))
    assert report['fish_progression']['actions']['default']['tide_rounds']==behavior['tide_rounds']
    resumed=AuthoringService(target).simulate('smoke',checkpoint_input=output/'final_checkpoint.json')
    assert resumed.ok,resumed.details
@pytest.mark.parametrize('cost', [0,-1])
def test_reload_price_zero_is_valid_and_negative_is_diagnosed(tmp_path,cost):
    data=tmp_path/'export';shutil.copytree(SOURCE/'igess_export/json',data)
    path=data/'tbgun.json';rows=json.loads(path.read_text(encoding='utf-8'))
    rows[0]['reloadResourceCost']={'sign':cost,'digits':'0' if cost==0 else '1','scale':0}
    path.write_text(json.dumps(rows),encoding='utf-8')
    with FishSourceRuntime(SOURCE,data) as runtime:
        if cost<0:
            from igess.fish_source_runtime import FishSourceRejection
            with pytest.raises(FishSourceRejection):
                runtime.create(start_at=0,initial_state=initial_state())
        else:
            runtime.create(start_at=0,initial_state=initial_state())
            r=runtime.request({'op':'start_tide','roundId':'free-config'})
            assert r['success'] and len(r['reloads'])==6 and r['materialSpent']['sign']==0
            assert runtime.request({'op':'query'})['wallet']['material']=={'sign':1,'coeff':'3','exp':2}
