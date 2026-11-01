"""Public run validation and diagnostic summaries; does not run simulations."""
from pathlib import Path
from collections import defaultdict
import base64,copy,json,os,pstats,subprocess,sys,zlib
HERE=Path(__file__).resolve().parent;REPO=HERE.parents[1];WORK=REPO/'.tmp/fish-post-luck-hotspots-20261101'
def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def save(name,value):(HERE/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
identity=read(HERE/'identity.json');order=read(HERE/'run-order.json')
assert len(order)==2 and all(row['exit_code']==0 and not row['foreign_lua'] for row in order)
env=os.environ.copy();env['PYTHONPATH']=str(WORK/'igess-src')
outputs=[];checks=[];manifests=[]
for variant,name in [('clean','clean-result.json'),('diagnostic','cli-result.json')]:
    response=read(HERE/name);assert response['ok'] and response['result']['status']=='success'
    result=response['result'];outputs.append(Path(result['output_dir']))
    def query(operation):
        args=[sys.executable,'-m','igess.cli','runs',operation,'--project',str(WORK/(variant+'-project')),
            '--runs-root',str(WORK/(variant+'-runs')),'--run-id',result['run_id'],'--json']
        completed=subprocess.run(args,cwd=REPO,env=env,capture_output=True,text=True,encoding='utf-8',check=True)
        answer=json.loads(completed.stdout);assert answer['ok'];save(variant+'-run-'+operation+'.json',answer)
        return answer['result']
    show=query('show');artifacts=query('artifacts');manifest=show['manifest'];manifests.append(manifest)
    assert show['status']=='success' and show['identity_complete']
    assert all(item['exists'] for item in artifacts['items'])
    assert manifest['execution_window']['start_seconds']==0 and manifest['execution_window']['end_seconds']==604800
    assert manifest['source_runtime']['code_sha256']==identity[variant+'_source']
    assert manifest['source_runtime']['selected_export_sha256']==identity['data']
    checks.append(dict(variant=variant,run_id=result['run_id'],all_artifacts_exist=True,identity_complete=True))
for name in ('timeline.json','events.json','source_progression.json','source_behavior.json'):
    assert (outputs[0]/name).read_bytes()==(outputs[1]/name).read_bytes(),name
def checkpoint(value):
    value=copy.deepcopy(value);value.pop('model_digest')
    packed=value.pop('engine_state');assert packed['codec']=='zlib-json-v1'
    session=json.loads(zlib.decompress(base64.b64decode(packed['data'])));session.pop('codeDigest')
    return value,session
checkpoints=[checkpoint(read(path/'final_checkpoint.json')) for path in outputs]
assert checkpoints[0]==checkpoints[1],'Instrumented checkpoint behavior/history changed'
mutated=read(outputs[0]/'final_checkpoint.json');mutated['next_throw_id']+=1
assert checkpoint(mutated)!=checkpoints[0]
for manifest in manifests:
    manifest.pop('model_digest')
    for key in ('code_sha256','timings_seconds'):manifest['source_runtime'].pop(key)
assert manifests[0]==manifests[1],'Input or business metadata changed'
save('validation.json',dict(runs=checks,core_bytes_equal=True,checkpoint_and_ordered_history_equal=True,
    manifest_equal_except_code_and_timing=True,negative_control_rejected=True))
p=read(HERE/'profile.json');assert p['exit_code']==0 and not p['capture_errors']
main=max(p['lua_runs'],key=lambda session:sum(row['count'] for row in session['timings'].values()))
def rows_for(op):
    rows=[]
    for key,value in main['timings'].items():
        operation,label=key.split('/',1)
        if operation==op:rows.append(dict(label=label,**value))
    return sorted(rows,key=lambda r:-r['seconds'])
owners=[]
for key,row in main['owners'].items():
    operation,owner,label=key.split('|',2)
    if operation=='query':owners.append(dict(owner=owner,label=label,**row))
combos={name:dict(calls=row['calls'],distinct_tuples=len(row['keys']),distinct_rule_tuples=len(row['ruleKeys'])) for name,row in main['combinations'].items()}
samples=defaultdict(int)
for key,count in main['samples'].items():
    op,source,name=key.split('|',2)
    if op=='query':samples[source.rsplit(':',1)[0]]+=count
stats=pstats.Stats(str(HERE/'python.pstats'));functions=[]
for (filename,line,name),(primitive,total,own,cumulative,callers) in stats.stats.items():
    functions.append(dict(file=filename,line=line,function=name,calls=total,self_seconds=own,inclusive_seconds=cumulative))
summary=dict(clean_wall_seconds=order[0]['wall_seconds'],diagnostic_wall_seconds=p['wall_seconds'],
    requests=main['request_timings'],all_requests=p['requests'],python_cpu_seconds=p['python_cpu_seconds'],
    python_response_json=p['python_response_json'],query=rows_for('query'),advance=rows_for('advance'),query_owners=owners,
    combinations=combos,suppressed_recursive_calls=main['suppressedRecursiveCalls'],
    query_instruction_samples_by_file=sorted(samples.items(),key=lambda row:-row[1]),
    python_by_self=sorted(functions,key=lambda row:-row['self_seconds'])[:25],
    python_by_inclusive=sorted(functions,key=lambda row:-row['inclusive_seconds'])[:25],
    warning='Instrumented inclusive timings overlap; os.clock and instruction samples are diagnostic. No speedup claim. Clone/copy/sameValue recursion is counted separately, timed at outer calls only.')
save('summary.json',summary)
print(json.dumps({k:summary[k] for k in ('clean_wall_seconds','diagnostic_wall_seconds','requests','query','combinations')},ensure_ascii=False,indent=2))
