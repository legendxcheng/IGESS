"""Frozen formal-entry benchmark, or exact observation differential (separate)."""
from pathlib import Path
import argparse
import hashlib
import json
import sys
import time

HERE=Path(__file__).resolve().parent
REPO=HERE.parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('variant',choices=['baseline','candidate'])
parser.add_argument('scenario')
parser.add_argument('tag')
parser.add_argument('--observations',action='store_true')
args=parser.parse_args()
root=REPO/'.tmp/fish-whale-rate-cache-20261104'
sys.path.insert(0,str(root/(args.variant+'-igess-src')))
from igess.authoring.service import AuthoringService
from igess.fish_source_runtime import FishSourceRuntime

last=None
observations=[]
original=FishSourceRuntime.request
def observed(self,payload,**kwargs):
    global last
    value=original(self,payload,**kwargs)
    if payload['op']=='query':
        last=value
        if args.observations:
            observations.append({'query':payload,'time':value['time'],'sha256':hashlib.sha256(
                json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()})
    return value
FishSourceRuntime.request=observed
started=time.perf_counter()
response=AuthoringService(root/(args.variant+'-project')).simulate(args.scenario)
elapsed=time.perf_counter()-started
receipt={'variant':args.variant,'tag':args.tag,'scenario':args.scenario,
    'timings':{'total':elapsed},'response':response.to_payload(),'diagnostic':args.observations}
if response.ok:
    output=Path(response.result['output_dir'])
    path=output.parent/'final_observation.json'
    path.write_text(json.dumps(last,sort_keys=True),encoding='utf-8')
    receipt['final_observation']=str(path)
    if args.observations:
        receipt['observations']=observations
dest=HERE/'results'/f'{args.tag}-{args.variant}-{args.scenario}.json'
dest.parent.mkdir(exist_ok=True)
assert not dest.exists()
dest.write_text(json.dumps(receipt,indent=2),encoding='utf-8')
print(json.dumps({'ok':response.ok,'seconds':elapsed,'receipt':str(dest),'details':dict(response.details)}))
if not response.ok:raise SystemExit(1)
