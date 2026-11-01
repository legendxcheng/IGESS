"""Public identity checks, smoke and attribution after clean timing completes."""
from pathlib import Path
import json, shutil, subprocess, sys, time
HERE=Path(__file__).resolve().parent;REPO=HERE.parents[1]
WORK=REPO/'.tmp/fish-query-snapshot-reuse-20261101'
while True:
    try:
        if len(json.loads((HERE/'delivered-comparisons.json').read_text()))==4:break
    except (FileNotFoundError,json.JSONDecodeError):pass
    time.sleep(10)
validated=subprocess.run([sys.executable,str(HERE/'validate_delivered.py')],capture_output=True,text=True,encoding='utf-8')
(HERE/'delivered-validation.log').write_text(validated.stdout+validated.stderr,encoding='utf-8')
assert validated.returncode==0,validated.stderr
smoke=subprocess.run([sys.executable,str(HERE/'bench.py'),'final','smoke','delivered-smoke'],capture_output=True,text=True,encoding='utf-8')
(HERE/'delivered-smoke.log').write_text(smoke.stdout+smoke.stderr,encoding='utf-8')
assert smoke.returncode==0,smoke.stderr
counts={}
for variant in ['baseline','final']:
    done=subprocess.run(['lua55',str(HERE/'count_snapshots.lua')],cwd=WORK/(variant+'-source'),capture_output=True,text=True,encoding='utf-8')
    assert done.returncode==0,done.stderr
    (HERE/(variant+'-delivered-count.log')).write_text(done.stdout+done.stderr,encoding='utf-8')
    counts[variant]=json.loads(done.stdout.splitlines()[-1])
    destination=WORK/(variant+'-source')/'igess_export/json'
    assert not destination.exists()
    shutil.copytree(WORK/'data',destination)
(HERE/'delivered-snapshot-counts.json').write_text(json.dumps(counts,indent=2),encoding='utf-8')
print('Final public run checks, smoke, counters: PASS',flush=True)
