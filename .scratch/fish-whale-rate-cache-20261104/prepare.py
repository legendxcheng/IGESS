from pathlib import Path
import json
import shutil
import yaml
from igess.fish_source_runtime import source_code_digest,data_snapshot_digest
root=Path('.tmp/fish-whale-rate-cache-20261104').resolve()
for part in ('proj/Script','simulation','tests'):
    shutil.copytree(Path('E:/fish-oasis')/part,root/'candidate-source'/part)
shutil.copytree(root/'baseline-source/igess_export/json',root/'candidate-source/igess_export/json')
shutil.copytree('src',root/'candidate-igess-src',ignore=shutil.ignore_patterns('__pycache__'))
for variant in ('baseline','candidate'):
    target=root/(variant+'-project')
    shutil.copytree(root/'project',target)
    config=yaml.safe_load((target/'economy.yaml').read_text(encoding='utf-8'))
    config['engine']['source_runtime'].update(project_root=str(root/(variant+'-source')),
        data_root=str(root/'baseline-source/igess_export/json'))
    config['scenarios']['smoke_whale']['duration_hours']='2'
    (target/'economy.yaml').write_text(yaml.safe_dump(config,allow_unicode=True),encoding='utf-8')
Path('.scratch/fish-whale-rate-cache-20261104/candidate.json').write_text(json.dumps({
    'source_sha256':source_code_digest(root/'candidate-source'),
    'data_sha256':data_snapshot_digest(root/'candidate-source/igess_export/json'),
    'scenario':'smoke_whale','duration_hours':2},indent=2))
print('Frozen baseline/candidate and identical 2-hour whale scenarios ready')
