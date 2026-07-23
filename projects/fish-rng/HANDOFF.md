# Fish Economy Simulator Handoff

> **历史快照：** 本文记录 2026-07-20 的交接状态，不再更新进度。当前唯一进度源是 [`../fish/RoadMap.md`](../fish/RoadMap.md)。

更新时间：2026-07-20  
项目范围：`projects/fish-rng`  
开发基线提交：`d53cd7f`  
总实施计划：`FISH_ECONOMY_SIMULATOR_PLAN.md`

> 本文更新时，玩家存档/checkpoint 里程碑仍在工作区中，是否已经提交应以
> `git status` 和最新提交为准。接手时不要清理不属于自己的未提交文件。

## 1. 当前结论

项目已经从“独立 Fish RNG 验证工具”转向统一的
`FishEconomySimulator` 架构。

目前有两块可信基础：

1. RNG 一期基线已经完成，BonusChain、变异、鱼/废料随机流和百万次
   示例概率已经验证。
2. 玩家存档基础已经完成，正式游戏业务 Schema、BigNumber DTO、
   `SimulationCheckpoint`、Fish codec、严格校验和规范化 JSON 已经
   落地。

尚未完成：

- IGESS 领域引擎协议和 `FishEngineAdapter` 接入。
- `FishEconomySimulator` 主循环。
- 权威单次炸鱼纯函数 `resolve_throw()`。
- `tbfishrandompool` 生产表到直接力量/FishLuck 插值的正式适配。
- 鱼厅、金钱、废料、材料、升级、重生和离线经济循环。

因此不能把当前项目描述为完整经济模拟器。当前最准确的状态是：

```text
RNG phase 1 已验证
+ PlayerState / checkpoint foundation 已完成
+ FishEconomySimulator / 经济状态迁移尚未实现
```

旧 HANDOFF 中“先把独立 RNG 全部完成，最后再接经济层”的实施顺序已由
`FISH_ECONOMY_SIMULATOR_PLAN.md` 覆盖。后续应先完成统一引擎接入，再
让 RNG Probe 和经济模拟器共同调用同一份 `resolve_throw()`。

## 2. 不可变架构决定

最终只有一个持有并推进玩家状态的主模拟器：

```text
FishEconomySimulator
├─ PlayerState
├─ SimulationCheckpoint
├─ SimulationClock
├─ PlayerPolicy
├─ resolve_throw()
└─ economy state transitions

FishRngProbe
└─ 重复调用同一个 resolve_throw()，只做统计验证
```

必须遵守：

1. 单次炸鱼规则只有一份实现。
2. `FishEconomySimulator` 是唯一推进 `PlayerState` 的对象。
3. 策略只能选择命令，不能直接修改存档字段。
4. RNG Probe 不拥有经济状态，也不能复制一套奖励规则。
5. 静态配置、玩家事实、推导值、策略和报告严格分离。
6. Fish 机制可以专门实现，但项目发现、运行登记、参数覆盖、产物、
   compare/scan/gate/report 必须复用 IGESS。
7. 正式 Fish 运行最终必须进入 `WorkflowService` 和 `RunRegistry`。

## 3. 已完成：玩家存档与 checkpoint

实现依据按优先级排列：

1. `E:\fish-oasis\gdd\03-存档结构设计.md`
2. `E:\fish-oasis\proj\Script\Domain\Player\PlayerArchiveSchema.lua`
3. `E:\fish-oasis\proj\Script\Domain\Player\BigNumberSaveAdapter.lua`
4. `projects/fish-rng/FISH_ECONOMY_SIMULATOR_PLAN.md`

### 3.1 实现文件

| 文件 | 当前职责 |
| --- | --- |
| `src/igess/checkpoint.py` | 引擎无关的 `SimulationCheckpoint`、规范 JSON、边界限制、digest/engine 校验和原子写入 |
| `src/igess/fish_state.py` | `PlayerState`、BigNumber DTO、业务校验、真实存档信封和 Fish checkpoint codec |
| `tests/test_checkpoint.py` | checkpoint 外壳、损坏 JSON、digest、深拷贝和原子写入测试 |
| `tests/test_fish_state.py` | 新档、完整档、引用、配置 ID、大数、规范化和 Fish checkpoint 测试 |
| `projects/fish-rng/PLAYER_STATE_MODEL.md` | 当前模型边界、正式 Schema 口径和最小使用方式 |

### 3.2 PlayerState v1

`PlayerState` 与正式游戏 `ProjectSaveCodec` 信封中的 `data` 一一对应：

```text
meta
production
wallet
torpedo
barbell
fishHall
fish
trashMan
rebirth
collection
automation
statistics
```

关键口径：

- Python 内部属性使用 `snake_case`，序列化字段使用正式 Lua Schema 的
  `camelCase`。
- 业务版本只放在真实存档信封的 `version`，不在 `data` 内重复保存
  `schemaVersion`。
- 金钱、材料和力量保存为四位有效数字
  `{sign, coeff, exp}` DTO。
- 鱼必须按实例保存，包含配置 ID、变异、等级、整数克重量和 `hallSlot`。
- `hallSlot` 是鱼位置的唯一事实源；不另存背包列表或部署引用。
- 废料按 `trashId` 聚合，保存当前处理目标和处理进度。
- 长期统计和自动玩法永久解锁属于玩家事实。

上述存档字段清单不等于 IGESS 的模拟范围。图鉴及其查看/领奖字段属于
非数值子系统，只为存档兼容保留；数值模拟不得读取、修改、发事件或建立
验收目标。

明确不保存：

- FishLuck、TrashLuck、CPS、容量、处理速度等推导值。
- 正在飞行的鱼雷、未落水结果、轨迹、特效、UI 和运行时缓存。
- 玩家策略、累计模拟报告和 RNG 内部对象。
- `model_digest`、模拟时间、根随机种子和下一个投掷 ID。

最后一组属于 `SimulationCheckpoint`。

### 3.3 SimulationCheckpoint v1

checkpoint 外壳包含：

```text
schema_version
engine_id
model_digest
scenario_id
profile_id
simulated_time_seconds
root_random_seed
next_throw_id
event_counters
engine_state
```

Fish checkpoint 的 `engine_state` 就是正式 `PlayerState` 数据，不维护
第二套 Fish 状态。

已经实现：

- `engine_id == "fish"` 校验。
- `sha256:<64 lowercase hex>` 格式和预期 `model_digest` 一致性校验。
- 稳定、排序、带结尾换行的 JSON 输出。
- 重复 JSON key、未知字段、浮点/非 plain engine state 拒绝。
- JSON 深度、工作单元和文件大小上限。
- 同目录临时文件 + `os.replace` 原子写入。
- checkpoint 深拷贝。
- `FishCheckpointCodec.new/dumps/loads/read/write/decode_state`。

`next_throw_id` 默认从 `statistics.totalThrows` 初始化，但两者不是长期
强制相等的不变量：前者表示当前模拟 RNG 位置，后者是业务生命周期统计。

### 3.4 当前校验保证

读取玩家状态时会拒绝：

- 非规范 BigNumber DTO 和负资产。
- 未拥有却被选择的鱼雷或杠铃。
- 重复配置 ID、鱼实例 ID、鱼厅栏位和废料库存 ID。
- 超出当前鱼厅容量的栏位。
- 不大于现有实例 ID 的 `nextInstanceId`。
- 当前境界高于历史最高境界。
- 激活突破但没有目标境界。
- 已查看但未解锁的图鉴项。
- 未解锁却启用的自动炸鱼。
- 不存在的鱼、变异、鱼雷、杠铃、境界、废料、升级和奖励 ID。
- 非法未来服务端时间戳。
- 当前版本的未知字段或缺失字段。

当前版本存档严格读取，不做静默修复。
`normalize_player_state()` 只供新档和显式迁移使用。

### 3.5 仍未完成的状态层工作

以下内容不要误报为已经完成：

- 两类重生的显式重置/保留状态迁移。
- 钱包消费、鱼领取/出售/上阵、废料入库等领域命令。
- `meta.revision` 的事务提交协调器。
- 连续运行与 checkpoint 分段恢复等价测试；当前只有 codec round trip。
- 正式配置表到 `id_exists` 和 `fish_hall_capacity` 校验器的适配。
- checkpoint 在 `WorkflowService`、run manifest 和 RunRegistry 中的登记。

## 4. 已完成：RNG 一期基线

现有 `src/igess/fish_rng.py` 仍是概率验证工具，不是最终主模拟器。

已验证：

- 13 个力量/Luck 区间配置和边界。
- BonusChain 外层互斥结果。
- 变异条件池和权重。
- Bonus、变异、鱼和废料四条随机流。
- RollPower 门槛选择。
- 固定 seed 的确定性产物。

当前仍使用近似链路：

```text
strength
-> 对数区间进度
-> smoothstep
-> startLuck/endLuck 插值
-> RegularLuckMultiplier
-> FishLuck
```

该链路后来被确认为正式结算语义：鱼雷轨迹由最终落点反推，仅属于表现，
不参与经济侧 BaseFishLuck 计算。

### 4.1 百万次示例基线

场景：`gdd_example_baseline`

```text
投掷次数              1,000,000
输入力量              100
当前近似 FishLuck     5.92652752
TrashLuck             20
```

| 指标 | 实测 | 理论 |
| --- | ---: | ---: |
| 第一层无 Bonus | 73.5947% | 73.6% |
| 第一层进入变异 | 16.3947% | 16.4% |
| 第一层 `Luck ×2` | 10.0106% | 10.0% |
| 整次投掷任意变异 | 18.2185% | 18.2204% |
| 整次投掷至少一次 `Luck ×2` | 11.6652% | 11.64% |
| `E[FinalFishLuck / FishLuck]` | 1.150646 | 1.149728 |

独立性：

```text
log RollPower Pearson     0.00084637
奖励等级 Pearson          0.00197749
```

这些结果只验证 GDD 示例池算法，不能作为正式鱼或废料概率结论。

## 5. 验证状态

2026-07-20 已执行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

结果：

```text
1191 passed, 6 skipped, 7 deselected
```

新增存档/checkpoint 定向测试：

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests\test_checkpoint.py tests\test_fish_state.py -q
```

结果：

```text
39 passed
```

正式 Lua Schema 对拍：

```powershell
lua E:\fish-oasis\tests\player_archive_schema_test.lua
```

结果：

```text
player_archive_schema_test passed
```

此外，`python -m py_compile` 和 `git diff --check` 均通过。

## 6. 正式数据阻塞

`E:\fish-oasis\gdd\data` 当前可用情况：

| 表 | 状态 | 影响 |
| --- | --- | --- |
| `tbfishrandompool.json` | 13 行完整 | 可用于力量阶段和 Luck 区间 |
| `tbbonusfirstlayer.json` | 完整 | 可替换示例 Bonus 配置 |
| `tbmutation.json` | Normal + 9 个变异 | 权重和收入倍率可接入 |
| `tbfish.json` | 121 条鱼 | 缺正式 `FishDenominator` 和区域归属 |
| `tbtorpedo.json` | 空 | 无法得到正式 TrashLuck |
| `tbtrashrandompool.json` | 空 | 无法得到正式废料稀有度 |
| `tbtrash.json` | 空 | 无法结算正式废料物品和材料 |
| `tbfishhallupgrade.json` | 空 | 无法得到正式鱼厅容量/成本 |
| `tbtrashmanrealm.json` | 空 | 无法得到正式加工和修炼参数 |
| `tbtrashmanrebirth.json` | 空 | 无法得到正式转世倍率 |

处理原则：

- 引擎、状态、checkpoint、事件和策略接口不等待正式表。
- 被空表阻塞的机制使用显式标记为 `fixture` 的最小配置测试。
- 不根据鱼收入反推稀有度门槛。
- fixture 结果不能作为生产平衡结论。
- 正式数据最终必须通过 IGESS Datas/Luban 来源和 model digest 管线接入。

## 7. 推荐的下一步

下一步优先完成首个里程碑中尚未实现的 Phase 0，而不是继续扩展独立
`fish_rng.py`。

### 7.1 建议下一任务：IGESS 领域引擎接入

目标：

```text
WorkflowService
-> engine_id dispatch
-> FishEngineAdapter
-> FishEconomySimulator smoke
-> standard SimulationResult
-> OutputWriter / RunRegistry
```

最小工作：

1. 定义引擎适配协议，覆盖加载、校验、构建、场景运行、参数覆盖、
   标准指标提取和 checkpoint engine state codec。
2. 用默认适配器包装现有通用 `Simulator`，保证现有行为和产物不退化。
3. 建立 `FishEngineAdapter` 和 `FishEconomySimulator` 空壳。
4. 让一个最小 Fish smoke 通过 `WorkflowService` 运行。
5. manifest 和 RunRegistry 记录 `engine_id`、`model_digest`、策略和
   override。
6. 让一个 Fish fixture 字段能走统一 `table.row.field` 参数覆盖。

验收：

- 全仓现有测试继续通过。
- 通用引擎基线产物不变。
- Fish smoke 有标准 timeline/events/analysis/manifest。
- Fish smoke 能被 report/compare 读取。
- checkpoint 可作为 Fish smoke 的输入和输出。

### 7.2 Phase 0 之后

按以下顺序推进：

1. 定义稳定领域键 RNG，并把现有 Bonus、变异、鱼和废料抽成纯
   `resolve_throw()`。
2. 实现力量到 BaseFishLuck 的直接插值纯函数，并把
   `strengthUpperBound` 解释为当前区域的包含性右端点。
3. 让 `FishRngProbe` 改为重复调用正式 `resolve_throw()`。
4. 建立最小事件循环，完成连续运行与 checkpoint 分段恢复等价测试。
5. 再依次接鱼厅/金钱和废料/材料两条经济闭环。

## 8. 物理与随机规则来源

后续 `resolve_throw()` 使用以下来源优先级：

1. `E:\fish-oasis\gdd\05-a-力量与Luck计算流程.md`
2. `E:\fish-oasis\gdd\09-鱼雷飞行公式.md`
3. `E:\fish-oasis\gdd\05-核心随机算法.md`
4. `E:\fish-oasis\gdd\data\*.json`
5. `E:\fish-oasis\curve-simulator\simulator.js`

已知口径冲突：

旧 `05-核心随机算法.md` 曾写：

```text
FishRollPower -> 横向距离
```

后来确认的正式经济结算链路是：

```text
力量
-> BaseFishLuck
-> BonusChain
-> FinalFishLuck
-> FishRollPower
-> 鱼奖励
```

`strengthUpperBound` 是当前区域的包含性右端点；轨迹由最终落点反推，
不进入经济结算链路。

## 9. 接手时不要误做

- 不要恢复旧 `projects/fish` 样例，继续使用 `projects/fish-rng`。
- 不要再创建第二套玩家状态或 Fish 专用运行登记管线。
- 不要让 Fish RNG Probe 直接修改 `PlayerState`。
- 不要把策略判断写进存档模型或奖励规则。
- 不要把当前 7 条示例鱼和 6 档废料当作正式表。
- 不要根据 `baseMoneyPerSecond` 反推 `FishDenominator`。
- 不要保存 FishLuck、CPS、容量等推导缓存。
- 不要保存 pending throw result；投掷落水后再原子写入奖励事实。
- 不要用十进制字符串替代正式 `{sign, coeff, exp}` 存档 DTO。
- 不要放宽 `model_digest` 校验后静默继续旧 checkpoint。
- 不要用 `random.Random.getstate()` 保存 RNG 位置。
- 不要在百万次循环中重复计算完全相同的确定性轨迹。
- 不要让日志、保存、报告或新增统计字段消耗随机数。
- 不要在正式表为空时把 fixture 节奏包装成生产结论。

## 10. 常用命令

运行 RNG 示例：

```powershell
.\.venv\Scripts\python.exe -m igess.cli fish-rng-run `
  --config projects\fish-rng\gdd-example.json `
  --out projects\fish-rng\runs\gdd-example
```

运行存档/checkpoint 测试：

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests\test_checkpoint.py tests\test_fish_state.py -q
```

运行 RNG 回归：

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests\test_fish_rng.py tests\test_cli_help.py -q
```

运行全仓回归：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## 11. 完成口径

当前完成的是“可信存档基础”，不是完整经济模拟。

下一里程碑完成的最低标准：

1. Fish 通过 IGESS 标准引擎派发运行。
2. smoke 进入 RunRegistry，并有标准 manifest/timeline/events/analysis。
3. 参数覆盖走统一路径。
4. checkpoint 能作为正式运行输入和输出。
5. 现有通用 IGESS 与 RNG 基线不退化。

完整完成定义以 `FISH_ECONOMY_SIMULATOR_PLAN.md` 第 13 节为准。
