"""Egg source session/replay and formal observation contracts."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess

import yaml
from igess.authoring.service import AuthoringService
from igess.fish_source_runtime import FishSourceRuntime

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get('FISH_SOURCE_ROOT', str(ROOT.parent / 'fish-oasis')))


def egg_state():
    script = """package.path='./?.lua;./proj/?.lua;'..package.path
local state=assert(require('Script.Domain.Player.PlayerArchiveSchema').New(0))
state.eggs.items={{instanceId=1,eggId=101,rarityId=1,mutationId=1,acquiredAt=0,hatchAt=30,rootSeed=77}}
state.eggs.nextInstanceId=2
io.write(require('simulation.Json').Encode(state))
"""
    result = subprocess.run(['lua55','-'],input=script,text=True,encoding='utf-8',cwd=SOURCE,capture_output=True,check=True)
    return json.loads(result.stdout)


def test_random_egg_instances_and_hatch_replay_across_processes():
    with FishSourceRuntime(SOURCE,SOURCE/'igess_export/json') as original:
        original.create(start_at=0,random_seed=37)
        original.request({'op':'advance','time':120})
        for index in range(3):
            receipt=original.request({'op':'grant_random_egg','requestId':f'tide:1:egg:{index}'})
            assert receipt['success'] and receipt['admitted']
        checkpoint=original.checkpoint()
        before=original.request({'op':'query'})
        assert len(before['eggs']['items'])==3
        assert len({e['rootSeed'] for e in before['eggs']['items']})==3
        assert all(e['acquiredAt']==120 for e in before['eggs']['items'])
        deadline=max(e['hatchAt'] for e in before['eggs']['items'])
        for index in range(3,5):
            original.request({'op':'grant_random_egg','requestId':f'tide:1:egg:{index}'})
        deadline=max(e['hatchAt'] for e in original.request({'op':'query'})['eggs']['items'])
        original.request({'op':'advance','time':deadline})
        expected=original.request({'op':'query'})
    with FishSourceRuntime(SOURCE,SOURCE/'igess_export/json') as restored:
        assert restored.restore(checkpoint)==before
        for index in range(5):
            restored.request({'op':'grant_random_egg','requestId':f'tide:1:egg:{index}'})
        restored.request({'op':'advance','time':deadline})
        assert restored.request({'op':'query'})==expected
        assert expected['inventory']['total']==5
        assert len(expected['eggs']['hatched'])==5


def test_formal_egg_observations_are_reported_without_free_player_grants(tmp_path,monkeypatch):
    project=tmp_path/'fish_source'
    project.mkdir()
    for name in ('economy.yaml','players.yaml','scenarios.yaml'):
        if (ROOT/'projects/fish_source'/name).exists():
            shutil.copy2(ROOT/'projects/fish_source'/name,project/name)
    for name in ('Datas','luban_exports'):
        shutil.copytree(ROOT/'projects/fish_source'/name,project/name)
    config_path=project/'economy.yaml'
    config=yaml.safe_load(config_path.read_text(encoding='utf-8'))
    config['engine']['source_runtime']['project_root']=str(SOURCE)
    config['engine']['source_runtime']['data_root']=str(SOURCE/'igess_export/json')
    config['scenarios']['smoke']['duration_hours']='0.02'
    config_path.write_text(yaml.safe_dump(config,allow_unicode=True),encoding='utf-8')
    create=FishSourceRuntime.create
    def with_egg(self,**kwargs):
        kwargs['initial_state']=egg_state()
        return create(self,**kwargs)
    monkeypatch.setattr(FishSourceRuntime,'create',with_egg)
    inputs={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (SOURCE/'igess_export/json').glob('*.json')}
    response=AuthoringService(project).simulate('smoke')
    assert response.ok,response.details
    output=Path(response.result['output_dir'])
    events=json.loads((output/'events.json').read_text(encoding='utf-8'))
    hatches=[e for e in events if e['kind']=='egg_hatched']
    assert len(hatches)==1 and hatches[0]['time_seconds']==30
    assert not any(e['kind']=='grant_random_egg' for e in events)
    behavior=json.loads((output/'source_behavior.json').read_text(encoding='utf-8'))['profiles']['default']
    assert len(behavior['egg_events'])==1
    report=json.loads((Path(response.result['report_index']).parent/'report_data.json').read_text(encoding='utf-8'))
    assert len(report['fish_progression']['actions']['default']['egg_events'])==1
    assert 'egg_hatched' not in report['fish_progression']['actions']['default']['accepted_commands']
    assert inputs=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (SOURCE/'igess_export/json').glob('*.json')}
    resumed=AuthoringService(project).simulate('smoke',checkpoint_input=output/'final_checkpoint.json')
    assert resumed.ok,resumed.details
    again=json.loads((Path(resumed.result['output_dir'])/'events.json').read_text(encoding='utf-8'))
    assert not any(e['kind']=='egg_hatched' for e in again)

def test_packaged_source_egg_results_match_checkout(tmp_path):
    from igess.fish_source_package import build_fish_source_package
    bundle=tmp_path/'runtime'
    build_fish_source_package(SOURCE,bundle,'lua55')
    def run(root):
        with FishSourceRuntime(root,SOURCE/'igess_export/json') as runtime:
            runtime.create(start_at=0,random_seed=37)
            runtime.request({'op':'grant_random_egg','requestId':'bundle:egg:1'})
            egg=runtime.request({'op':'query'})['eggs']['items'][0]
            runtime.request({'op':'advance','time':egg['hatchAt']})
            return runtime.request({'op':'query'})
    assert run(bundle)==run(SOURCE)
