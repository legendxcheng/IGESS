"""Public CLI benchmark, or explicitly marked observation-trace verification."""
from pathlib import Path
import argparse, contextlib, hashlib, json, os, subprocess, sys, time
HERE=Path(__file__).resolve().parent
REPO=HERE.parents[1]
ROOT=REPO/'.tmp/fish-query-snapshot-reuse-20261101'
p=argparse.ArgumentParser();p.add_argument('variant',choices=['baseline','candidate','final']);p.add_argument('scenario');p.add_argument('tag');p.add_argument('--trace',action='store_true');a=p.parse_args()
target=HERE/(a.tag+'-'+a.variant+'-'+a.scenario+'.json')
assert not target.exists(), 'Do not overwrite benchmark receipts'
sys.path.insert(0,str(ROOT/'igess-src'))
args=['model','simulate','--project',str(ROOT/(a.variant+'-project')),'--scenario',a.scenario,'--runs-root',str(ROOT/(a.variant+'-runs')),'--json']
trace=[];last=None
if a.trace:
    from igess.fish_source_runtime import FishSourceRuntime
    from igess.cli import main
    original=FishSourceRuntime.request
    def observed(self,payload,**kw):
        global last
        result=original(self,payload,**kw)
        if payload['op']=='query':
            last=result
            trace.append({'options':payload,'hash':hashlib.sha256(json.dumps(result,sort_keys=True,separators=(',',':')).encode()).hexdigest()})
        return result
    FishSourceRuntime.request=observed
    import io
    output=io.StringIO();start=time.perf_counter()
    with contextlib.redirect_stdout(output): rc=main(args)
    elapsed=time.perf_counter()-start;stdout=output.getvalue();stderr=''
else:
    env=os.environ.copy();env['PYTHONPATH']=str(ROOT/'igess-src')
    start=time.perf_counter()
    result=subprocess.run([sys.executable,'-m','igess.cli',*args],cwd=REPO,env=env,capture_output=True,text=True,encoding='utf-8')
    elapsed=time.perf_counter()-start;rc=result.returncode;stdout=result.stdout;stderr=result.stderr
try: response=json.loads(stdout)
except Exception:
    target.with_suffix('.failure.log').write_text(stdout+'\n'+stderr,encoding='utf-8')
    raise
record=dict(variant=a.variant,scenario=a.scenario,tag=a.tag,diagnostic_only=a.trace,timings={'total':elapsed},response=response,stderr=stderr)
if a.trace:
    record['observation_trace']=trace
    observation=target.with_suffix('.observation.json');observation.write_text(json.dumps(last,sort_keys=True),encoding='utf-8');record['final_observation']=str(observation)
target.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'receipt':str(target),'seconds':elapsed,'response':response},ensure_ascii=False),flush=True)
assert rc==0 and response['ok'] and response['result']['status']=='success',record
