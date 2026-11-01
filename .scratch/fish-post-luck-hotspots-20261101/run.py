"""One clean Week1 then one instrumented Week1, serial public CLI execution."""
from pathlib import Path
import json,os,subprocess,sys,time
from control_env import foreign_lua,now
HERE=Path(__file__).resolve().parent;REPO=HERE.parents[1]
WORK=REPO/'.tmp/fish-post-luck-hotspots-20261101'
assert (HERE/'identity.json').exists(),'Finish prepare.py before executing the benchmark'
env=os.environ.copy();env['PYTHONPATH']=str(WORK/'igess-src')
order=[]
for variant in ('clean','diagnostic'):
    while foreign_lua():
        print('WAIT external Lua',flush=True);time.sleep(10)
    args=['model','simulate','--project',str(WORK/(variant+'-project')),'--scenario','week_1_growth','--runs-root',str(WORK/(variant+'-runs')),'--json']
    print('START '+variant,flush=True)
    row=dict(variant=variant,started=now(),foreign_lua=[],argv=args)
    start=time.perf_counter()
    if variant=='clean':
        output=(HERE/'clean-result.json').open('w',encoding='utf-8')
        child=subprocess.Popen([sys.executable,'-m','igess.cli',*args],cwd=REPO,env=env,stdout=output)
    else:
        output=None
        child=subprocess.Popen([sys.executable,str(HERE/'diagnose.py')],cwd=REPO,env=env)
    last=start
    while child.poll() is None:
        external=foreign_lua(child.pid)
        if external:row['foreign_lua'].append(dict(at=now(),processes=external))
        if time.perf_counter()-last>30:
            print(json.dumps({'phase':variant,'elapsed_seconds':round(time.perf_counter()-start,1)}),flush=True)
            last=time.perf_counter()
        try:child.wait(timeout=2)
        except subprocess.TimeoutExpired:pass
    elapsed=time.perf_counter()-start
    if output:output.close()
    row.update(finished=now(),exit_code=child.returncode,wall_seconds=elapsed)
    order.append(row);(HERE/'run-order.json').write_text(json.dumps(order,indent=2),encoding='utf-8')
    assert child.returncode==0,row
    assert not row['foreign_lua'],'External Lua overlap: do not treat wall time as isolated'
    result=json.loads((HERE/('clean-result.json' if variant=='clean' else 'cli-result.json')).read_text(encoding='utf-8'))
    assert result['ok'] and result['result']['status']=='success',result
    print('DONE '+variant+' '+str(round(elapsed,3))+' seconds '+result['result']['run_id'],flush=True)
