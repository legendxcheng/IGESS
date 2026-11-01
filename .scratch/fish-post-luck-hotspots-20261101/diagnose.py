from pathlib import Path
import contextlib,cProfile,json,os,sys,time
HERE=Path(__file__).resolve().parent
REPO=HERE.parents[1]
WORK=REPO/'.tmp/fish-post-luck-hotspots-20261101'
def save(name,value):
    (HERE/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
sys.path.insert(0, str(WORK/'igess-src'))
from igess.fish_source_runtime import FishSourceRuntime
from igess.cli import main

request = FishSourceRuntime.request
close = FishSourceRuntime.close
rows, lua_runs, errors = {}, [], []
last_print = time.perf_counter()
active_request = False
json_stats = {'calls':0, 'seconds':0., 'characters':0}
original_loads = json.loads

def measured_loads(value, *a, **kw):
    started = time.perf_counter()
    result = original_loads(value, *a, **kw)
    if active_request:
        json_stats['calls'] += 1
        json_stats['seconds'] += time.perf_counter()-started
        json_stats['characters'] += len(value)
    return result

def measured(self, payload, **kw):
    global active_request, last_print
    started = time.perf_counter(); cpu = time.process_time(); active_request = True
    value = {}
    try:
        value = request(self, payload, **kw)
        return value
    finally:
        active_request = False
        elapsed, cpu_elapsed = time.perf_counter()-started, time.process_time()-cpu
        if not hasattr(self, '_diag_rows'):
            self._diag_rows = {}
        for collection in (rows, self._diag_rows):
            row = collection.setdefault(payload['op'], {'calls':0, 'wall_seconds':0., 'python_cpu_seconds':0.})
            row['calls'] += 1; row['wall_seconds'] += elapsed
            row['python_cpu_seconds'] += cpu_elapsed
        if time.perf_counter()-last_print > 25:
            progress = {'op':payload['op'], 'state_time':value.get('time'), 'requests':sum(r['calls'] for r in rows.values()), 'elapsed':time.perf_counter()-start}
            print(json.dumps(progress), file=sys.stderr, flush=True)
            save('progress.json', progress)
            last_print = time.perf_counter()

def capture_close(self):
    try:
        if self._process is not None and self.capabilities is not None:
            capture = request(self, {'op':'perf_read'}, timeout_seconds=60)
            capture['request_timings'] = getattr(self, '_diag_rows', {})
            lua_runs.append(capture)
    except Exception as exc:
        errors.append(repr(exc))
    finally:
        close(self)

FishSourceRuntime.request = measured
FishSourceRuntime.close = capture_close
json.loads = measured_loads
args = ['model','simulate','--project',str(WORK/'diagnostic-project'),'--scenario','week_1_growth',
        '--runs-root',str(WORK/'diagnostic-runs'),'--json']
save('invocation.json', {'argv':args, 'entry':'igess.cli.main', 'profiler':'cProfile + Lua wrappers + instruction samples every 100000 instructions; per-service and owner counters; outer recursive calls only'})
profile = cProfile.Profile()
start = time.perf_counter(); cpu = time.process_time(); rc = None
try:
    with (HERE/'cli-result.json').open('w',encoding='utf-8') as output, contextlib.redirect_stdout(output):
        profile.enable()
        rc = main(args)
        profile.disable()
finally:
    elapsed = time.perf_counter()-start
    profile.disable()
    json.loads = original_loads
    profile.dump_stats(str(HERE/'python.pstats'))
    save('profile.json', {'wall_seconds':elapsed,'python_cpu_seconds':time.process_time()-cpu,
        'requests':rows,'python_response_json':json_stats,'lua_runs':lua_runs,'capture_errors':errors,'exit_code':rc,
        'warning':'Instrumented diagnostic, not clean timing. Inclusive timings overlap. self_seconds excludes other wrapped children only. Instruction sample shares are not CPU time shares.'})
    print(json.dumps({'wall_seconds':elapsed,'exit_code':rc,'profile':str(HERE/'profile.json')}),file=sys.stderr,flush=True)
raise SystemExit(rc)
