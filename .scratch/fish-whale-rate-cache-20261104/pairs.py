"""Serial uninstrumented formal pairs on one logical CPU; records each result."""
from pathlib import Path
import ctypes
import json
import platform
import subprocess
import sys
HERE=Path(__file__).resolve().parent
kernel=ctypes.WinDLL('kernel32',use_last_error=True)
kernel.SetProcessAffinityMask.argtypes=[ctypes.c_void_p,ctypes.c_size_t]
order=[('baseline','smoke_whale','pair1'),('candidate','smoke_whale','pair1'),
       ('candidate','smoke_whale','pair2'),('baseline','smoke_whale','pair2'),
       ('baseline','smoke_whale','pair3'),('candidate','smoke_whale','pair3'),
       ('baseline','smoke','short'),('candidate','smoke','short')]
log={'python':sys.version,'platform':platform.platform(),'affinity_mask':4,'order':[]}
for variant,scenario,tag in order:
    p=subprocess.Popen([sys.executable,str(HERE/'benchmark.py'),variant,scenario,tag],
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8')
    assert kernel.SetProcessAffinityMask(int(p._handle),4)
    stdout,stderr=p.communicate()
    row={'variant':variant,'scenario':scenario,'tag':tag,'exit_code':p.returncode,'stdout':stdout,'stderr':stderr}
    log['order'].append(row)
    (HERE/'order.json').write_text(json.dumps(log,indent=2),encoding='utf-8')
    print(stdout or stderr,flush=True)
    if p.returncode:raise SystemExit(p.returncode)
