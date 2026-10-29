"""Isolated diagnostic of the delivered baseline; never a speedup benchmark."""
from pathlib import Path
import json
import runpy
import shutil
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = Path('.tmp/fish-performance-next-20261029').resolve()
ROOT.mkdir(exist_ok=True)
if not (ROOT/'baseline-source').exists():
    for part in ('proj/Script', 'simulation', 'igess_export/json'):
        shutil.copytree(Path('E:/fish-oasis')/part, ROOT/'baseline-source'/part)
    shutil.copytree('src', ROOT/'baseline-igess-src', ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copytree('.tmp/fish-query-perf/project', ROOT/'project')
sys.path.insert(0, str(ROOT/'baseline-igess-src'))
from igess.fish_source_runtime import FishSourceRuntime, source_code_digest, data_snapshot_digest
from igess.fish_source_engine import _integration_code_digest

identity = dict(source=source_code_digest(ROOT/'baseline-source'),
                data=data_snapshot_digest(ROOT/'baseline-source/igess_export/json'),
                adapter=_integration_code_digest())
(HERE/'identities.json').write_text(json.dumps(identity, indent=2), encoding='utf-8')
print(json.dumps(identity), flush=True)

PROBE = r'''
local perf = {}
local perfOp = 'startup'
local function add(label, elapsed, bytes)
    local key = perfOp .. '/' .. label
    local row = perf[key] or {count=0, seconds=0, bytes=0}
    row.count=row.count+1; row.seconds=row.seconds+elapsed
    row.bytes=row.bytes+(bytes or 0); perf[key]=row
end
local function wrap(object, method, label)
    local original=object[method]
    if type(original)~='function' then return end
    object[method]=function(...)
        local t=os.clock()
        local values=table.pack(original(...))
        add(label, os.clock()-t)
        return table.unpack(values,1,values.n)
    end
end
wrap(require('Script.Application.PlayerArchiveService'),'GetSnapshot','archive.GetSnapshot')
wrap(require('Script.Domain.Player.PlayerArchiveSchema'),'Validate','schema.Validate')
wrap(require('Script.Domain.Player.PlayerArchiveSchema'),'Clone','schema.Clone')
wrap(require('Script.Domain.Fishing.FishInventoryQuery'),'BuildAll','inventory.BuildAll')
wrap(require('Script.Domain.Fishing.FishEconomyRules'),'CalculateProductionSnapshot','fish.CalculateProductionSnapshot')
local encode=Json.Encode
Json.Encode=function(value)
    local t=os.clock(); local result=encode(value)
    add('json.Encode',os.clock()-t,#result)
    return result
end
local originalDispatch=dispatch
dispatch=function(request)
    if request.op=='perf_read' then return perf end
    perfOp=request.op
    local t=os.clock()
    local values=table.pack(originalDispatch(request))
    add('dispatch',os.clock()-t)
    return table.unpack(values,1,values.n)
end
'''

freeze = FishSourceRuntime._freeze_source
request = FishSourceRuntime.request
close = FishSourceRuntime.close
rows = {}
lua_runs = []
last_print = time.perf_counter()
active = False
loads = json.loads
python_json = {'count':0, 'seconds':0.0, 'bytes':0}

def measured_loads(value, *a, **kw):
    t=time.perf_counter()
    result=loads(value, *a, **kw)
    if active:
        python_json['count'] += 1
        python_json['seconds'] += time.perf_counter()-t
        python_json['bytes'] += len(value)
    return result

def instrument(self):
    root=freeze(self)
    cli=root/'simulation/cli.lua'
    contents=cli.read_text(encoding='utf-8')
    assert contents.count('for line in io.lines() do')==1
    cli.write_text(contents.replace('for line in io.lines() do', PROBE+'\nfor line in io.lines() do'), encoding='utf-8')
    return root

def measured(self, payload, **kw):
    global last_print, active
    wall=time.perf_counter(); cpu=time.process_time(); active=True
    try:
        result=request(self,payload,**kw)
    finally:
        active=False
        row=rows.setdefault(payload['op'],dict(count=0,wall=0.0,python_cpu=0.0))
        row['count']+=1; row['wall']+=time.perf_counter()-wall; row['python_cpu']+=time.process_time()-cpu
    if time.perf_counter()-last_print>30:
        print(json.dumps({'last_op':payload['op'],'state_time':result.get('time'),'requests':sum(x['count'] for x in rows.values())}),flush=True)
        last_print=time.perf_counter()
    return result

def capture_close(self):
    if self._process is not None and self.capabilities is not None:
        lua_runs.append(request(self,{'op':'perf_read'}))
    close(self)

FishSourceRuntime._freeze_source=instrument
FishSourceRuntime.request=measured
FishSourceRuntime.close=capture_close
json.loads=measured_loads
benchmark=HERE/'benchmark.py'
if not benchmark.exists():
    shutil.copyfile('.scratch/fish-source-query-performance/benchmark.py',benchmark)
sys.argv=[str(benchmark),'baseline','week_1_growth','diagnostic','--root',str(ROOT)]
started=time.perf_counter(); cpu_started=time.process_time()
try:
    runpy.run_path(str(benchmark),run_name='__main__')
finally:
    json.loads=loads
    result=dict(identity=identity,wall=time.perf_counter()-started,python_cpu=time.process_time()-cpu_started,
                requests=rows,python_json=python_json,lua_runs=lua_runs,
                warning='Instrumented diagnostic; inclusive wrapper times overlap, not a speedup benchmark')
    (HERE/'profile.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({'profile':str(HERE/'profile.json'),'wall':result['wall'],'python_cpu':result['python_cpu']}),flush=True)
