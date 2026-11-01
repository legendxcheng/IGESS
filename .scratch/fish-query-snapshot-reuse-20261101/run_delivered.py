"""Final bytes after constructor compatibility fix: three clean serial pairs."""
from pathlib import Path
import json, subprocess, sys, time
from control_env import foreign_lua, now
from compare import compare
HERE=Path(__file__).resolve().parent
order=[];comparisons=[]
for tag,scenario,variants in [
    ('delivered1','week_1_growth',['baseline','final']),
    ('delivered2','week_1_growth',['final','baseline']),
    ('delivered3','week_1_growth',['baseline','final']),
    ('delivered-short','day_1_growth',['baseline','final']),
]:
    for variant in variants:
        while foreign_lua():time.sleep(10)
        row=dict(tag=tag,scenario=scenario,variant=variant,started=now(),foreign_lua=[])
        print('START '+tag+' '+variant,flush=True)
        child=subprocess.Popen([sys.executable,str(HERE/'bench.py'),variant,scenario,tag])
        while child.poll() is None:
            other=foreign_lua(child.pid)
            if other:row['foreign_lua'].append(dict(at=now(),processes=other))
            try:child.wait(timeout=2)
            except subprocess.TimeoutExpired:pass
        row.update(finished=now(),returncode=child.returncode)
        order.append(row);(HERE/'delivered-order.json').write_text(json.dumps(order,indent=2),encoding='utf-8')
        assert child.returncode==0 and not row['foreign_lua'],row
    comparisons.append(compare(HERE/f'{tag}-baseline-{scenario}.json',HERE/f'{tag}-final-{scenario}.json'))
    (HERE/'delivered-comparisons.json').write_text(json.dumps(comparisons,indent=2),encoding='utf-8')
    print('MATCH '+tag,flush=True)
for scenario in ['day_1_growth','week_1_growth']:
    print('START delivered observation trace '+scenario,flush=True)
    completed=subprocess.run([sys.executable,str(HERE/'bench.py'),'final',scenario,'delivered-trace','--trace'],capture_output=True,text=True,encoding='utf-8')
    (HERE/('delivered-trace-'+scenario+'.log')).write_text(completed.stdout+completed.stderr,encoding='utf-8')
    assert completed.returncode==0,completed.stderr
    old='trace' if scenario=='day_1_growth' else 'full-trace'
    result=compare(HERE/f'{old}-baseline-{scenario}.json',HERE/f'delivered-trace-final-{scenario}.json')
    (HERE/('delivered-trace-'+scenario+'-comparison.json')).write_text(json.dumps(result,indent=2),encoding='utf-8')
    print('MATCH delivered trace '+str(result['observations']),flush=True)
print('DELIVERED TIMING AND TRACE COMPLETE',flush=True)
