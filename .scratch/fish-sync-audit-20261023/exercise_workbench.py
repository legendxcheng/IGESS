"""Exercise the delivered workbench form and verify its official artifacts."""
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INPUT = Path('E:/fish-oasis/igess_export/json')
HISTORY = Path(os.environ['LOCALAPPDATA']) / 'IGESS Operator/fish/runs'

def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))

def fingerprint():
    return {p.name: [p.stat().st_size, p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest()] for p in sorted(INPUT.glob('*.json'))}

def validate(run_dir):
    status = read(run_dir / 'run_status.json')
    metadata = read(run_dir / 'operator_run.json')
    manifest = read(run_dir / 'output/run_manifest.json')
    assert status['status'] == 'success', status
    assert metadata['tool_version'] == '0.5.19', metadata
    assert manifest['engine_id'] == 'fish_source'
    for name in manifest['artifacts']:
        assert (run_dir / 'output' / name).is_file(), name
    for name in ('index.html', 'report_data.json'):
        assert (run_dir / 'report' / name).is_file(), name
    assert (run_dir / 'output/final_checkpoint.json').is_file()
    runtime = read(Path('E:/GameBalancer/bundle/fish-runtime/runtime.json'))
    assert manifest['source_runtime']['packaged_source_code_sha256'] == runtime['source_code_sha256']
    return status, manifest

url = sys.argv[1].rstrip('/') + '/'
before = fingerprint()
results = []
for scenario in sys.argv[2:]:
    home = urllib.request.urlopen(url, timeout=10).read().decode('utf-8')
    assert '0.5.19' in home
    csrf = re.search(r'name="_csrf" value="([^"]+)"', home).group(1)
    previous = {p.name for p in HISTORY.iterdir() if p.is_dir()}
    body = urllib.parse.urlencode({'_csrf': csrf, 'tables': str(INPUT), 'scenario': scenario, 'baseline': ''}).encode()
    request = urllib.request.Request(url + 'run', data=body, headers={'Origin': url.rstrip('/'), 'Content-Type': 'application/x-www-form-urlencoded'})
    started = time.monotonic()
    print('Starting workbench ' + scenario, flush=True)
    response = urllib.request.urlopen(request, timeout=3600).read().decode('utf-8')
    assert '运行完成' in response
    created = [p for p in HISTORY.iterdir() if p.is_dir() and p.name not in previous]
    assert len(created) == 1, created
    run_dir = created[0]
    status, manifest = validate(run_dir)
    report_url = url + 'reports/' + run_dir.name + '/index.html'
    assert urllib.request.urlopen(report_url, timeout=10).status == 200
    result = {'scenario': scenario, 'run_id': run_dir.name, 'status': status['status'], 'report_url': report_url, 'report_index': status['report_index'], 'seconds': round(time.monotonic() - started, 2), 'source_runtime': manifest['source_runtime']}
    if scenario == 'day_1_growth':
        source = Path(read(ROOT / 'source-day-result.json')['result']['output_dir'])
        reference = read(source / 'run_manifest.json')
        assert reference['source_runtime']['selected_export_sha256'] == manifest['source_runtime']['selected_export_sha256']
        assert reference['source_runtime']['code_sha256'] == manifest['source_runtime']['packaged_source_code_sha256']
        for name in ('timeline.json', 'events.json', 'source_progression.json', 'source_behavior.json'):
            assert (source / name).read_bytes() == (run_dir / 'output' / name).read_bytes(), name
        result['source_day_core_artifacts_equal'] = True
    assert fingerprint() == before, 'Production JSON changed during verification'
    results.append(result)
    (ROOT / 'workbench-results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k != 'source_runtime'}, ensure_ascii=False), flush=True)
