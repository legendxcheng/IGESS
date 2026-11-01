"""Run existing IGESS source suites after trace and performance work finishes."""
from pathlib import Path
import json, subprocess, sys, time
HERE=Path(__file__).resolve().parent
REPO=HERE.parents[1]
while True:
    result=HERE/'source-test-results.json'
    if result.exists():
        tests=json.loads(result.read_text())
        assert all(r['exit_code']==0 for r in tests),tests
        break
    time.sleep(10)
command=[sys.executable,'-m','pytest','tests/test_fish_source_current_rules.py',
    'tests/test_fish_source_joint.py','tests/test_fish_source_toolkit.py','-q']
done=subprocess.run(command,cwd=REPO,capture_output=True,text=True,encoding='utf-8')
(HERE/'igess-regression.log').write_text(done.stdout+done.stderr,encoding='utf-8')
(HERE/'igess-regression-result.json').write_text(json.dumps({'command':command,'exit_code':done.returncode},indent=2),encoding='utf-8')
print(done.stdout[-1800:]+done.stderr[-500:])
