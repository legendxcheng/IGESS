"""Summarize diagnostic timing and verify its behavior against delivery evidence."""
import base64
import json
import zlib
from pathlib import Path

HERE=Path(__file__).resolve().parent
def read(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))

profile=read(HERE/'profile.json')
lua={}
for run in profile['lua_runs']:
    for key,row in run.items():
        acc=lua.setdefault(key,dict(count=0,seconds=0.0,bytes=0))
        for field,value in row.items(): acc[field]+=value
aggregates={}
for key,row in lua.items():
    label=key.split('/',1)[1]
    acc=aggregates.setdefault(label,dict(count=0,seconds=0.0,bytes=0))
    for field,value in row.items(): acc[field]+=value
summary=dict(wall=profile['wall'],python_cpu=profile['python_cpu'],python_json=profile['python_json'],
             request_wall=sum(x['wall'] for x in profile['requests'].values()),
             requests=sorted(profile['requests'].items(),key=lambda r:-r[1]['wall']),
             lua_aggregates=aggregates,
             query_detail={k:v for k,v in lua.items() if k.startswith('query/')},
             advance_detail={k:v for k,v in lua.items() if k.startswith('advance/')})

old=read('.scratch/fish-source-query-performance/results/delivery-lf-candidate-week_1_growth.json')
new=read(HERE/'results/diagnostic-baseline-week_1_growth.json')
assert old['response']['ok'] and new['response']['ok']
outputs=[Path(r['response']['result']['output_dir']) for r in (old,new)]
files=['timeline.json','events.json','source_progression.json','source_behavior.json']
checks={name:(outputs[0]/name).read_bytes()==(outputs[1]/name).read_bytes() for name in files}
checks['final_query']=read(old['final_observation'])==read(new['final_observation'])
checkpoints=[read(p/'final_checkpoint.json') for p in outputs]
sessions=[]
for c in checkpoints:
    c.pop('model_digest')
    engine=c.pop('engine_state')
    sessions.append(json.loads(zlib.decompress(base64.b64decode(engine['data']))))
checks['checkpoint_behavior']=checkpoints[0]==checkpoints[1]
checks['source_history_and_identity']=sessions[0]==sessions[1]
checks['same_code_adapter_data']=all(old['source_runtime'][k]==new['source_runtime'][k]
    for k in ('code_sha256','integration_code_sha256','selected_export_sha256'))
manifests=[read(p/'run_manifest.json') for p in outputs]
for m in manifests:
    m.pop('model_digest')
    runtime=m['source_runtime']
    for key in ('timings_seconds','project_root','data_root','selected_export_root'):
        runtime.pop(key,None)
checks['manifest_except_paths_model_digest_timings']=manifests[0]==manifests[1]
assert all(checks.values()),checks
summary['equivalence']=checks
summary['history_entries']=len(sessions[0]['history'])
summary['warning']='Instrumented elapsed times; inclusive subcall times overlap. No new speedup measured.'
(HERE/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
print(json.dumps(summary,indent=2))
