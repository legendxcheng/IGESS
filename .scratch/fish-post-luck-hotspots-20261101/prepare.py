"""Freeze current inputs; instrument only an isolated copy. Does not simulate."""
from pathlib import Path
import hashlib,json,platform,shutil,subprocess,sys,yaml
HERE=Path(__file__).resolve().parent;REPO=HERE.parents[1]
WORK=REPO/'.tmp/fish-post-luck-hotspots-20261101'
assert not WORK.exists(),'Never overwrite a frozen experiment'
WORK.mkdir(parents=True)
project=REPO/'projects/fish_source'
config=yaml.safe_load((project/'economy.yaml').read_text(encoding='utf-8'))
runtime=config['engine']['source_runtime']
source=(project/runtime['project_root']).resolve();data=(project/runtime['data_root']).resolve()
shutil.copytree(REPO/'src',WORK/'igess-src',ignore=shutil.ignore_patterns('__pycache__'))
shutil.copytree(data,WORK/'data')
sys.path.insert(0,str(WORK/'igess-src'))
from igess.fish_source_runtime import source_code_digest,data_snapshot_digest
before=source_code_digest(source);data_before=data_snapshot_digest(data)
for variant in ('clean','diagnostic'):
    target=WORK/(variant+'-source')
    for part in ('proj/Script','simulation'):shutil.copytree(source/part,target/part)
    dest=WORK/(variant+'-project');dest.mkdir()
    for part in ('Datas','luban_exports'):shutil.copytree(project/part,dest/part)
    runtime.update(project_root=str(target),data_root=str(WORK/'data'))
    (dest/'economy.yaml').write_text(yaml.safe_dump(config,allow_unicode=True,sort_keys=False),encoding='utf-8')
assert before==source_code_digest(source)==source_code_digest(WORK/'clean-source')==source_code_digest(WORK/'diagnostic-source')
assert data_before==data_snapshot_digest(data)==data_snapshot_digest(WORK/'data')
target=WORK/'diagnostic-source'
cli=target/'simulation/cli.lua';content=cli.read_text(encoding='utf-8')
marker='local Json = require("simulation.Json")';assert content.count(marker)==1
content=content.replace(marker,(HERE/'probe.lua').read_text(encoding='utf-8')+'\n'+marker)
tail="""
local originalDispatch=dispatch
dispatch=function(request)
    if request.op=='perf_read' then
        debug.sethook()
        return {timings=perf,samples=sampled,totalSamples=totalSamples,combinations=combinations,owners=owners,suppressedRecursiveCalls=recursive}
    end
    perfOp=request.op
    return timed('dispatch',originalDispatch,request)
end
"""
marker='for line in io.lines() do';assert content.count(marker)==1
cli.write_bytes(content.replace(marker,tail+'\n'+marker).encode('utf-8'))
fish=target/'proj/Script/Domain/Fishing/FishEconomyRules.lua';content=fish.read_text(encoding='utf-8')
marker='FishEconomyRules.Build = RulesBuilder.Build';assert content.count(marker)==1
content=content.replace(marker,"local oldP0=calculateP0\ncalculateP0=function(...) return _G.__fishPerfTimed('fish.calculateP0',oldP0,...) end\n"+marker)
fish.write_bytes(content.encode('utf-8'))
query=target/'simulation/Query.lua';content=query.read_text(encoding='utf-8')
marker='function Query.Build(context, services, rules)';assert content.count(marker)==1
helpers="""local oldCopy,oldSame=copyValue,sameValue
copyValue=function(...) return _G.__fishPerfTimed('query.copyValue',oldCopy,...) end
sameValue=function(...) return _G.__fishPerfTimed('query.sameValue',oldSame,...) end
"""
content=content.replace(marker,helpers+marker)
marker='    function queries:Query(includeLuck, observation)';assert content.count(marker)==1
content=content.replace(marker,"    local oldInventory=queryInventory\n    queryInventory=function(...) return _G.__fishPerfTimed('query.inventoryProjection',oldInventory,...) end\n\n"+marker)
query.write_bytes(content.encode('utf-8'))
identity=dict(source_root=str(source),data_root=str(data),clean_source=before,
    diagnostic_source=source_code_digest(target),data=data_before,python=sys.version,machine=platform.platform(),
    scenario=config['scenarios']['week_1_growth'],seed=config['model']['random_seed'],
    git={str(p):subprocess.check_output(['git','-C',str(p),'rev-parse','HEAD'],text=True).strip() for p in (REPO,source)})
(HERE/'identity.json').write_text(json.dumps(identity,indent=2),encoding='utf-8')
(HERE/'original-economy.yaml').write_bytes((project/'economy.yaml').read_bytes())
print(json.dumps(identity,indent=2))
