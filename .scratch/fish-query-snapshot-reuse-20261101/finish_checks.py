"""Wait for clean serial timing to finish, then run separate trace/regressions."""
from pathlib import Path
import json, os, subprocess, sys, time
HERE=Path(__file__).resolve().parent
REPO=HERE.parents[1]
WORK=REPO/'.tmp/fish-query-snapshot-reuse-20261101'
while True:
    p=HERE/'pinned-final-comparisons.json'
    try:
        if p.exists() and len(json.loads(p.read_text()))==6: break
    except json.JSONDecodeError: pass
    time.sleep(10)
for variant in ['baseline','candidate']:
    print('START full Week1 observation trace '+variant,flush=True)
    completed=subprocess.run([sys.executable,str(HERE/'bench.py'),variant,'week_1_growth','full-trace','--trace'],capture_output=True,text=True,encoding='utf-8')
    (HERE/('full-trace-'+variant+'.log')).write_text(completed.stdout+completed.stderr,encoding='utf-8')
    assert completed.returncode==0,completed.stderr
    print('DONE full Week1 observation trace '+variant,flush=True)
sys.path.insert(0,str(HERE))
from compare import compare
result=compare(HERE/'full-trace-baseline-week_1_growth.json',HERE/'full-trace-candidate-week_1_growth.json')
(HERE/'full-trace-comparison.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print('MATCH full Week1 '+str(result['observations'])+' observations',flush=True)
tests=[]
for name in ['simulation_snapshot_scope_test.lua','simulation_inventory_projection_test.lua','simulation_codex_test.lua','throw_luck_query_test.lua']:
    args=['lua55','tests/'+name]
    if name=='throw_luck_query_test.lua':args.append('igess_export/json')
    # Source tests use generated Lua tables; the luck test needs selected JSON.
    if name=='throw_luck_query_test.lua':args[-1]=str(WORK/'data')
    c=subprocess.run(args,cwd=WORK/'candidate-source',capture_output=True)
    (HERE/('final-'+name+'.log')).write_bytes(c.stdout+c.stderr)
    tests.append(dict(test=name,exit_code=c.returncode))
    print(name,c.returncode,flush=True)
env=os.environ.copy();env['PYTHONPATH']=str(WORK/'igess-src');env['FISH_SOURCE_ROOT']=str(WORK/'candidate-source')
# These existing suites resolve the sibling source directly. Run after delivery
# against live source separately, rather than claiming this env redirects them.
(HERE/'source-test-results.json').write_text(json.dumps(tests,indent=2),encoding='utf-8')
assert all(r['exit_code']==0 for r in tests),tests
print('ALL scheduled checks complete',flush=True)
