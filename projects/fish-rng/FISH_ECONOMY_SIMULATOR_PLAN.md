# FishEconomySimulator 实施计划

> **状态说明：** 本文档保留详细架构、阶段目标与验收背景，文中的勾选项仅是历史快照，不再更新。当前唯一进度源是 [`../fish/RoadMap.md`](../fish/RoadMap.md)。

更新时间：2026-07-20  
当前工作目录：`projects/fish-rng`

本文覆盖 `HANDOFF.md` 中“先完成独立 RNG 模拟器、最后再接经济层”的旧实施顺序。`HANDOFF.md` 中已经完成的 RNG 基线、GDD 口径和数据缺口仍然有效。

## 1. 架构决定

最终只有一个面向完整游戏数值模拟的主模拟器：

```text
FishEconomySimulator
```

现有 `FishRngSimulator` 只是一项概率验证工具。它不拥有独立的游戏规则，也不形成第二套模拟架构。最终应由它反复调用与经济模拟器完全相同的单次炸鱼结算函数，完成百万次概率、独立性和分布验证。

统一关系：

```text
FishEconomySimulator
├─ PlayerState / SimulationCheckpoint
├─ SimulationClock
├─ PlayerPolicy
├─ resolve_throw()
│  ├─ flight
│  ├─ BonusChain
│  ├─ mutation
│  ├─ fish roll
│  └─ trash roll
├─ economy transitions
│  ├─ claim / sell / deploy fish
│  ├─ passive income
│  ├─ trash processing
│  ├─ purchases and upgrades
│  └─ rebirth
└─ statistics and reports

FishRngProbe
└─ 重复调用 resolve_throw()，只做统计验证
```

核心约束：

1. 单次炸鱼规则只有一份实现。
2. `FishEconomySimulator` 是唯一持有和推进玩家状态的对象。
3. RNG 工具不能直接修改经济状态。
4. 玩家策略和玩家存档分离，同一存档可以对比多种策略。
5. 静态配置、玩家状态、推导值和统计报告严格分离。
6. Fish 可以专门实现游戏特有机制，但不能另建一套运行、调参、产物和报告框架。
7. Fish 正式模拟必须通过 IGESS 的项目、运行和分析工作流执行。

### 1.1 IGESS 与 Fish 的职责边界

| 层级 | 负责内容 |
| --- | --- |
| IGESS 核心 | 项目发现、YAML/Luban 来源、模型摘要、`SimNumber`、运行登记、参数覆盖、scan、compare、gate、report、标准 manifest |
| IGESS 扩展协议 | 引擎选择、模型加载/校验/构建、场景运行、checkpoint 外壳、标准时间线/事件/KPI 输出 |
| Fish 领域实现 | 玩家领域状态、鱼实例、鱼厅、垃圾佬、加工队列、两类重生、Fish 策略 |
| Fish 单次结算 | 轨迹、距离/Luck、BonusChain、变异、鱼随机、废料随机 |
| Fish 诊断工具 | 百万次 RNG Probe、物理 golden case、概率理论对拍 |

原则是“机制可以特有，基础设施必须共享”。Fish 不要求硬塞进现有通用 `generators/upgrades/prestige` 数据结构；如果现有 `SimulationState` 无法表达实例鱼和异步队列，应通过 IGESS 领域扩展载荷表达，而不是把同类运行设施复制一遍。

### 1.2 IGESS 引擎接入点

IGESS 需要新增一个最小的领域引擎适配协议。名称可在实现时确定，职责必须覆盖：

```text
engine_id
load_project(config, tables)
validate(raw_model)
build(raw_model)
run_scenario(model, scenario, checkpoint?)
apply_parameter_override(raw_model, table.row.field, value)
extract_standard_metrics(result)
encode/decode checkpoint engine_state
```

运行关系：

```text
IGESS CLI / WorkflowService
→ 根据 economy.yaml 的 engine_id 选择适配器
→ FishEngineAdapter
→ FishEconomySimulator
→ IGESS 标准 SimulationResult / run artifacts
→ report / compare / scan / gate / advice
```

现有通用 `Simulator` 继续作为 IGESS 默认引擎；`FishEconomySimulator` 是 Fish 项目的唯一领域引擎。两者不需要继承同一个具体状态类，但必须遵守相同的运行与产物协议。

### 1.3 Fish 正式项目形态

Fish 最终使用 IGESS 标准项目来源：

```text
economy.yaml
Datas/
luban_exports/
changes/
runs/
```

`economy.yaml` 保存引擎 ID、场景、策略参数、回归门槛和非表格规则；正式可调数值来自 Luban 表或规范化表适配器。当前 `gdd-example.json` 只保留为 fixture/兼容输入，不能成为绕过 IGESS model digest、参数覆盖和来源追踪的第二套正式来源。

当前继续在 `projects/fish-rng` 内实施，不恢复旧 `projects/fish` 样例；是否在迁移完成后重命名目录单独决定。

## 2. 模拟器的输入与输出

标准输入：

```text
IGESS economy.yaml
+ Luban/规范化配置表快照
+ 初始存档或已有 checkpoint
+ 玩家策略
+ 模拟终止条件
```

标准输出：

```text
最终 checkpoint
+ IGESS 标准 timeline
+ IGESS 标准 events
+ IGESS analysis/KPI
+ run_manifest（含 engine_id、model_digest、策略和 override）
+ Fish 可选补充诊断产物
```

正式运行应进入 IGESS `RunRegistry`，并能被现有 Dashboard 和后续分析命令发现。Fish 补充产物必须登记在 manifest 中，不能替代标准产物。

模拟终止条件至少支持：

- 模拟到指定游戏时间。
- 模拟指定次数炸鱼。
- 达到指定力量、鱼雷、境界或重生阶段。
- 达到指定金钱或材料。

## 3. 四类数据的边界

| 类别 | 内容 | 是否写入存档 |
| --- | --- | --- |
| 静态配置 | 鱼表、鱼雷表、价格、公式、物理常量、随机池 | 否，只记录数据版本和哈希 |
| 玩家状态 | 资源、资产、升级、进度、计时任务、永久成长 | 是 |
| 推导值 | FishLuck、TrashLuck、每秒收入、当前升级价格、处理速度 | 否，使用时计算 |
| 策略与报告 | 购买优先级、替换鱼规则、P50/P90、累计产出 | 不写入玩家状态 |

只有会影响未来模拟结果的事实才进入 `PlayerState`。纯 UI 状态和可以从其他字段无歧义推导的缓存值不进入首版存档。

## 4. 状态模型 v1

### 4.1 checkpoint 元信息和模拟位置

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
```

要求：

- 这些字段属于 `SimulationCheckpoint`，不属于 `PlayerState`。
- `schema_version` 只描述 checkpoint 外壳版本；业务存档版本沿用正式信封的 `version`。
- `engine_id` 必须为 `fish`，由 IGESS 引擎注册表负责派发。
- `model_digest` 复用 IGESS 对 `economy.yaml + Datas/Luban exports` 的来源摘要。
- `next_throw_id` 保证中断恢复后不会重复或跳过一次炸鱼。
- `event_counters` 只保存确实需要独立序列的非投掷随机领域。

### 4.2 业务元信息、结算锚点和基础资源

`PlayerState` 与正式游戏 `ProjectSaveCodec` 信封中的 `data` 一一对应。
业务结构版本只使用信封的 `version`，不在 `data` 内重复保存。

```text
meta
├─ createdAt
└─ revision

production
└─ lastSettledAt

wallet
├─ money
├─ material
└─ strength
```

金钱、材料和力量使用正式游戏的四位有效数字 DTO：

```json
{"sign": 1, "coeff": 1234, "exp": 8}
```

零值固定为 `{"sign": 0, "coeff": 0, "exp": 0}`。模拟运行时可以转为
`SimNumber` 计算，但 checkpoint 中必须写回规范 DTO，不能保存二进制
浮点数、运行时对象或另一套十进制字符串格式。

所有消费操作必须满足：

```text
消费前余额 >= 成本
消费后余额 >= 0
```

### 4.3 炸鱼能力

```text
torpedo
├─ selectedId
└─ ownedIds[]

barbell
├─ equippedId
└─ owned[]
   ├─ barbellId
   └─ count
```

力量已经属于 `wallet.strength`。鱼雷按唯一配置 ID 保存拥有集合；杠铃按
配置 ID 聚合数量。如果后续出现随机词条、强化等级或耐久度，再通过存档
迁移升级为实例对象。

以下值由状态和配置推导，不保存：

```text
FishLuck
TrashLuck
杠铃力量产出速度
```

### 4.4 鱼背包和摸鱼厅

鱼必须按实例保存：

```text
FishInstance
├─ instance_id
├─ fish_id
├─ mutation_id
├─ level
├─ weight_gram
└─ hall_slot
```

摸鱼厅状态：

```text
fishHall.upgradeLevel
```

规则：

1. `instance_id` 在整个存档生命周期内唯一。
2. `hall_slot == 0` 表示背包，正数表示对应摸鱼厅栏位；这是鱼位置的唯一事实来源。
3. 不另存背包列表、上阵引用或已部署实例 ID，避免重复事实和悬空引用。
4. 一个栏位最多一条鱼，栏位不能超过配置推导出的当前容量。
5. `nextInstanceId` 必须大于所有已有实例 ID。
6. 重量保存整数克，不保存浮点公斤。
7. 鱼厅每秒收入根据上阵实例、鱼表、变异倍率和永久倍率实时计算。

### 4.5 废料和加工

废料如果没有实例级随机属性，使用按 `trash_id` 聚合的数量，不为每份废料创建对象。

正式 v1 Schema 保存一个当前处理目标和按废料 ID 聚合的库存：

```text
trashMan.processing
├─ activeTrashId
├─ activeProgressSeconds
└─ stocks[]
   ├─ trashId
   └─ count
```

不为每份废料创建实例，也不在首版存档中引入第二套任务队列结构。处理速度
仍由当前境界、升级和配置推导；进度结算必须在改变产出源前先推进到当前
时间。

Phase 5 v1 采用固定基础工作量模型：

```text
单份废料基础工作量 = baseDecomposeSeconds
真实秒工作速度 = decomposeSpeedMultiplier
已产材料 =
  baseMaterialPerSecond
  × 实际消费的基础工作量
  × trashToTreasureOutputMultiplier
```

因此境界加速只缩短处理同一份废料所需的真实时间，不会减少它的基础总材料。
活动目标仍计入聚合库存，完成时才扣除；没有显式目标时按 `trashId` 升序选择。
结算按废料种类批量跨越完整份数，不逐秒或逐份循环。PlayerState v1 的
`activeProgressSeconds` 保存完整基础工作秒，小数余量放在 checkpoint 的
`engine_runtime_state`，保证境界速度为小数时仍可精确恢复。

### 4.6 垃圾佬状态

```text
trashMan
├─ realmId
├─ highestRealmId
├─ upgrades[]
│  ├─ upgradeId
│  └─ level
├─ trainingProgressSeconds
├─ breakthrough
│  ├─ active
│  ├─ targetRealmId
│  └─ progressSeconds
└─ processing
```

在线自动修炼、闭关突破和废料加工是不同进度，不应共用一个计时字段。修炼和闭关期间仍然允许材料加工。

### 4.7 永久成长

```text
rebirth
├─ strengthCompletedCount
└─ trashManCompletedCount
```

永久产出倍率由重生次数和配置推导，不重复保存。力量重生默认只重置
`wallet.strength`；垃圾佬转世默认只重置当前境界及本轮境界进度。具体
重置集合必须由显式状态迁移实现，不允许用“创建新玩家状态再补回部分
字段”的方式实现。

### 4.8 自动玩法、长期统计和透传字段

```text
collection (opaque archive passthrough; not modeled)

automation
├─ autoThrowUnlocked
└─ autoThrowEnabled

statistics
├─ totalThrows
├─ totalFishCaught
└─ maxDistanceCm
```

`collection` 仅为正式存档兼容字段。图鉴、查看状态和奖励领取不影响数值
体验，明确排除在 IGESS 模拟之外；这些字段只做结构校验和原样透传，任何
模拟事件、策略或报表都不得读取或修改它们。

正在飞行的鱼雷、尚未落水的投掷、轨迹、特效和运行时缓存不保存。投掷
完成服务端结算后，只有鱼实例、废料和数值统计在同一个状态迁移中写入。

## 5. SimulationCheckpoint

checkpoint 是可以完整恢复模拟的 JSON 文档：

```json
{
  "schema_version": 1,
  "engine_id": "fish",
  "model_digest": "sha256:...",
  "scenario_id": "day_1_progression",
  "profile_id": "max_income",
  "simulated_time_seconds": 86400,
  "root_random_seed": 20260720,
  "next_throw_id": 2881,
  "event_counters": {},
  "engine_state": {}
}
```

首版要求：

1. JSON 规范化输出，字段和集合排序稳定。
2. 读取时执行完整校验，不接受悬空鱼实例引用、负资源或非法配置 ID。
3. checkpoint 可以在领域事件边界保存。
4. 连续运行与“运行一半、保存、加载、继续运行”得到相同最终状态和后续事件。
5. `model_digest` 不一致时默认拒绝继续；显式迁移模式另行处理。
6. 不直接保存 Python `random.Random.getstate()`。
7. checkpoint 外壳和安全读写由 IGESS 提供；`engine_state` 的 schema、校验和迁移由 Fish 领域实现。

## 6. 可复现 RNG

每个随机值使用稳定的领域键生成：

```text
root seed
+ throw_id
+ stream name
+ layer/index
```

示例：

```text
(seed, throw_id, "bonus", layer)
(seed, throw_id, "mutation", 0)
(seed, throw_id, "fish", 0)
(seed, throw_id, "trash_rarity", 0)
(seed, throw_id, "trash_item", 0)
```

优点：

- BonusChain 层数变化不会挪动鱼和废料的随机序列。
- 新增统计字段不会改变开奖结果。
- checkpoint 只需要保存 `next_throw_id`，不依赖解释器内部 RNG 状态。
- 单次投掷可以独立重放和定位问题。

必须保留现有四流独立性，并扩展废料稀有度和废料物品两个不同领域键。

## 7. 领域事件和状态迁移

首版领域事件：

```text
TimeAdvanced
ThrowStarted
ThrowResolved
FishClaimed
FishSold
FishDeployed
FishRemovedFromHall
TrashQueued
TrashProcessed
TorpedoPurchased
FishHallUpgraded
BarbellCrafted
BarbellActivated
TrashmanBreakthroughFunded
TrashmanRealmAdvanced
StrengthRebirthed
TrashmanRebirthed
BuffStarted
BuffExpired
```

每个状态迁移采用同一形式：

```text
旧 PlayerState
+ 领域命令或时间事件
+ 静态配置
→ 新 PlayerState
+ 领域事件
```

状态迁移必须集中实现并测试。策略只能选择命令，不能直接修改状态字段。

## 8. PlayerPolicy

策略不是存档的一部分。Fish 策略由领域实现，但通过 IGESS 的 profile/scenario 配置选择，策略 ID 和参数必须进入 manifest。鱼厅编队不再作为策略分支：模拟始终按当前单鱼每秒收益降序取容量内前 `N` 条上阵，同收益按 `instanceId` 升序决胜。首版策略接口只需决定：

1. 金钱优先购买鱼雷还是资助垃圾佬突破。
2. 材料优先升级鱼厅还是合成杠铃。
3. 使用哪种鱼雷和杠铃。
4. 何时力量重生。
5. 何时垃圾佬转世。

首批基准策略：

```text
progression
    优先购买能解锁下一阶段的升级

rebirth_conservative
    只有预计回本时间低于阈值时重生
```

所有报告必须记录所用策略 ID 和参数。

## 9. 分阶段实施

### Phase 0：建立 IGESS 领域引擎接入点

目标：Fish 机制可以专门实现，但从第一天起就通过 IGESS 标准工作流运行。

工作：

1. 在 IGESS 核心定义最小领域引擎适配协议和 `engine_id` 派发。
2. 让默认通用 `Simulator` 通过默认适配器保持现有行为。
3. 建立 `FishEngineAdapter` 和 `FishEconomySimulator` 空壳。
4. 定义标准结果中的通用资源、时间线、事件、KPI 和领域扩展字段。
5. 让 `WorkflowService`、CLI、RunRegistry 和 OutputWriter 能运行并登记 Fish smoke。
6. 让参数覆盖不再硬编码为通用模型的 `getattr(raw, table)`，而是经引擎适配器定位 `table.row.field`。
7. 定义 `ThrowInput`、`ThrowOutcome` 和纯函数 `resolve_throw()` 的接口。
8. 保留 `fish-rng-run` 作为兼容诊断入口，正式经济运行走 IGESS 标准命令。

验收：

- 现有 IGESS 通用项目测试和产物逐字节基线不退化。
- 一个最小 Fish smoke 可以通过 IGESS 标准项目命令运行。
- smoke 在 `RunRegistry` 中有 `engine_id`、`model_digest` 和标准 manifest。
- `report` 能打开 Fish smoke；`compare` 能比较两个 Fish smoke。
- 至少一个 Fish fixture 表字段可以通过通用参数覆盖路径运行两个变体。
- 接口明确规定单次结算不读取或修改 `PlayerState`。
- 模块依赖不允许经济规则反向依赖概率报告。

### Phase 1：PlayerState 和 checkpoint

目标：建立可以验证、保存、加载和复制的玩家状态。

工作：

1. 在 IGESS 核心实现通用 checkpoint 外壳、规范化 JSON 和 `model_digest` 校验。
2. 在 Fish 领域实现 `PlayerState`、鱼实例、加工任务和计时状态。
3. 由 `FishEngineAdapter` 实现 `engine_state` codec、schema 校验和迁移入口。
4. 所有经济大数使用正式游戏的规范 `{sign, coeff, exp}` DTO。
5. 实现稳定实例 ID 和 `next_throw_id`。

验收：

- 新存档可以稳定地保存、加载并逐字节重写。
- 非法引用、负余额、重复实例 ID 和超容量鱼厅会被拒绝。
- `copy()` 后修改副本不会影响原状态。
- checkpoint 中不出现 FishLuck、CPS 等推导缓存。
- checkpoint 可以作为 IGESS 正式运行的输入和输出，并在 manifest 中登记。

### Phase 2：单次炸鱼正式结算

目标：形成经济模拟器可以调用的权威炸鱼结算函数。

工作：

1. 完成力量到 BaseFishLuck 的直接插值纯函数；`strengthUpperBound` 按
   当前区域的包含性右端点解释。
2. 接入 BonusChain、变异、鱼随机和废料随机。
3. 输出完整 `ThrowOutcome`，但不直接放入玩家背包。
4. 将 RNG 改为基于稳定领域键的可重放实现。

验收：

- 给定配置、状态快照和 `throw_id`，结果完全确定。
- 修改鱼随机领域不会改变力量/Luck 映射、Bonus 或废料结果。
- 力量端点、Bonus 和独立性现有回归继续通过。
- 一次有效投掷严格产生一条鱼和一份废料。

### Phase 3：时间引擎和模拟循环

目标：让 `FishEconomySimulator` 可以从 checkpoint 推进到指定时间。

工作：

1. 扩展 IGESS `TimeEngine` 的事件跳跃契约，不在 Fish 内复制通用时钟。
2. 由 Fish 提供下一次投掷、加工、修炼、突破和 buff 过期等领域事件时间。
3. 定义同一时间点多个事件的稳定处理顺序。
4. 支持主动炸鱼和慢速自动炸鱼。
5. 支持仅存在于一次运行时事件内的投掷结果、原子领取结算和策略决策，不把 pending result 写入存档。
6. 通过 IGESS 通用 `BehaviorScheduler` 调度带权重、持续时长和目标的离散
   玩家行为；每个玩家画像独立配置，行为选择、时长和目标使用独立稳定随机域。
7. checkpoint 保存行为 sequence 游标及进行中的完整行为；恢复时继续原行为，
   不重新选择。无行为的旧 checkpoint 保持原 JSON 形状。

当前 Fish 加权模式已以 opt-in 方式接入 `manual_throw`、`upgrade_fish`、
`upgrade_fish_hall` 和 `idle`。鱼厅收入是与前台行为并行的后台生产，
不进入行为权重；鱼厅升级是无目标前台行为。生产 `default` 画像尚未配置
正式权重和持续时长，机制测试使用 fixture；没有 `behavior_weights` 的画像
仍走旧主动投掷循环。

验收：

- 现有通用引擎的 tick/analytic 测试继续通过。
- 连续运行 24 小时与两个连续 12 小时 checkpoint 运行结果一致。
- tick 模式和事件跳跃模式在同一 fixture 下结果一致。
- 保存和报告动作不会消耗随机数或改变未来结果。

### Phase 4：鱼、摸鱼厅和金钱闭环

目标：先形成鱼线最小可运行经济循环。

链路：

```text
炸鱼
→ 鱼实例
→ 固定最高收益自动上阵
→ 摸鱼厅随时间产出金钱
→ 金钱消费
```

工作：

1. 实现鱼背包和鱼厅栏位；出售等待正式价格口径。
2. 接入 `baseMoneyPerSecond` 和变异 `incomeMultiplier`。
3. 实现鱼厅容量和收入计算。
4. 实现固定 `max_income` 自动编队，不保留手动/`collector` 分支。

当前进度：上述基础上阵、容量、收入和 trace 已完成。鱼等级从 `1` 开始、
最高 `100`；等级 `n` 的产出为
`B × 1.25^(n-1) × mutationIncomeMultiplier`，从 `n` 升到 `n+1` 的价格
为 `B × 1.5^(n-1)` 且不乘变异倍率，统一使用 BigNumber。升级原子扣款、
加级和固定最高收益阵容重排已完成。加权行为适配器提供显式 opt-in 的
`random_affordable` 策略，只从当前余额可支付且未满 100 级的鱼中选择；
生产玩家权重、行为时长和该目标策略尚未配置，出售仍等待正式口径。

验收：

- 替换鱼不会复制或丢失实例。
- 固定上阵阵容的累计金钱可用解析公式对拍。
- 收入倍率乘区有明确公式 trace。

### Phase 5：废料、垃圾佬和材料闭环

目标：完成废料到材料的异步生产线。

链路：

```text
炸鱼
→ 废料库存
→ 垃圾佬加工队列
→ 材料
```

工作：

1. 实现废料聚合库存和批量加工队列。
2. 实现境界、拾荒效率、材料倍率和加工工作量。
3. 实现在线修炼、瓶颈和资助突破。
4. 保证修炼或闭关期间加工不停。

验收：

- 废料数量守恒：获得量 = 库存量 + 已加工量。
- 速度变化后剩余工作量正确，不重复结算。
- 固定队列的材料产出可用手算样例对拍。
- 在线修炼与离线状态的边界符合 GDD。

### Phase 6：升级和交叉养成

目标：连通金钱、材料、鱼雷、摸鱼厅、杠铃和力量。

链路：

```text
金钱 → 鱼雷 / 垃圾佬突破
材料 → 鱼厅 / 杠铃
杠铃 → 力量
力量 → FishLuck
鱼雷 → TrashLuck
```

工作：

1. 鱼雷购买、拥有和选用。
2. 鱼厅升级。
3. 杠铃合成、选用和力量挂机产出。
4. 购买与合成策略。

当前鱼厅升级首片已完成：`upgradeLevel` 当前行的 `upgradePrice` 用于进入
下一行，最终零值行是不可购买的满级哨兵。命令先结算后台生产，再使用
BigNumber 原子扣除材料、扩容并按 IGESS 的 `fixed_max_income` 模拟策略重排；
`upgrade_fish_hall` 行为支持中途 checkpoint 恢复且不会提前扣款。
5. 关键升级等待时间和回本时间报告。

验收：

- 所有升级严格消费对应资源。
- 切换鱼雷只影响废料线。
- 力量变化只通过正式距离链路影响鱼线。
- 固定策略可以从新存档自动推进多个经济阶段。

### Phase 7：重生和永久成长

目标：实现两条重生线和明确的局部重置。

工作：

1. 力量重生及摸鱼厅永久倍率。
2. 垃圾佬转世及材料永久倍率。
3. 历史最高境界和转世后在线追赶。
4. 重生策略和回本分析。

验收：

- 力量重生只重置配置规定的力量状态。
- 垃圾佬转世只重置当前境界相关状态。
- 金钱、材料、鱼、废料、鱼厅、鱼雷等保留项不丢失。
- 重生前后收入和材料倍率变化可追踪。

### Phase 8：离线、临时效果和长期模拟

目标：覆盖真实增量游戏的在线/离线节奏。

工作：

1. 在线会话和离线区间。
2. 离线金钱与材料收益，当前暂按在线的 50% 作为待确认规则。
3. 临时 Luck、速度、金钱和材料效果。
4. buff 过期、加工完成、突破完成等同一时刻事件排序。
5. 天、周和多重生长期模拟。

验收：

- 离线计算不会重复领取。
- 跨 buff 过期点的积分与分段手算一致。
- 长时间事件跳跃结果与小 tick 基准一致。

### Phase 9：策略比较和数值报告

目标：让 Fish 模拟结果通过 IGESS 的标准数值平衡工具直接支持决策。

输出至少包括：

- 资源和能力时间线。
- 每小时鱼、废料、金钱和材料产出。
- 升级与重生事件。
- 关键阶段到达时间。
- 稀有奖励等待时间 P50/P90/P99。
- 各策略最终状态和阶段速度对比。
- 调参前后差异。
- 公式 trace 和数据来源哈希。

验收：

- 同一 checkpoint 可以分叉运行多个策略。
- 报告明确区分实测、理论和 fixture 结果。
- 所有关键结论能追踪到配置和状态迁移事件。
- `scan` 可以覆盖 Fish Luban 表中的可调字段并运行 `FishEconomySimulator`。
- `compare` 可以比较 Fish 的资源、能力、升级、重生和关键阶段 KPI。
- `gate` 可以对 Fish KPI 设置回归门槛。
- `report` 和 Dashboard 能展示 Fish 标准 KPI，并允许加载登记过的领域补充图表。
- Agent Analyst 和人工改表验证可以沿用 `model_digest`、来源行和 override 记录。

## 10. 正式数据阻塞

当前可用数据：

- `tbfishrandompool`
- `tbbonusfirstlayer`
- `tbmutation`
- `tbbarbell`
- `tbstrengthrebirth`
- `tbfish` 中的基础每秒金钱

当前关键阻塞：

- `tbfish` 缺少正式 `FishDenominator` 和区域归属。
- `tbtorpedo` 为空。
- `tbtrashrandompool` 为空。
- `tbtrash` 为空。
- `tbfishhallupgrade` 为空。
- `tbtrashmanrealm` 为空。
- `tbtrashmanrebirth` 为空。

处理原则：

1. 状态引擎、checkpoint、事件和策略接口不等待正式表。
2. 阻塞系统使用最小测试 fixture 验证机制。
3. fixture 文件和报告必须显式标注 `fixture`。
4. 不根据鱼收入反推稀有度门槛。
5. 不把 fixture 概率、升级时间和经济节奏作为正式平衡结论。
6. 正式表接入时进入 IGESS 的 Datas/Luban 来源、model digest 和来源追踪流程，不由 Fish 模拟器直接读取散落的生产 JSON。

## 11. 跨阶段不变量

所有阶段持续验证：

1. 相同 checkpoint、配置、策略和终止条件产生相同结果。
2. 连续运行等价于 checkpoint 分段运行。
3. 资源不会无来源增加，也不会消费成负数。
4. 每次有效炸鱼严格产生一条鱼和一份废料。
5. 鱼和废料随机流独立。
6. 状态引用完整，无重复实例或悬空引用。
7. 重生严格遵循显式重置和保留集合。
8. 推导值不作为玩家事实重复存储。
9. 策略只能发出命令，不能绕过状态迁移直接改存档。
10. 工具、日志和报告不能改变模拟结果。
11. 正式 Fish 运行必须进入 IGESS RunRegistry 并输出标准 manifest、timeline、events 和 analysis。
12. Fish 可调字段必须能由统一 `table.row.field` 路径覆盖并记录 override。
13. Fish 补充产物只能扩展标准产物，不能形成独立的 compare/scan/gate/report 管线。
14. 每个关键事件和结论都能追踪到 `model_digest`、配置表和来源行。

## 12. 首个实施里程碑

首个里程碑不追求完整经济闭环，先建立 IGESS 接入和可信状态基础：

```text
[ ] IGESS 领域引擎适配协议
[ ] 默认通用引擎兼容适配
[ ] FishEngineAdapter / FishEconomySimulator 空壳
[ ] Fish smoke 进入 WorkflowService 和 RunRegistry
[ ] Fish 标准 manifest/timeline/events/analysis
[ ] 一个 Fish 参数覆盖 smoke
[x] PlayerState v1
[x] IGESS SimulationCheckpoint v1 外壳
[x] Fish engine_state codec
[x] 新存档工厂
[x] JSON 保存、加载和规范化输出
[x] model_digest 校验
[x] 稳定 next_throw_id
[x] 鱼实例和鱼厅引用校验
[x] 废料聚合库存和加工任务结构
[ ] 两类重生字段及显式重置集合
[ ] 连续运行 = 分段恢复的确定性测试骨架
```

完成该里程碑后，再把现有 RNG 代码拆成 `resolve_throw()`，接入同一个 `FishEconomySimulator`。

## 13. 最终完成定义

`FishEconomySimulator` 可以称为完整的 Fish 增量经济模拟时，至少满足：

1. 可以从新存档或任意合法 checkpoint 开始运行。
2. 力量通过正式物理和距离链路决定鱼线能力。
3. 鱼雷通过正式配置决定废料线能力。
4. 鱼、摸鱼厅和金钱形成可持续循环。
5. 废料、垃圾佬和材料形成异步生产循环。
6. 金钱和材料可以驱动鱼雷、鱼厅、杠铃及垃圾佬成长。
7. 两类重生按设计重置和保留状态。
8. 在线、离线、临时效果和自动行为可以正确推进。
9. 玩家策略可替换、可比较，不与游戏规则耦合。
10. 同一单次结算逻辑同时服务经济模拟和 RNG 验证工具。
11. 模拟可中断、保存、恢复，并保持确定性。
12. 报告能回答关键资源、升级、重生和等待时间问题。
13. 正式运行通过 IGESS 项目和 WorkflowService 发起，并进入 RunRegistry。
14. Fish 数值表可以使用 IGESS 参数覆盖和 scan 批量运行。
15. Fish 关键 KPI 可以使用 IGESS compare 和 gate 做调参回归。
16. Fish 报告可以通过 IGESS report、Dashboard 和 Agent Analyst 消费。
17. 所有产物记录 engine ID、model digest、策略、override 和来源追踪。
