"""Read-only comparison of current Fish inputs; writes only this audit directory."""
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GAME = Path('E:/fish-oasis')
sys.path.insert(0, str(ROOT.parents[1] / 'src'))
from igess.fish_source_runtime import FishSourceRuntime
from igess.fish_source_engine import _REQUIRED_OPERATIONS

def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))

def differences(a, b, path=''):
    if isinstance(a, dict) and isinstance(b, dict):
        result = []
        for k in sorted(a.keys() | b.keys()):
            if k not in a or k not in b:
                result.append({'field': path + '/' + k, 'old': a.get(k), 'new': b.get(k)})
            else:
                result.extend(differences(a[k], b[k], path + '/' + k))
        return result
    if isinstance(a, list) and isinstance(b, list):
        if all(isinstance(r, dict) and 'id' in r for r in a + b):
            return differences({str(r['id']): r for r in a}, {str(r['id']): r for r in b}, path)
        if len(a) == len(b):
            return [d for i, (x, y) in enumerate(zip(a, b)) for d in differences(x, y, path + '/' + str(i))]
    return [] if a == b else [{'field': path, 'old': a, 'new': b}]

selected = GAME / 'igess_export/json'
fresh = ROOT / 'fresh-json'
summary = {'game_head': subprocess.check_output(['git', '-C', str(GAME), 'rev-parse', 'HEAD'], text=True).strip()}
with FishSourceRuntime(GAME, selected) as runtime:
    caps = runtime.capabilities
    summary['source_code_sha256'] = runtime.source_digest
    summary['selected_export_sha256'] = runtime.data_digest
    summary['capabilities'] = caps
    summary['missing_operations'] = sorted(_REQUIRED_OPERATIONS - set(caps['actions']))
    summary['missing_versions'] = [v for v in ('tideScheduleVersion', 'naturalLandingVersion', 'inventoryProjectionVersion') if caps.get(v) != 1]

summary['tables'] = {}
schema_text = (GAME / 'proj/Script/Config/Generated/schema.lua').read_text(encoding='utf-8')
indexes = dict(re.findall(r"file='([^']+)', mode='map', index='([^']+)'", schema_text))
for path in sorted(fresh.glob('*.json')):
    name = path.stem
    current = selected / path.name
    table = {'rows': len(read(path)), 'existing_json_matches_excel': current.exists() and current.read_bytes() == path.read_bytes()}
    if current.exists():
        table['existing_json_vs_excel'] = differences(read(current), read(path))
    lua = GAME / 'proj/Script/Table' / (name + '.lua')
    if lua.exists():
        code = "local J = dofile('simulation/Json.lua'); local t = dofile('proj/Script/Table/" + name + ".lua'); local r={}; for _,v in pairs(t) do r[#r+1]=v end; print(J.Encode(r))"
        result = subprocess.run(['lua55', '-e', code], cwd=GAME, capture_output=True, text=True, encoding='utf-8', check=True)
        lua_rows = json.loads(result.stdout)
        if lua_rows == {}:
            lua_rows = []
        # Lua nil fields are omitted, JSON uses null. Compare equivalent shapes.
        def normalize(v):
            if isinstance(v, dict):
                return {k: normalize(x) for k,x in v.items() if x is not None}
            if isinstance(v, list):
                return [normalize(x) for x in v]
            return v
        def keyed(rows):
            rows = normalize(rows)
            index = indexes.get(name)
            return {str(row[index]): row for row in rows} if index else rows
        table['game_lua_vs_excel'] = differences(keyed(lua_rows), keyed(read(path)))
        table['game_lua_vs_existing_json'] = differences(keyed(lua_rows), keyed(read(current))) if current.exists() else None
    summary['tables'][name] = table
(ROOT / 'audit.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({k: v for k,v in summary.items() if k != 'tables'}, ensure_ascii=False, indent=2))
for name, info in summary['tables'].items():
    diffs = info.get('existing_json_vs_excel', [])
    lua_diffs = info.get('game_lua_vs_excel', [])
    print(name, 'rows=', info['rows'], 'JSON diffs=', len(diffs), 'Lua diffs=', len(lua_diffs))
    for diff in diffs[:5]:
        print(' JSON:', json.dumps(diff, ensure_ascii=False))
    for diff in lua_diffs[:5]:
        print(' Lua:', json.dumps(diff, ensure_ascii=False))
status = subprocess.run([str(ROOT.parents[1] / '.tmp/py311-venv/Scripts/igess.exe'), 'model', 'status', '--project', str(ROOT.parents[1] / 'projects/fish_source'), '--json'], capture_output=True, text=True, encoding='utf-8')
(ROOT / 'model-status.json').write_text(status.stdout, encoding='utf-8')
print('model status exit:', status.returncode)
