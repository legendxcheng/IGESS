"""Correctness checks after final clean timing; can overlap diagnostic trace."""
from pathlib import Path
import json, os, subprocess, sys, time
HERE=Path(__file__).resolve().parent;REPO=HERE.parents[1]
WORK=REPO/'.tmp/fish-query-snapshot-reuse-20261101'
while True:
    try:
        if len(json.loads((HERE/'delivered-comparisons.json').read_text()))==4:break
    except (FileNotFoundError,json.JSONDecodeError):pass
    time.sleep(10)
tests=[dict(test='simulation_snapshot_scope_test.lua',exit_code=0,
    log='delivered-simulation_snapshot_scope_test.lua.log')]
for test in ['simulation_inventory_projection_test.lua','simulation_codex_test.lua','throw_luck_query_test.lua']:
    args=['lua55','tests/'+test]
    if test=='throw_luck_query_test.lua':args.append(str(WORK/'data'))
    run=subprocess.run(args,cwd=WORK/'final-source',capture_output=True)
    (HERE/('delivered-'+test+'.log')).write_bytes(run.stdout+run.stderr)
    tests.append(dict(test=test,exit_code=run.returncode))
(HERE/'delivered-source-test-results.json').write_text(json.dumps(tests,indent=2),encoding='utf-8')
assert all(r['exit_code']==0 for r in tests),tests
for phase in ['continuous','restored']:
    run=subprocess.run([sys.executable,str(HERE/'recovery.py'),'final',phase],capture_output=True,text=True,encoding='utf-8')
    assert run.returncode==0,run.stderr
values=[json.loads((HERE/('final-'+phase+'.json')).read_text()) for phase in ['continuous','restored']]
assert values[0]==values[1]
assert values[0]['state']==json.loads((HERE/'baseline-continuous.json').read_text())['state']
(HERE/'delivered-recovery-result.json').write_text(json.dumps({'restart_and_ordered_history_equal':True,'baseline_complete_state_equal':True},indent=2),encoding='utf-8')
env=os.environ.copy();env['PYTHONPATH']=str(WORK/'igess-src')
command=[sys.executable,'-m','pytest','tests/test_fish_source_current_rules.py','tests/test_fish_source_joint.py','tests/test_fish_source_toolkit.py','-q']
done=subprocess.run(command,cwd=REPO,env=env,capture_output=True,text=True,encoding='utf-8')
(HERE/'delivered-igess-regression.log').write_text(done.stdout+done.stderr,encoding='utf-8')
(HERE/'delivered-igess-regression-result.json').write_text(json.dumps({'command':command,'exit_code':done.returncode},indent=2),encoding='utf-8')
print(done.stdout[-1800:]+done.stderr[-500:],flush=True)
