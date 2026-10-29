"""Serial independent candidates; do not run other simulations alongside this."""
from pathlib import Path
import json
import subprocess
import sys
from compare import compare

HERE=Path(__file__).resolve().parent
results=[]
for variant in sys.argv[1:] or ['production','advance']:
    subprocess.run([sys.executable,str(HERE/'benchmark.py'),variant,'week_1_growth','isolated'],check=True)
    comparison=compare(HERE/'results/initial-baseline-week_1_growth.json',HERE/f'results/isolated-{variant}-week_1_growth.json')
    results.append(dict(variant=variant,**comparison))
    print(json.dumps(results[-1]),flush=True)
(HERE/'results/isolated-comparisons.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
