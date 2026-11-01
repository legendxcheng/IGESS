"""Actual process restart, same-code identity, complete state and ordered history."""
from pathlib import Path
import json, subprocess, sys
HERE=Path(__file__).resolve().parent
WORK=HERE.parents[1]/'.tmp/fish-query-snapshot-reuse-20261101'
sys.path.insert(0,str(WORK/'igess-src'))
from igess.fish_source_runtime import FishSourceRuntime

if len(sys.argv)>1:
    variant,phase=sys.argv[1:]
    with FishSourceRuntime(WORK/(variant+'-source'),WORK/'data') as runtime:
        if phase=='continuous':
            runtime.create(start_at=0,random_seed=37,fast_advance=True,in_fishing_area=True)
            runtime.request({'op':'advance','time':30})
            saved=runtime.checkpoint()
            (HERE/(variant+'-restart.json')).write_text(json.dumps(saved),encoding='utf-8')
        else:
            runtime.restore(json.loads((HERE/(variant+'-restart.json')).read_text(encoding='utf-8')))
        runtime.request({'op':'advance','time':60})
        state=runtime.request({'op':'query','includeLuck':True})
        checkpoint=runtime.checkpoint()
        (HERE/(variant+'-'+phase+'.json')).write_text(json.dumps({'state':state,'checkpoint':checkpoint},sort_keys=True),encoding='utf-8')
else:
    states=[]
    for variant in ['baseline','candidate']:
        for phase in ['continuous','restored']:
            result=subprocess.run([sys.executable,__file__,variant,phase],capture_output=True,text=True,encoding='utf-8')
            assert result.returncode==0,result.stderr
        values=[json.loads((HERE/(variant+'-'+phase+'.json')).read_text(encoding='utf-8')) for phase in ['continuous','restored']]
        assert values[0]==values[1],variant+' restart differs'
        states.append(values[0]['state'])
    assert states[0]==states[1],'cross-variant complete state differs'
    (HERE/'recovery-result.json').write_text(json.dumps({'baseline_restart_equal':True,'candidate_restart_equal':True,'complete_state_equal':True},indent=2),encoding='utf-8')
    print('cross-process restart and complete state: PASS')
