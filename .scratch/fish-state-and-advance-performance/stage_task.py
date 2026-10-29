"""Stage task-only versions without absorbing pre-existing dirty hunks."""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess

parser=argparse.ArgumentParser();parser.add_argument('--commit',action='store_true');args=parser.parse_args()
ROOT=Path.cwd(); HERE=Path(__file__).resolve().parent; FREEZE=ROOT/'.tmp/fish-state-advance'
SOURCE=Path('E:/fish-oasis')
def git(repo,*arguments,input=None):
    return subprocess.check_output(['git','-c',f'safe.directory={repo.as_posix()}','-C',str(repo),*arguments],input=input)
def head_text(repo,name): return git(repo,'show',f'HEAD:{name}').decode('utf-8')
def replace(text,old,new):
    assert text.count(old)==1,old
    return text.replace(old,new)
def engine(text):
    text=replace(text,'"fish_source_runtime.py",','"fish_source_runtime.py", "fish_source_observation.py",')
    text=replace(text,'self.state = self.runtime.request({"op": "query"})','self.state = self.runtime.observe()')
    text=replace(text,'self.state = self.runtime.request({"op": "query", "includeLuck": include_luck})','self.state = self.runtime.observe(include_luck=include_luck)')
    return replace(text,'self.state = self.runtime.request({"op": "query", "includeLuck": True})\n        self.last_receipt', 'self.state = self.runtime.observe(include_luck=True)\n        self.last_receipt')
runtime_now=(ROOT/'src/igess/fish_source_runtime.py').read_text(encoding='utf-8')
observe=runtime_now[runtime_now.index('    def observe('):runtime_now.index('    def create(')]
def runtime(text):
    text=replace(text,'from typing import Any, Self\n','from typing import Any, Self\n\nfrom .fish_source_observation import SourceObservation\n')
    text=replace(text,'        self.capabilities: dict[str, Any] | None = None','        self.capabilities: dict[str, Any] | None = None\n        self._observation = SourceObservation()')
    text=replace(text,'    def create(',observe+'    def create(')
    return replace(text,'    def close(self) -> None:\n','    def close(self) -> None:\n        self._observation = SourceObservation()\n')

staged={}
for name,transform in [('fish_source_engine.py',engine),('fish_source_runtime.py',runtime)]:
    baseline=(FREEZE/'baseline-igess-src/igess'/name).read_text(encoding='utf-8')
    current=(ROOT/'src/igess'/name).read_text(encoding='utf-8')
    assert transform(baseline)==current,f'Unexpected changes in {name}'
    path=f'src/igess/{name}'
    staged[path]=transform(head_text(ROOT,path)).encode('utf-8')
docs=json.loads((HERE/'doc-additions.json').read_text(encoding='utf-8'))
for path,addition in docs.items():
    assert (ROOT/path).read_bytes()==(FREEZE/'docs-before'/path).read_bytes()+addition.encode('utf-8'),path
    staged[path]=(head_text(ROOT,path)+addition).encode('utf-8')
new_paths=['src/igess/fish_source_observation.py','tests/test_fish_source_observation.py']
new_paths += [str(p.relative_to(ROOT)).replace('\\','/') for p in HERE.glob('*.py')]
new_paths += [str(p.relative_to(ROOT)).replace('\\','/') for p in HERE.glob('*.md')]
new_paths += [str(p.relative_to(ROOT)).replace('\\','/') for p in HERE.glob('*.json')]
new_paths += [str(p.relative_to(ROOT)).replace('\\','/') for p in (HERE/'issues').glob('*.md')]
new_paths += [str(p.relative_to(ROOT)).replace('\\','/') for p in (HERE/'results').glob('*.json')]
# Earlier diagnostic evidence is referenced by this task's approved spec.
diagnostic=ROOT/'.scratch/fish-performance-next-20261029'
new_paths += [str(p.relative_to(ROOT)).replace('\\','/') for p in diagnostic.glob('*.py')]
new_paths += [str(p.relative_to(ROOT)).replace('\\','/') for p in diagnostic.glob('*.json')]
new_paths += [str(p.relative_to(ROOT)).replace('\\','/') for p in (diagnostic/'results').glob('*.json')]
for name in new_paths: staged[name]=(ROOT/name).read_bytes()
manifest=json.loads((HERE/'delivery-files.json').read_text(encoding='utf-8'))
for name,digest in manifest.items():
    assert hashlib.sha256((SOURCE/name).read_bytes()).hexdigest()==digest,name
for repo,label in [(ROOT,'igess'),(SOURCE,'source')]:
    assert git(repo,'rev-parse','HEAD').strip()==(FREEZE/f'{label}-head.txt').read_bytes().strip(),f'{label} HEAD moved'
    assert not git(repo,'diff','--cached','--name-only').strip(),f'{label} has staged work'
print(json.dumps({'igess_task_files':list(staged),'source_task_files':list(manifest)},ensure_ascii=False,indent=2),flush=True)
if not args.commit: raise SystemExit(0)
for name,contents in staged.items():
    oid=git(ROOT,'hash-object','-w','--stdin',input=contents).decode().strip()
    git(ROOT,'update-index','--add','--cacheinfo','100644',oid,name)
git(SOURCE,'add','--',*manifest)
for repo,message in [(SOURCE,'优化同源模拟的状态观察与冻结生产计算'),(ROOT,'接入变化状态观察并建立性能差分验收')]:
    git(repo,'diff','--cached','--check')
    print(git(repo,'commit','-m',message).decode('utf-8',errors='replace'),flush=True)
commits={label:git(repo,'rev-parse','HEAD').decode().strip() for repo,label in [(ROOT,'igess'),(SOURCE,'source')]}
(HERE/'implementation-commits.json').write_text(json.dumps(commits,indent=2),encoding='utf-8')
