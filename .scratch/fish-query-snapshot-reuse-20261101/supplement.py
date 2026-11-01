"""Prespecified fourth reverse-order pair after observed baseline drift."""
from pathlib import Path
import json, subprocess, sys, time
from control_env import foreign_lua, now
from compare import compare
HERE=Path(__file__).resolve().parent
while True:
    p=HERE/'pinned-final-comparisons.json'
    try:
        if p.exists() and len(json.loads(p.read_text()))==5: break
    except json.JSONDecodeError: pass
    time.sleep(10)
order=json.loads((HERE/'pinned-final-order.json').read_text())
for variant in ['candidate','baseline']:
    while foreign_lua():time.sleep(10)
    record=dict(tag='pinned-supplement',scenario='week_1_growth',variant=variant,started=now(),foreign_lua=[])
    print('START supplement '+variant,flush=True)
    child=subprocess.Popen([sys.executable,str(HERE/'bench.py'),variant,'week_1_growth','pinned-supplement'])
    while child.poll() is None:
        other=foreign_lua(child.pid)
        if other:record['foreign_lua'].append(dict(at=now(),processes=other))
        try:child.wait(timeout=2)
        except subprocess.TimeoutExpired:pass
    record.update(finished=now(),returncode=child.returncode)
    order.append(record)
    (HERE/'pinned-final-order.json').write_text(json.dumps(order,indent=2),encoding='utf-8')
    assert child.returncode==0 and not record['foreign_lua'],record
result=compare(HERE/'pinned-supplement-baseline-week_1_growth.json',HERE/'pinned-supplement-candidate-week_1_growth.json')
comparisons=json.loads(p.read_text());comparisons.append(result)
p.write_text(json.dumps(comparisons,indent=2),encoding='utf-8')
print('MATCH supplement',flush=True)
