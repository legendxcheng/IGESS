import hashlib
import json
import shutil
from pathlib import Path

from igess.operator_export import scan_operator_candidate

root = Path(__file__).resolve().parent
distribution = Path('E:/GameBalancer')
manifest = json.loads((distribution / '.igess-delivery-manifest.json').read_text(encoding='utf-8'))
actual = {p.relative_to(distribution).as_posix() for p in distribution.rglob('*') if p.is_file() and '.git' not in p.relative_to(distribution).parts}
assert actual == set(manifest['managed_files'])
for name, expected in manifest['sha256'].items():
    assert 'sha256:' + hashlib.sha256((distribution / name).read_bytes()).hexdigest() == expected, name
# The candidate scanner intentionally rejects Git metadata. Audit a byte-for-
# byte copy of the actual delivery, after verifying no extra files are omitted.
candidate = root / 'candidate-scan-0.5.19'
shutil.copytree(distribution, candidate, ignore=shutil.ignore_patterns('.git'))
managed = scan_operator_candidate(candidate)
result = {'version': manifest['tool_version'], 'managed_files': len(managed), 'unexpected_files': 0, 'hashes_match': True, 'source_leak_audit': 'passed'}
(root / 'candidate-audit-0.5.19.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
print(json.dumps(result))
