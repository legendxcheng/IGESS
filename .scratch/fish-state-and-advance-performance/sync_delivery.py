"""Apply only the accepted source files and append their maintenance contracts."""
from pathlib import Path
import hashlib
import json
import shutil

HERE=Path(__file__).resolve().parent
ROOT=Path('.tmp/fish-state-advance').resolve()
TARGET=Path('E:/fish-oasis')
paths=[
 'simulation/Observation.lua','simulation/Query.lua','simulation/Host.lua','simulation/cli.lua',
 'proj/Script/Application/PlayerProductionRuntime.lua',
 'proj/Script/Domain/Production/FishHallProductionCalculator.lua',
 'proj/Script/Domain/Production/FrozenFishRateCache.lua',
 'tests/simulation_observation_changes_test.lua','simulation/README.md',
]
source_note='''

## 状态变化观察与冻结生产计算

`query_changes` 是可选只读能力 `observationChangesVersion=1`，完整 `query` 接口不变。每个观察通道用 channel/token 标识基准；基准缺失、错配或通道切换时返回完整状态。变化响应明确携带字段替换、删除和对象部分更新，数组作为整体替换；空 Lua 表仍按既有 JSON 契约编码为 `[]`。观察不进入 checkpoint 的操作历史，恢复后重新建立完整基准。

`Query` 仅向内部 `Observation` 共享自己拥有且不再修改的背包/鱼厅稳定投影。公开完整 Query 和变化响应均返回独立数据；后续观察与调用方修改不能污染权威存档、缓存或之前的观察。缓存身份和完整校验沿用“查询性能与隔离”的规则；变化传输不会减少观察时点。

宿主使用 `PlayerProductionRuntime:BuildFrozenCalculator` 创建会话独立的生产计算器，并只通过既有结算 calculator 参数注入。该入口要求规则在计算器生命周期内保持冻结；普通游戏 `Configure` 和普通生产工厂行为不变。`BuildFrozenContribution` 的单条鱼厅产出缓存依赖完整鱼列表、规则身份、返祖产出倍率和服务器倍率，返回的大数均独立。余额、经过时间、效率、交易校验、回滚和回执仍在每次结算计算；缓存不进存档。

原有等价批量推进算法保留。本轮事件分段候选虽通过整周业务差分，但未证明性能收益，未接入交付实现。补充回归 `tests/simulation_observation_changes_test.lua`；IGESS 侧的 `test_fish_source_observation.py` 覆盖完整状态重建、隔离、恢复、能力回退和坏协议拒绝。整周逐次观察与无探针配对证据分别保存在 IGESS 的状态观察/推进性能任务中。
'''
readme=ROOT/'combined-source/simulation/README.md'
if '## 状态变化观察与冻结生产计算' not in readme.read_text(encoding='utf-8'):
    with readme.open('a',encoding='utf-8',newline='\n') as f: f.write(source_note)
for name in paths:
    before=ROOT/'baseline-source'/name
    current=TARGET/name
    if before.exists():
        if current.read_bytes()!=before.read_bytes(): raise RuntimeError(f'Source changed since freeze: {name}')
    elif current.exists(): raise RuntimeError(f'Unowned existing source file: {name}')
docs={
 '.agents/skills/fish_sim/SKILL.md': '''

状态变化观察与推进性能：修改 `observe`、`query_changes` 或冻结生产计算器时，先读源模拟说明的“状态变化观察与冻结生产计算”。消费者仍接收原时点的完整独立状态；传输基准不进 checkpoint，恢复重新建立，完整查询作为回退和差分参照。生产缓存仅用于会话拥有的冻结规则计算器，结算仍使用原精度、校验和回执。验收同时比较逐次逻辑观察与完整业务产物；正式测速关闭诊断记录。
''',
 '.agents/skills/fish_sim/references/code-map.md': '''

## 状态变化观察与冻结生产

- `src/igess/fish_source_runtime.py` 的 `observe`：能力协商、完整查询回退和观察错误；`fish_source_observation.py`：channel/token 基准、完整状态重建与返回对象隔离，参与适配器摘要。
- `<source>/simulation/Observation.lua`、`Query.lua` 的 `QueryChanges`：按部分返回变化，私有稳定投影复用；`Host.lua`/`cli.lua` 保证离线与鱼潮中可观察，观察操作不进入源历史。
- `<source>/proj/Script/Application/PlayerProductionRuntime.lua` 的 `BuildFrozenCalculator` → `Domain/Production/FishHallProductionCalculator.lua` 的 `BuildFrozenContribution` → `FrozenFishRateCache.lua`：冻结规则、会话独立的纯鱼厅产出复用；普通生产入口不启用此缓存。
- 回归入口：`tests/test_fish_source_observation.py` 与源 `tests/simulation_observation_changes_test.lua`；正式逐次观察差分和串行配对工具在 `.scratch/fish-state-and-advance-performance/`。既有准确/批量、满包孵化和跨进程恢复测试继续适用。
''',
 'projects/fish_source/README.md': '''

2026-10-29 状态观察新增可选变化传输：运行时依据源能力自动选择，在原有每个观察点重建完整独立状态，完整 Query 保留为回退接口。源宿主为每个会话创建冻结规则生产计算器，复用稳定鱼厅产出；动态余额、交易校验、精确大数、回执和 checkpoint 身份规则不变。原批量推进算法保留，未接入没有实测收益的事件分段候选。规格、逐次状态差分及整周配对见[状态观察与推进性能](../../.scratch/fish-state-and-advance-performance/spec.md)及[验收记录](../../.scratch/fish-state-and-advance-performance/verification.md)。本地实现不代表 GameBalancer 已更新。
''',
 'projects/fish_source/RoadMap.md': '''

## 2026-10-29 状态观察与推进性能

已接入完整逻辑状态的变化传输、私有稳定投影复用，以及会话独立的冻结鱼厅生产计算。保持观察时点、采样、精度、业务回执和恢复身份。事件分段候选没有证明整周收益，交付保留原推进算法。当前验证进度及配对证据以[验收记录](../../.scratch/fish-state-and-advance-performance/verification.md)为准；本次不发布 GameBalancer。
''',
}
backup=ROOT/'docs-before';backup.mkdir(exist_ok=True)
for name,note in docs.items():
    path=Path(name)
    target=backup/name
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists(): raise RuntimeError(f'Document backup already exists: {name}')
    shutil.copyfile(path,target)
for name in paths:
    target=TARGET/name;target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(ROOT/'combined-source'/name,target)
for name,note in docs.items():
    with Path(name).open('a',encoding='utf-8',newline='\n') as f: f.write(note)
digest=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
manifest={name:digest(TARGET/name) for name in paths}
(HERE/'delivery-files.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
(HERE/'doc-additions.json').write_text(json.dumps(docs,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'source_files':len(paths),'documents':len(docs)}))
