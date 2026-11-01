from pathlib import Path
import json, shutil, sys, yaml
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
ROOT = REPO/'.tmp/fish-luck-query-20261101'
assert not ROOT.exists(), 'Do not overwrite a frozen baseline'
ROOT.mkdir(parents=True)
sys.path.insert(0, str(REPO/'src'))
from igess.fish_source_runtime import source_code_digest, data_snapshot_digest
config = yaml.safe_load((REPO/'projects/fish_source/economy.yaml').read_text(encoding='utf-8'))
runtime = config['engine']['source_runtime']
source = (REPO/'projects/fish_source'/runtime['project_root']).resolve()
data = (REPO/'projects/fish_source'/runtime['data_root']).resolve()
shutil.copytree(REPO/'src', ROOT/'igess-src', ignore=shutil.ignore_patterns('__pycache__'))
shutil.copytree(data, ROOT/'data')
for variant in ('baseline', 'candidate'):
    for part in ('proj/Script', 'simulation'):
        shutil.copytree(source/part, ROOT/(variant+'-source')/part)
    project = ROOT/(variant+'-project'); project.mkdir()
    for part in ('Datas','luban_exports'):
        shutil.copytree(REPO/'projects/fish_source'/part, project/part)
    config['engine']['source_runtime'].update(project_root=str(ROOT/(variant+'-source')),data_root=str(ROOT/'data'))
    (project/'economy.yaml').write_text(yaml.safe_dump(config,allow_unicode=True,sort_keys=False),encoding='utf-8')
identity = dict(source_root=str(source),data_root=str(data),baseline_source=source_code_digest(ROOT/'baseline-source'),data=data_snapshot_digest(ROOT/'data'))
(HERE/'identity.json').write_text(json.dumps(identity,indent=2),encoding='utf-8')
print(json.dumps(identity))
