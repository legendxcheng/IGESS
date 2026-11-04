"""Diagnostic late-inventory cost; separate from formal end-to-end scores."""
from pathlib import Path
import ctypes
import json
import statistics
import subprocess
HERE=Path(__file__).resolve().parent
REPO=HERE.parents[1]
root=REPO/'.tmp/fish-whale-rate-cache-20261104'
kernel=ctypes.WinDLL('kernel32',use_last_error=True)
kernel.SetProcessAffinityMask.argtypes=[ctypes.c_void_p,ctypes.c_size_t]
result={'note':'Recorded final inventory and default other systems, synthetic egg weights. Diagnostic, not a month simulation.','affinity_mask':4}
for variant in ('baseline','candidate'):
    p=subprocess.Popen(['lua55',str(HERE/'late-probe.lua'),str(HERE/'late-inventories.json'),
        str(root/'baseline-source/igess_export/json')],cwd=root/(variant+'-source'),
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8')
    assert kernel.SetProcessAffinityMask(int(p._handle),4)
    stdout,stderr=p.communicate(timeout=90)
    assert p.returncode==0,stderr
    data=json.loads(stdout)
    data['medians']={tag:{k:statistics.median(r[tag][k] for r in data['passes'])
        for k in data['passes'][0][tag]} for tag in data['passes'][0]}
    result[variant]=data
(HERE/'late-microbench.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps({v:result[v]['medians']['whale'] for v in ('baseline','candidate')},indent=2))
