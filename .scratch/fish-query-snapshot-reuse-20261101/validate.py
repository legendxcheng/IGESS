"""Read formal run identities through public CLI; summarize serial pairs."""
from pathlib import Path
import json, os, statistics, subprocess, sys
HERE=Path(__file__).resolve().parent
REPO=HERE.parents[1]
WORK=REPO/'.tmp/fish-query-snapshot-reuse-20261101'
sys.path.insert(0,str(WORK/'igess-src'))
from igess.fish_source_runtime import source_code_digest, data_snapshot_digest
identity=json.loads((HERE/'identity.json').read_text())
identity['candidate_source']=source_code_digest(WORK/'candidate-source')
assert identity['baseline_source']==source_code_digest(WORK/'baseline-source')
assert identity['data']==data_snapshot_digest(WORK/'data')
(HERE/'identity.json').write_text(json.dumps(identity,indent=2),encoding='utf-8')
comparisons=json.loads((HERE/'pinned-final-comparisons.json').read_text())
assert len(comparisons)==6
order=json.loads((HERE/'pinned-final-order.json').read_text())
assert len(order)==12 and all(not r['foreign_lua'] and r['returncode']==0 for r in order)
env=os.environ.copy();env['PYTHONPATH']=str(WORK/'igess-src')
records=[]
for row in comparisons:
    for key in ['first','second']:
        receipt=json.loads(Path(row[key]).read_text(encoding='utf-8'))
        result=receipt['response']['result'];variant=receipt['variant']
        checks={}
        for op in ['show','artifacts']:
            command=[sys.executable,'-m','igess.cli','runs',op,'--project',str(WORK/(variant+'-project')),
                '--runs-root',str(WORK/(variant+'-runs')),'--run-id',result['run_id'],'--json']
            completed=subprocess.run(command,cwd=REPO,env=env,capture_output=True,text=True,encoding='utf-8',check=True)
            answer=json.loads(completed.stdout);assert answer['ok']
            checks[op]=answer['result']
            (HERE/(result['run_id']+'-'+op+'.json')).write_text(json.dumps(answer,indent=2),encoding='utf-8')
        show=checks['show'];manifest=show['manifest']
        assert show['status']=='success' and show['identity_complete']
        assert all(a['exists'] for a in checks['artifacts']['items'])
        assert manifest['source_runtime']['code_sha256']==identity[variant+'_source']
        assert manifest['source_runtime']['selected_export_sha256']==identity['data']
        end=604800 if receipt['scenario']=='week_1_growth' else 86400
        assert manifest['execution_window']['start_seconds']==0
        assert manifest['execution_window']['end_seconds']==end
        records.append(dict(variant=variant,run_id=result['run_id'],scenario=receipt['scenario'],seconds=receipt['timings']['total']))
def summarize(scenario):
    selected=[r for r in records if r['scenario']==scenario]
    timings={variant:[r['seconds'] for r in selected if r['variant']==variant] for variant in ['baseline','candidate']}
    medians={v:statistics.median(values) for v,values in timings.items()}
    pairs=[r for r in comparisons if scenario in r['first']]
    reductions=[100*(1-r['seconds'][1]/r['seconds'][0]) for r in pairs]
    return dict(timings=timings,medians=medians,reduction_percent=(1-medians['candidate']/medians['baseline'])*100,
        speed_ratio=medians['baseline']/medians['candidate'],ranges={v:[min(x),max(x)] for v,x in timings.items()},
        paired_reduction_percent=reductions,paired_reduction_median_percent=statistics.median(reductions))
summary=dict(week=summarize('week_1_growth'),day=summarize('day_1_growth'),runs=records,
    all_public_run_checks_passed=True,serial_no_foreign_lua=True)
(HERE/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
print(json.dumps({k:summary[k] for k in ['week','day']},indent=2))
