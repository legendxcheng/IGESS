"""Serial correctness trace, then clean formal timing pairs. No production edits."""
from pathlib import Path
from datetime import datetime, timezone
import json, subprocess, sys
from compare import compare
HERE=Path(__file__).resolve().parent
order=[]; comparisons=[]
def run(variant,scenario,tag,trace=False):
    print(f'START {tag} {variant} {scenario}',flush=True)
    started=datetime.now(timezone.utc).isoformat()
    command=[sys.executable,str(HERE/'bench.py'),variant,scenario,tag]
    if trace: command.append('--trace')
    subprocess.run(command,check=True)
    order.append(dict(variant=variant,scenario=scenario,tag=tag,trace=trace,started=started,finished=datetime.now(timezone.utc).isoformat()))
    (HERE/'run-order.json').write_text(json.dumps(order,indent=2),encoding='utf-8')
def check(tag,scenario):
    result=compare(HERE/f'{tag}-baseline-{scenario}.json',HERE/f'{tag}-candidate-{scenario}.json')
    comparisons.append(result)
    (HERE/'comparisons.json').write_text(json.dumps(comparisons,indent=2),encoding='utf-8')
    print('MATCH '+tag+' '+scenario,flush=True)
run('baseline','day_1_growth','trace',True)
run('candidate','day_1_growth','trace',True)
check('trace','day_1_growth')
run('candidate','week_1_growth','pair1')
check('pair1','week_1_growth')
for tag,variants in [('pair2',['candidate','baseline']),('pair3',['baseline','candidate'])]:
    for variant in variants:run(variant,'week_1_growth',tag)
    check(tag,'week_1_growth')
for variant in ['baseline','candidate']:run(variant,'day_1_growth','short')
check('short','day_1_growth')
