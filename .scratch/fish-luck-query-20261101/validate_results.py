from pathlib import Path
import json, os, statistics, subprocess, sys
HERE=Path(__file__).resolve().parent
REPO=HERE.parents[1];ROOT=REPO/'.tmp/fish-luck-query-20261101'
identity=json.loads((HERE/'identity.json').read_text())
env=os.environ.copy();env['PYTHONPATH']=str(ROOT/'igess-src')
checks=[]
for receipt in sorted(HERE.glob('*.json')):
    row=json.loads(receipt.read_text(encoding='utf-8'))
    if not isinstance(row,dict) or 'response' not in row:continue
    result=row['response']['result'];variant=row['variant']
    def query(operation):
        args=[sys.executable,'-m','igess.cli','runs',operation,'--project',str(ROOT/(variant+'-project')),
              '--runs-root',str(ROOT/(variant+'-runs')),'--run-id',result['run_id'],'--json']
        completed=subprocess.run(args,cwd=REPO,env=env,capture_output=True,text=True,encoding='utf-8',check=True)
        value=json.loads(completed.stdout);assert value['ok'];return value['result']
    show=query('show');artifacts=query('artifacts');manifest=show['manifest']
    assert show['status']=='success' and show['identity_complete']
    assert all(a['exists'] for a in artifacts['items'])
    runtime=manifest['source_runtime']
    assert runtime['code_sha256']==identity[variant+'_source']
    assert runtime['selected_export_sha256']==identity['data']
    assert runtime['integration_code_sha256']=='9d5ca91921fdb5fcd764fa08e9da2dc2beed6e4a1bf798c5d7b207c4739c7d0c'
    expected=604800 if row['scenario']=='week_1_growth' else 86400
    assert manifest['execution_window']['start_seconds']==0 and manifest['execution_window']['end_seconds']==expected
    checks.append(dict(receipt=receipt.name,run_id=result['run_id'],variant=variant,scenario=row['scenario'],
        accepted_for_performance=receipt.name.startswith('pinned-') and not row['diagnostic_only'],
        diagnostic_only=row['diagnostic_only'],seconds=row['timings']['total'],status=show['status'],
        identity_complete=True,all_artifacts_exist=True,source_code_sha256=runtime['code_sha256'],
        selected_export_sha256=runtime['selected_export_sha256'],integration_code_sha256=runtime['integration_code_sha256']))
(HERE/'registry-checks.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
pairs=[]
for tag in ('pinned-final1','pinned-final2','pinned-final3'):
    values=[json.loads((HERE/f'{tag}-{v}-week_1_growth.json').read_text())['timings']['total'] for v in ('baseline','candidate')]
    pairs.append(dict(pair=tag,baseline_seconds=values[0],candidate_seconds=values[1],reduction_percent=(1-values[1]/values[0])*100))
b=statistics.median(p['baseline_seconds'] for p in pairs);c=statistics.median(p['candidate_seconds'] for p in pairs)
order=json.loads((HERE/'pinned-final-order.json').read_text())
assert len(order)==8 and all(not r['foreign_lua'] and r['returncode']==0 for r in order)
summary=dict(cpu_condition=json.loads((HERE/'cpu-condition.json').read_text()),pairs=pairs,baseline_median=b,candidate_median=c,reduction_percent=(1-c/b)*100,speedup=b/c,
    baseline_range=[min(p['baseline_seconds'] for p in pairs),max(p['baseline_seconds'] for p in pairs)],
    candidate_range=[min(p['candidate_seconds'] for p in pairs),max(p['candidate_seconds'] for p in pairs)],
    short={v:json.loads((HERE/f'pinned-short-{v}-day_1_growth.json').read_text())['timings']['total'] for v in ('baseline','candidate')})
(HERE/'final-summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
print(json.dumps(summary,indent=2))
