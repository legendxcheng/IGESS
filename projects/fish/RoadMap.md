# Fish 模拟 RoadMap

更新时间：2026-07-26
项目范围：`projects/fish` 与 Fish 领域模拟代码
当前总状态：**Fish 专用引擎已接入 IGESS；鱼厅金钱、垃圾佬材料、鱼雷、杠铃、两类重生以及垃圾佬付费新境界突破均已进入统一生产循环。默认画像每天在线 2 小时、离线 22 小时；突破行为权重 `100`、固定 `1s`，按当前境界 `moneyRequireToNextRealm` 付费，首版仅在线推进且闭关不停产。境界价格 1～59 号严格递增、60 号为零值哨兵，分解倍率为 `1 + 1.25×(ID-1)`。系统级永久进展目标首日/首周/首月为 `10 / 20 / 40`，当前结果 `9 / 23 / 36` 全部通过 gate；24h 离线上限、临时效果、30d 正式产物压缩和超月长期策略模拟仍未完成。**

## 1. 本文档是唯一进度源

本文档统一记录 Fish 的经济规则建模、RNG、玩家存档、模拟器接入、正式场景和数值分析进度。

### 数值体验模拟边界

IGESS 只关注会改变数值体验的资源、概率、时间、产出、消耗、成长曲线、
策略选择和 KPI。图鉴、已查看状态、图鉴奖励领取、表现、教程、通知等非数值
子系统明确不建模，也不得进入领域事件、策略或报表。正式存档 Schema 中为兼容
游戏而保留的无关字段仅做原样透传和结构校验，模拟过程不读取、不修改。

维护规则：

1. 只有本文档维护阶段状态、任务勾选和“下一步”。
2. 每次完成任务时同时填写证据；没有测试、运行产物或可检查代码的任务不能标记完成。
3. 模拟中的具体数值必须与游戏实际数值完全一致，`E:\fish-oasis\igess_export` 是唯一权威生产快照；正式运行读取其中的 `json\*.json` 和同次生成的 `python\schema.py`，不得用 RoadMap、文字 GDD、旧 `gdd/data`、示例、fixture 或代码默认值覆盖。
4. 具体玩法语义和计算规则到 `E:\fish-oasis\gdd` 查找；文字 GDD 或旧数据副本与 `igess_export/json/*.json` 冲突时，数值无条件以权威导出 JSON 为准，缺失字段、公式歧义和无法由数据表决定的行为再与人类确认。
5. 每次模拟必须记录实际加载的数据目录、文件清单、内容摘要和 `model_digest`，确保结果能追踪到与游戏相同的一版数值。

状态标记：

- `[x]`：完成且已有可检查证据。
- `[~]`：部分完成，尚未达到该项验收标准。
- `[ ]`：未开始或没有可验证成果。
- `[!]`：被正式数据或外部决定阻塞；可用明确标记的 fixture 继续验证机制。

## 2. 当前进度总览

| 工作线 | 状态 | 当前结论 | 证据 |
| --- | --- | --- | --- |
| 通用经济规则原型 | `[~]` | `projects/fish` 已达到 `runnable`，但只有主动活动每秒产生 2 金钱的最小 smoke，不代表正式 Fish 经济 | `economy.yaml`、`changes/`、自动 smoke run |
| RNG 一期基线 | `[x]` | BonusChain、变异、鱼与废料独立随机流已有验证基线；Probe 已复用权威 `resolve_throw()`，FishLuck 直接按力量和 `tbfishrandompool` 插值 | `src/igess/fish_throw.py`、`src/igess/fish_throw_data.py`、`tests/test_fish_throw_commands.py` |
| PlayerState v1 | `[x]` | 正式存档字段、大数 DTO、严格业务校验、新档和规范 JSON 已实现 | `src/igess/fish_state.py`、`tests/test_fish_state.py` |
| 通用 checkpoint v1 | `[x]` | checkpoint 外壳、digest/engine 校验、原子读写及可选行为运行态已实现；无行为的旧 JSON 形状不变 | `src/igess/checkpoint.py`、`tests/test_checkpoint.py` |
| Fish checkpoint codec | `[x]` | `PlayerState` 可作为 Fish `engine_state` 保存和恢复 | `FishCheckpointCodec` 及定向测试 |
| IGESS Fish 引擎接入 | `[x]` | 领域引擎协议、派发、Luban Python 强类型表、生产 smoke、标准产物、checkpoint 恢复和 compare 已接通 | `src/igess/engines.py`、`tests/test_fish_engine.py`、生产 run `20260722T052544104476Z-smoke` |
| FishEconomySimulator | `[~]` | 鱼厅金钱/垃圾佬材料按在线或离线模式统一结算；杠铃力量只由互斥前台 `exercise_barbell` 在线产出。加权行为循环支持每日在线窗口、离线跳跃、两类重生和任意分段恢复 | `src/igess/fish_production.py`、`src/igess/fish_session.py`、`src/igess/fish_behavior*.py`、相关测试 |
| 正式经济闭环 | `[~]` | 鱼厅/金钱、废料/材料、历史境界追赶、付费新境界突破、材料→鱼厅/杠铃、金钱→鱼雷、两类重生永久倍率及离线基础结算已接通；出售和未确认离线扩展尚未闭合 | Phase 4–8 |
| 正式调参与报告 | `[~]` | 核心强度与永久养成一等报表、24h/7d KPI 基线和第一轮双 Luck 纯价格调参已完成；长期价格验证、策略分叉、compare/gate/scan 消费仍待实现 | Phase 9 |

当前不能把项目描述成“完整 Fish 经济模拟器”。准确口径是：

```text
通用最小经济 smoke 可运行
+ RNG 一期基线已验证
+ PlayerState / checkpoint 基础已完成
+ FishEconomySimulator 已接入生产数据驱动的投掷、鱼厅金钱、废料材料、在线历史境界追赶、付费新境界突破、摸鱼厅升级、鱼雷购买/自动装备、杠铃合成/装备/主动在线锻炼、两类重生永久倍率和可选加权行为循环
+ 默认画像 `daily_online_seconds=7200`，每天在线 2 小时、离线 22 小时；`purchase_torpedo / synthesize_barbell / upgrade_fish_hall / fund_trash_man_breakthrough` 权重均为 `100`，`manual_throw / exercise_barbell` 权重均为 `1`，`upgrade_fish` 权重为 `0.1`；鱼升级仅选择最低价且要求价格严格低于当前材料 `1/10`，成功时扣除材料
+ 两类重生均已进入生产画像，达到要求时硬优先于全部普通前台行为
+ 24h 上限、双倍领取、临时效果、30d 正式产物压缩、第 15～60 境界和 10/11 号鱼雷的超月验证尚未完成
```

## 3. 已锁定的架构边界

### 3.1 必须接入 IGESS

Fish 模拟器**必须接入当前代码框架 IGESS**。这是项目的强制约束，不是可选的后续优化。

Fish 允许拥有自己的领域特殊逻辑，例如：

- 鱼雷投掷、轨迹和距离计算。
- BonusChain、鱼、变异与废料随机规则。
- 鱼实例、摸鱼厅栏位、垃圾佬加工和两类重生。
- Fish 专用事件、状态迁移、玩家策略和报告扩展字段。

但这些逻辑最终必须通过 IGESS 的统一接口接入，不能长期停留在独立脚本、独立 CLI 或独立报告管线中。正式实现至少必须满足：

1. 由 IGESS 发现和加载项目，通过 `engine_id` 派发到 Fish 领域适配器。
2. 正式模拟由 `WorkflowService` 发起并登记到 `RunRegistry`。
3. 配置、Luban 数据、参数覆盖和运行结果都记录同一个 `model_digest` 与来源信息。
4. 输出 IGESS 标准的 manifest、timeline、events 和 analysis；Fish 数据只能作为兼容扩展。
5. checkpoint 可以作为正式运行的输入和输出，并接受引擎与模型摘要校验。
6. Fish 的可调参数可以进入 IGESS 的 `scan`、`compare`、`gate` 和调参流程。
7. 标准报告、Dashboard 和 Agent Analyst 能直接消费 Fish 运行结果，用于数值平衡分析。
8. 独立的 RNG Probe 或诊断命令只能作为验证工具，不能成为另一套权威规则或正式模拟入口。

判断一项 Fish 模拟能力是否真正完成时，不能只看领域函数或独立测试是否可运行；还必须验证它已经通过 IGESS 标准工作流运行、留下可追踪产物，并能参与数值比较与平衡分析。任何尚未接入 IGESS 的 Fish 特殊逻辑最多标记为 `[~]`，不能标记为 `[x]`。

### 3.2 目标结构

最终只允许一个对象持有并推进玩家状态：

```text
IGESS WorkflowService
-> engine_id dispatch
-> FishEngineAdapter
-> FishEconomySimulator
   |- PlayerState
   |- SimulationCheckpoint
   |- SimulationClock
   |- PlayerPolicy
   |- resolve_throw()
   `- economy state transitions
-> standard SimulationResult
-> OutputWriter / RunRegistry / report / compare / scan / gate
```

必须持续遵守：

1. `FishEconomySimulator` 是唯一推进 `PlayerState` 的对象。
2. 单次炸鱼规则只有一份权威 `resolve_throw()`；RNG Probe 只能重复调用它。
3. 策略只能发出命令，不能直接修改玩家存档。
4. 静态配置、玩家事实、推导值、策略和报告分离。
5. 正式 Fish 运行必须进入 IGESS `WorkflowService` 与 `RunRegistry`。
6. Fish 产物扩展标准 manifest、timeline、events、analysis，不建立第二套报告管线。
7. 同一 checkpoint、配置、策略和终止条件必须产生相同结果。
8. 连续运行必须等价于 checkpoint 分段恢复运行。
9. 资源不能无来源增加或消费成负数。
10. 关键结论必须可追踪到 `model_digest`、配置表、来源行和状态迁移事件。
11. 允许 Fish 使用领域专用实现，但不允许绕开 IGESS 建立独立的正式运行、调参或报告体系。

### 3.3 玩家行为调度边界

1. IGESS 通用层以离散事件调度玩家行为：每名玩家画像分别配置
   `behavior_weights`、`behavior_durations` 和 `behavior_target_policies`。
2. 每次只允许一个前台行为占用玩家时间；Fish 当前行为为
   `manual_throw`、`upgrade_fish`、`upgrade_fish_hall`、
   `synthesize_barbell`、`exercise_barbell`、`strength_rebirth`、
   `trash_man_rebirth`、`idle`。摸鱼厅和垃圾佬加工属于后台系统；
   已装备杠铃本身不产出，只有 `exercise_barbell` 在线执行期间产出力量。
3. 领域适配器先过滤当前不可执行的行为和目标，再对剩余正权重重新归一化；
   鱼数量只影响升级目标池，不得隐式提高 `upgrade_fish` 的行为概率。
4. 行为选择、整数时长和目标选择使用三个独立稳定随机域，键为
   `(root_seed, profile_id, sequence_id, domain)`；输入顺序不改变重放结果。
5. checkpoint 保存 sequence 游标和进行中的完整行为，恢复时不得重新选择行为、
   时长或目标。纯记录边界只临时推导被动收入，不拆分领域结算事务。
6. Fish 为单鱼升级保留 fixture 使用的 `random_affordable`，生产画像使用
   `cheapest_below_material_tenth`：从全部未满级鱼中取升级价格最低项，同价按
   `instanceId` 升序决胜；仅当该价格严格低于当前 `wallet.material / 10` 时
   才可选。鱼升级价格从材料余额扣除。杠铃合成使用
   `random_affordable`，目标池只包含当前未拥有且材料可支付的 ID，避免重复
   合成不提高产出的库存副本。相应行为权重大于零时必须明确配置目标策略。
   生产 `default` 画像为高优先级 `synthesize_barbell` 和
   `upgrade_fish_hall` 配置权重 `100`，为 `manual_throw` 和
   `exercise_barbell` 配置权重 `1`，为低优先级 `upgrade_fish` 配置权重
   `0.1`；两类重生均配置权重 `1`，上述七种行为均为固定 `1` 秒时长。
   重生不依赖大权重近似优先级：只要任一重生可执行，本轮候选池就只保留
   当前可执行的重生；若两种同时可执行，则在二者之间稳定选择一种，下一轮
   立即执行仍可用的另一种。`upgrade_fish_hall` 是无目标行为，仅在未满级且当前材料足以
   支付时可选；`strength_rebirth` 同样无目标，仅在未满档且当前力量达到
   `tbstrengthrebirth[id=completedCount+1]` 的门槛时可选。
   `trash_man_rebirth` 也是无目标行为，仅在未满档、没有进行中的突破且当前
   `realmId >= tbtrashmanrebirth[id=completedCount+1].realmRequirement`
   时可选。`exercise_barbell` 是无目标行为，仅在拥有有效已装备杠铃时可选。
7. 玩家画像引用的 `session_pattern.daily_online_seconds` 定义每天从模拟日
   起点开始的连续在线预算；在线预算耗尽后不再选择前台行为，直到下一模拟日。
   行为候选时长会限制在剩余在线窗口内，无法完成的行为不进入本次候选。

### 3.4 GDD 数值规则基线

规则语义来源：`E:\fish-oasis\gdd`；唯一权威生产快照：`E:\fish-oasis\igess_export`。下列内容用于拆解实现与测试。所有表内数值直接采用 `igess_export/json` 当前 JSON，并通过同次导出的 `igess_export/python/schema.py` 加载；文字 GDD 只解释计算顺序和业务语义，不得覆盖 JSON。只有数据表未表达的字段、公式或行为才需要与人类确认。

#### 3.4.0 数值一致性强制约束

1. 正式模拟必须通过权威快照 `E:\fish-oasis\igess_export\python\schema.py` 加载同目录版本的 `E:\fish-oasis\igess_export\json\*.json`；IGESS 只负责通用文件读取、输入哈希并消费生成后的强类型表对象，不能手写第二套字段解析器或维护第二份手抄正式数值。
2. 表名、行数、ID、字段、精度和大数含义必须与游戏数据一致；不得擅自补齐空档、平滑曲线、修改异常值、重排 ID 或替换为“更合理”的值。
3. JSON 数值与文字 GDD、历史示例、测试 fixture 或现有代码常量冲突时，以 JSON 数值为准；差异记录为数据审计信息，但不阻塞按 JSON 实现。
4. 缺字段时不得猜测生产数值。允许用显式 `fixture` 验证机制，但 fixture 运行必须与正式结果隔离，并在 manifest 和报告中标记 `production_data=false`。
5. 数值读取保留原始精度。概率门槛、倍率和大数在计算层不得先按展示格式取整；只有 UI/报告展示层可以格式化。
6. 每次正式运行的 manifest 至少记录：数据根目录、每个输入文件的内容哈希、合并后的 `model_digest`、override 列表和 `production_data=true`。
7. 正式场景默认禁止 override；scan/调参允许 override，但必须同时保存原始值、覆盖值和字段路径，且结果不得标记为“与游戏实际数值一致”。
8. 数据契约测试必须逐表验证生成对象与权威 export JSON 逐字段一致，并同时记录 JSON 与生成加载器哈希；不再要求与旧 `gdd/data` 副本逐文件一致。当前 12 张表、340 行已通过该生成对象契约。

#### 3.4.1 配置大数

GDD JSON 中 `{sign, digits, scale}` 按以下口径转换：

```text
value = sign × decimal(digits) × 10^scale
```

配置大数与存档 `{sign, coeff, exp}` DTO 是两种格式，必须通过适配器转换，不能混用。

#### 3.4.2 一次投掷与随机域

1. 每次有效投掷固定产出 `1` 条鱼和 `1` 份废料。
2. 鱼线与废料线独立：力量按 `FishRandomPool.strengthUpperBound` 区间插值得到 `FishLuck`；鱼雷 power 按 `TrashRandomPool.powerUpperBound` 区间映射 `TrashLuck`，`TrashRollPower` 再映射为表现层下探深度。
3. Bonus 每层、具体变异、最终鱼、废料稀有度、废料池内选择必须使用相互独立且可重放的随机域。
4. 通用公式：`RollPower = Luck / Random(0, 1]`；门槛为 `X` 的结果被击穿概率为 `min(1, Luck / X)`。
5. 鱼从当前可用池中选择 `FishDenominator <= FishRollPower` 的最高门槛项；若全部未击穿，回退到当前池最低门槛鱼。
6. 某条鱼 `F_i` 的最终产出概率为 `min(1, FinalFishLuck/F_i) - min(1, FinalFishLuck/F_(i+1))`，最高门槛鱼没有第二项。
7. 当前权威导出的 `tbtrash` 39 行均已有唯一 `Denominator`；正式规则按 `TrashDenominator <= TrashRollPower` 选择全表中的最高门槛废料，取代旧的“先选稀有度、再池内权重随机”。不得用鱼结果限制废料池。

#### 3.4.3 BonusChain 与变异

首版 `MaxBonusLayer = 4`，每层只做一次互斥外层判定：

| 结果 | `rollPowerRequirement` | `BonusBaseLuck=1` 单层概率 | 效果 |
| --- | ---: | ---: | --- |
| 无 Bonus | `1` | `73.6%` | 结束链并进入正式鱼随机 |
| 进入变异 | `3.787878787878788` | `16.4%` | 条件池必选一个非 Normal 变异，继续下一层 |
| Luck ×2 | `10` | `10%` | 当前 FishLuck ×2，继续下一层 |

补充约束：

- `BonusRollPower = 1 / Random(0, 1]`，不读取当前 FishLuck；因此 FishLuck 翻倍不会提高后续层 Bonus 概率。
- 一次链最多获得一个变异；获得后锁定，后续层的“进入变异”视为不可用且不重新归一化，此时为无 Bonus `90%` / Luck ×2 `10%`。
- 第 4 层 Bonus 仍生效，但不再续层。
- 当前非 Normal 变异十万权重依次为 `54922, 21969, 16643, 4394, 1649, 275, 110, 27, 11`，收入倍率依次为 `1.5, 2, 4, 6, 8, 12, 16, 40, 50`；Normal 权重 `0`、收入倍率 `1`。
- 当前理论基线：任意变异约 `18.22%`，至少一次 Luck ×2 约 `11.6%`，`FinalFishLuck/FishLuck` 期望约 `1.150`；进入第 2/3/4 层约为 `26.4% / 4.28% / 0.59%`。

#### 3.4.4 力量与 FishLuck

1. 出手时锁定力量快照；飞行期间力量变化不影响本次投掷。
2. `FishRandomPool.strengthUpperBound` 表示当前区域终点对应的力量，是包含性右端点。若各行终点为 `R1...Rn`，则第一区域为 `[1,R1]`，后续区域为 `(R(i-1),Ri]`；从低到高选择第一个满足 `strength <= strengthUpperBound` 的池。
3. 力量限制到 `[1, Rn]`。当前区域的起点取 `1`（第一区域）或上一行的 `strengthUpperBound`，终点取当前行的 `strengthUpperBound`。
4. 池内力量进度使用对数和平滑阶跃，并直接插值 BaseFishLuck：

```text
t = clamp((ln(F)-ln(Fmin))/(ln(Fmax)-ln(Fmin)), 0, 1)
u = t² × (3-2t)
BaseFishLuck = lerp(startLuck, endLuck, u)
FishLuck = max(1, BaseFishLuck × RegularLuckMultiplier)
FinalFishLuck = FishLuck × 2^BonusDoubleCount
```

5. 精确等于 `Ri` 时使用第 `i` 行的 `endLuck`；刚超过 `Ri` 时进入下一行并从其 `startLuck` 开始。相邻行 Luck 端点允许不连续，必须原样保留生产 JSON 的跳变，不得平滑或补齐。
6. 常规 Luck 倍率在 BonusChain 前相乘；同类型效果如何合并由效果所属系统先处理。

#### 3.4.5 鱼雷轨迹边界

鱼雷轨迹由最终落点反推，属于客户端表现层。经济模拟只使用锁定力量和
`tbfishrandompool` 计算 FishLuck，不模拟轨迹，也不把目标距离或实际入水
距离作为 `resolve_throw()` 输入。

#### 3.4.6 经济、升级与持续产出

1. 摸鱼厅基础每秒金钱为所有上阵鱼产出的和；鱼变异收入倍率作用于对应鱼，力量重生倍率作用于摸鱼厅整体产出，即 `摸鱼厅秒产出=sum(上阵鱼秒产出)×力量重生总倍率`。容量只限制求和项数量，不额外作为乘数。模拟不保留手动编队策略：每次鱼库存或单鱼收益变化后，按当前单鱼每秒收益降序取容量内前 `N` 条自动上阵，其余留在背包；同收益按 `instanceId` 升序稳定决胜，并按该顺序占用 `hallSlot=1..N`。
2. 鱼等级从 `1` 开始，最高 `100` 级。当前等级为 `n` 时，单鱼升级前的基础秒产出为 `B×1.25^(n-1)`；变异收入倍率在等级倍率之后乘入最终产出。从 `n` 升到 `n+1` 的材料价格为 `B×1.5^(n-1)`，价格不乘变异倍率。价格、产出和材料扣款统一使用 BigNumber，不额外做整数取整。
3. 摸鱼厅容量读取 `FishHallUpgrade.slotQty`；当前 JSON 有 `21` 行，容量从 `10` 到 `30`，升级消耗材料。模拟采用顺序映射：`upgradeLevel=0` 读取第一行，等级 `n` 读取第 `n+1` 行；从 `n` 升到 `n+1` 消耗当前第 `n+1` 行的 `upgradePrice`。只有存在下一行时才能升级；最后一行容量 `30`、`upgradePrice=0` 是满级哨兵，不是免费升级。升级命令先按旧容量结算后台生产，再原子扣材料、提升等级和 revision；随后按 IGESS 已锁定的 `fixed_max_income` 模拟策略重排阵容。若后续配置增加显式等级字段，再替换顺序映射。
4. 杠铃消耗材料，当前 `tbbarbell` 有 `15` 档，`strengthPerExercise` 从 `2` 到 `5,000,000`，生产行的 `timeCost` 当前均为 `1` 秒；主动锻炼的在线力量速度为 `strengthPerExercise / timeCost`。已装备杠铃本身不属于后台产出，只有当前互斥前台行为为 `exercise_barbell` 时才按 `equippedId` 产出力量，库存 `count` 不作为倍率；炸鱼、升级、合成、重生和 idle 期间均不产出力量。合成原子扣材料、增加一件库存和 revision，并按固定 `highest_strength_per_second` 策略自动装备当前速度最高的已拥有杠铃；显式换装命令只允许选择已拥有 ID。离线力量固定为 `0`。
5. 鱼雷消耗金钱并提升废料 Luck；当前 `Torpedo` 表有 `25` 行、power 从
   `50` 到 `30B`，`price` 由同表提供。购买只检查未拥有、比当前装备强和
   金钱可支付，不读取当前力量或历史最高力量；成功后自动装备。生产画像采用
   `highest_affordable`，成长时点完全由价格控制。
6. 废料当前 `39` 行，全部 `baseDecomposeSeconds = 300`；材料基础速度从 `2/s` 到 `10M/s`。Phase 5 v1 将其解释为基础工作量与每单位基础工作材料：每真实秒推进 `decomposeSpeedMultiplier` 单位工作，材料为 `baseMaterialPerSecond × 已消费工作量 × 转世产出倍率`。因此加速缩短耗时但不减少同一废料的基础总材料。
7. 垃圾佬境界当前 `60` 档，`decomposeSpeedMultiplier = 1 + 1.25×(ID-1)`，从 `1` 到 `74.75`；修炼时间字段从 `0s` 到 `36310s`。`moneyRequireToNextRealm` 的 1～59 号为严格递增正价，60 号为 `0` 满档哨兵。
8. 当 `realmId < highestRealmId` 且没有进行中的突破时，在线时间免费追赶至历史最高境界；达到历史最高境界后，`fund_trash_man_breakthrough` 按当前行价格扣金钱并创建目标为下一表行的突破。突破只累计在线时间，离线暂停；跨境界统一结算先按旧速度加工到完成边界，再更新当前/历史最高境界并启用新速度。闭关期间废料加工持续进行。
9. 资源变化必须先结算到当前服务端时间，再原子执行消费/换装/升级，成功后 `meta.revision += 1`。

#### 3.4.7 重生规则

力量重生只把当前力量归零；垃圾佬转世把当前境界重置到初始境界，并清零当前境界修炼进度。鱼、废料、金钱、材料、鱼雷、杠铃、摸鱼厅升级、垃圾佬非境界升级、历史最高境界和已获得永久倍率默认保留。

当前表基线：

- 力量重生 `completedCount=0` 时使用不在表内的默认 `1×`；生产
  `tbstrengthrebirth` 为一基 ID `1..10`，完成第 `n` 次后使用 `id=n`
  的摸鱼厅总倍率。下一次重生读取 `id=completedCount+1` 的力量门槛；
  共 `10` 档，门槛 `10^3` 到 `10^12`，总倍率 `2×` 到 `11×`。
- 力量重生命令先按旧倍率结算全部后台生产到命令时刻，再原子把
  `wallet.strength` 归零、将 `strengthCompletedCount` 增加到目标表 ID、
  增加 revision 并立即启用新总倍率；其他数值状态全部保留。
- 垃圾佬转世 `completedCount=0` 时使用不在表内的默认 `1×`；2026-07-24
  权威导出 `tbtrashmanrebirth` 为一基 ID `1..10`，完成第 `n` 次后使用
  `id=n` 的材料总倍率，下一次读取 `id=completedCount+1`。表内境界门槛
  `0,4,8,...,36` 按 `current realmId >= realmRequirement` 校验，材料总倍率
  `2×` 到 `11×`；首行 `id=1 / realmRequirement=0` 表示第一次转世。
- 垃圾佬转世命令先按旧倍率结算全部后台生产到命令时刻，再原子重置当前境界和
  本境界修炼进度、增加转世次数与 revision，并立即启用新材料总倍率；进行中的
  突破期间不可转世，历史最高境界及其他数值状态保留。
- 垃圾佬转世后仅在线自动修炼至历史最高境界；超过历史最高境界后才重新需要资助突破。
- 自动修炼和闭关期间仍按当前境界处理废料并产出材料。

#### 3.4.8 离线结算

1. 玩家画像引用的 `session_pattern.daily_online_seconds` 表示每天连续在线预算；
   默认画像为 `7200` 秒，即在线 2 小时后离线 22 小时。模拟时间 `t=0` 是
   首日上线起点，每 `86400` 秒重置预算并重新上线。
2. 在线预算内每次只推进一个前台行为；预算耗尽后严格离线，不再选择或推进
   前台行为，直到下一模拟日。候选行为时长不得跨越下线边界。
3. 摸鱼厅金钱和垃圾佬废料加工享受离线收益，效率为在线的 `50%`。
   垃圾佬的 50% 作用于加工工作速度，同一份废料的最终材料总量不缩水。
4. 已装备杠铃力量只由在线互斥行为 `exercise_barbell` 产生，离线效率为 `0%`。
5. 垃圾佬自动修炼与突破闭关首版仅在线推进。
6. 离线时长上限目前只有 `24h` 建议值，尚未成为已确认正式配置。
7. 材料离线收益受废料库存限制，不能凭空产生。
8. `lastSettledAt` 是唯一结算锚点；即使超过离线上限也推进到当前服务端时间，防止分次登录重复领取。
9. 普通领取与双倍领取互斥且只能成功一次；双倍领取消耗道具，具体道具/价格尚未确认。

#### 3.4.9 待人类确认清单

- `[~]` `05-a-力量与Luck计算流程.md` 的 FishRandomPool Luck 连续区间（如池 1 为 `1→5`）与当前 `igess_export/json/tbfishrandompool.json`（池 1 为 `1→3`，且多处池间有空档）冲突；模拟数值已明确以权威导出 JSON 为准，需人类确认的只是文字 GDD 是否同步修订。
- `[x]` 已于 2026-07-22 拍定正式流程为 `力量快照→按 strengthUpperBound 右端点选区→区内插值 FishLuck→BonusChain→FinalFishLuck→FishRollPower→鱼结果`；轨迹由最终落点反推，不进入经济结算，废料继续使用独立的 TrashLuck/TrashRollPower 链。
- `[x]` `strengthUpperBound` 是当前区域的包含性右端点；相邻行 Luck 不连续时按权威 JSON 原样保留跳变。
- `[x]` 当前 `tbfish` 121/121 行均已有唯一正式 `Denominator`；已确认 `Fish.xlsx`/`tbfish` 全表就是所有可用鱼，正式结算使用全表门槛池。
- `[x]` 当前 `tbtrash` 39/39 行均已有唯一正式 `Denominator`；已确认物品级门槛正式取代旧的稀有度池内权重随机，`05-核心随机算法.md` 已同步。
- `[x]` `tbtorpedo.price` 已进入生产强类型表适配和“金钱→鱼雷”闭环；
  2～11 号价格已按双 Luck 峰值同步目标完成首轮平衡，且明确不增加力量门槛。
- `[x]` `TrashRandomPool.powerUpperBound` 是当前鱼雷 power 区域的包含性右端点；TrashLuck 正式使用与 FishLuck 相同的对数进度 + smoothstep 区间插值并保留跨行跳变；表现层下探深度不进入经济结算。
- `[x]` 新档初始拥有并选中 `tbtorpedo` 第一行鱼雷；具体 ID 从生成表第一行读取，不在存档工厂中硬编码。
- `[!]` 缺少鱼直接出售价格公式或字段。
- `[x]` 上阵规则已简化为全局固定的最高收益编队：自动选择容量内当前每秒收益最高的鱼，不再比较 `collector`、手动编队或其他上阵策略。
- `[x]` 鱼升级规则已确认：等级 `1..100`；等级 `n` 产出为 `B×1.25^(n-1)×变异倍率`，从 `n` 升到 `n+1` 的价格为 `B×1.5^(n-1)`且不乘变异倍率，统一使用 BigNumber。
- `[x]` 生产 `tbbarbell.timeCost` 已给出每次锻炼秒数，当前 15 行均为 `1`；在线速度按 `strengthPerExercise/timeCost`，只有互斥前台 `exercise_barbell` 使用已装备杠铃产出且库存数量不放大，离线力量为 `0`。
- `[x]` 已于 2026-07-23 确认力量重生表是一基 ID：`completedCount=0` 为表外默认 `1×`；完成第 `n` 次后使用 `tbstrengthrebirth.id=n`，下一次门槛读取 `id=completedCount+1`。
- `[x]` Phase 5 v1 已采用固定工作量公式并用 BigNumber 结算材料；`0` 次转世为表外 `1×`，第 `n>=1` 次转世读取一基 `tbtrashmanrebirth.id=n`。
- `[x]` 垃圾佬新境界突破读取当前行 `moneyRequireToNextRealm` 作为价格、当前行 `cultivationSecondsToNextRealm` 作为在线闭关时长；转世后的历史境界追赶免费，历史最高境界以上必须重新付费，闭关期间继续按旧境界加工。
- `[x]` 已于 2026-07-24 确认新版 `tbtrashmanrebirth` 为一基 ID：`id=1` 表示第一次转世，初始转世次数为 `0`；首行 `realmRequirement=0` 按权威表原值校验。
- `[x]` 已于 2026-07-23 确认摸鱼厅顺序映射：当前 `upgradeLevel` 使用当前行价格升级到下一行；最后一行 `upgradePrice=0` 是满级哨兵，不允许免费升级。
- `[x]` 已于 2026-07-25 确认“全部永久进展”的阶段性频率目标。间隔统一按
  累计在线时间计算，并作为相邻永久进展事件及阶段尾部空窗的最大允许值：
  首个在线小时不超过 `30s`；首日剩余在线时间不超过 `60s`；第 2～7 日
  不超过 `120s`；第 8～30 日不超过 `300s`。默认 2h/22h 画像下，阶段按
  模拟日划分，但离线 22 小时不计入间隔。
- `[x]` 已于 2026-07-25 将“系统级永久进展”的累计次数目标调整为：首日 `10`
  次、首周 `20` 次、首月 `40` 次。系统级永久进展包括鱼雷、杠铃、摸鱼厅、
  力量重生和垃圾佬转世等跨鱼保留的系统成长，不含最佳鱼厅捕获和单鱼升级。
  `gate` 继续采用目标值上下各 `20%` 的包含性允许范围：首日 `8..12` 次、
  首周 `16..24` 次、首月 `32..48` 次。当前结果为 `9 / 23 / 36`，三阶段
  全部通过；30d 仍需补正式产物压缩。
- `[x]` 已于 2026-07-25 确认双 Luck 分开判定停滞，统一只累计在线时间：
  FishLuck 在首个在线小时/首日剩余时间/第 2～7 日/第 8～30 日的阈值分别为
  `300s / 600s / 1200s / 1800s`；TrashLuck 对应为
  `1800s / 3600s / 7200s / 21600s`。FishLuck 历史峰值相对上次有效提升
  至少增长 `1%` 才重置停滞计时；力量重生恢复期单独统计，不判普通停滞，
  但累计在线恢复超过 `5400s` 时报警。TrashLuck 任意严格增加均重置计时；
  已拥有最高档鱼雷后标记为“已封顶”，不再判停滞。任一 Luck 超阈值均独立
  标记，不得由另一项增长抵消。
- `[x]` 已于 2026-07-25 确认双 Luck 同步允许 `20%` 相对误差。沿用当前日报
  口径，以 `abs(TrashLuckPeak - FishLuckPeak) / FishLuckPeak` 计算；结果
  `<=20%` 通过，超过 `20%` 失败。
- `[!]` 离线时长上限是否正式采用 `24h`，双倍领取消耗什么，以及临时效果的叠加组/上限需确认。

## 4. 分阶段 RoadMap

### 基础 A：通用经济规则原型

- `[x]` 建立 `money`、`material` 两种资源。
- `[x]` 建立 `starter_fish_hall` 主动活动。
- `[x]` 配置每秒 2 金钱并加入默认玩家活动权重。
- `[x]` 自动 smoke 运行 10 秒，最终获得 20 金钱。
- `[x]` 正式 Fish 资源语义已由 Fish 专用引擎实现；不再继续扩展通用原型。
- `[x]` 已建立并接入 Fish 专用引擎场景，通用原型仅保留为框架 smoke。
- `[ ]` 增加非 smoke 正式场景，使模型从 `runnable` 达到可正式运行状态。

注意：这条原型只证明 IGESS 增量建模链可运行，不是正式鱼厅收入模型。

### 基础 B：RNG 一期验证

- `[x]` 验证 13 个力量/Luck 区间和边界。
- `[x]` 验证 BonusChain 外层互斥结果。
- `[x]` 验证变异条件池与权重。
- `[x]` 验证鱼和废料随机流独立。
- `[x]` 建立 GDD 示例配置与统计基线。
- `[x]` 将 RNG 规则收敛为权威 `resolve_throw()`；接口、稳定领域键 RNG、力量/Luck 和 Probe 复用、生产 Luban 表适配均已完成。轨迹已明确为表现结果，不进入经济结算。

### Phase 0：建立 IGESS 领域引擎接入点

状态：`[x]`，生产数据入口、标准工作流、checkpoint 恢复、报告和比较验收均已完成。

- `[x]` 定义最小领域引擎适配协议和 `engine_id` 派发。
- `[x]` 用默认适配器包装现有通用 `Simulator`，保证已有行为不退化。
- `[x]` 建立 `FishEngineAdapter` 与 `FishEconomySimulator` 空壳。
- `[x]` 让最小 Fish fixture smoke 通过 `WorkflowService` 和 authoring 正式路径运行。
- `[x]` 将 Fish fixture smoke 登记到 `RunRegistry`，记录 `engine_id` 与 `model_digest`。
- `[x]` 输出标准 manifest、timeline、events、analysis。
- `[x]` manifest 记录 `engine_id`、`model_digest`、策略和 override。
- `[x]` 已接入 `E:\fish-oasis\igess_export\json` 与 Luban 生成的 `python/schema.py`，记录 JSON 和加载器逐文件哈希；IGESS 不自行解析业务字段。
- `[x]` manifest 机制可记录数据根目录、逐文件哈希、`production_data` 和完整 override 差异。
- `[x]` 已验证 12 张表、340 行生成强类型对象与权威 export JSON 逐字段一致，并记录 JSON 与生成加载器哈希。
- `[x]` Fish fixture 字段可由 provider 通过统一 `table.row.field` 参数覆盖，且 manifest 保存原值与覆盖值。
- `[x]` checkpoint 已成为 Fish fixture smoke 的输入和输出，并执行引擎与模型摘要校验。
- `[x]` report/compare 可以读取并比较 Fish fixture smoke。

Phase 0 完成标准：Fish 可以通过 IGESS 标准入口运行、登记、恢复和分析；不要求已有完整经济闭环。该标准已达到。

当前验证证据：`tests/test_fish_engine.py` 覆盖 Luban provider、源文件/加载器哈希、逐字段生产契约、fixture override、WorkflowService/authoring 派发、RunRegistry、标准产物、checkpoint 恢复及 compare；生产 runs `20260722T052544104476Z-smoke`、`20260722T052557525711Z-smoke` 使用相同 `model_digest=sha256:ff044b1eb961edd53b449a45c77d0c52c6143f784a322ef8c6ab753aced299ff`，比较结果为零差异。

### Phase 1：PlayerState 和 checkpoint

状态：`[x]`，Schema/codec、投掷、鱼升级、两类重生和统一生产结算的运行时集成及 checkpoint 已完成。

- `[x]` 实现通用 `SimulationCheckpoint` v1 外壳。
- `[x]` 实现 `PlayerState` v1，与正式业务存档 `data` 对齐。
- `[x]` 实现 `{sign, coeff, exp}` 大数 DTO。
- `[x]` 实现新存档工厂、严格读取、规范 JSON 和深拷贝。
- `[x]` 实现 Fish `engine_state` codec 与 `model_digest` 校验。
- `[x]` 实现稳定 `next_throw_id`、鱼实例/栏位、废料聚合库存校验。
- `[x]` checkpoint 可选保存通用行为 sequence 游标和进行中的完整行为；
  旧引擎不写该区块时保持原 v1 JSON 形状。
- `[x]` 存档与 checkpoint 定向测试通过。
- `[ ]` 定义两类重生的显式重置/保留集合与状态迁移。
- `[~]` 已实现一次投掷的鱼领取、废料入库、统计、鱼升级以及鱼厅金钱/垃圾佬材料统一结算原子事务；鱼升级会扣除材料、增加等级并重排固定最高收益阵容。鱼出售等领域命令仍待正式口径；图鉴明确不属于 IGESS 模拟范围。
- `[~]` 投掷、鱼升级和鱼厅/材料统一结算均按事务递增 `meta.revision`；覆盖全部后续领域命令的统一提交协调仍待实现。
- `[~]` 鱼、变异、鱼厅、废料和垃圾佬境界/转世已接入正式表适配及相关 ID/容量校验；跨全部正式表和后续领域命令的统一校验仍待补齐。
- `[x]` 完成 10 秒连续主动投掷与两个 5 秒 checkpoint 分段恢复等价测试。
- `[x]` 投掷状态循环已接入 `WorkflowService`、manifest 和 `RunRegistry`。

### Phase 2：单次炸鱼正式结算

状态：`[x]`，生产 Luban 表适配、权威纯结算、玩法语义和标准工作流一次投掷均已完成；纯结算仍不读写 PlayerState，奖品由独立原子领域命令提交。

- `[x]` 定义 `ThrowInput`、`ThrowRules`、`ThrowOutcome` 和不读写 `PlayerState` 的纯函数 `resolve_throw()`。
- `[x]` 实现力量到 BaseFishLuck 的正式纯函数；按当前行 `strengthUpperBound` 包含性右端点选区并直接插值，不依赖物理距离。
- `[x]` 已固化 `RollPower = Luck / Random(0,1]`、最高门槛击穿和最低项回退；当前 121 条鱼和 39 份废料的生产 `Denominator` 已全部通过适配器进入门槛池。
- `[x]` BonusChain、变异、鱼随机和废料随机已接入权威结算函数且 Probe 改为重复调用它；生成的 Luban 强类型表对象已适配为 `ThrowRules`，未建立第二套 JSON 解析器。
- `[x]` 改用稳定领域键 RNG，按 `(root_seed, throw_id, stream, index)` 保证随机域互不干扰并可独立重放。
- `[x]` 保证单次结算不读取或修改 `PlayerState`。
- `[x]` 保证一次有效投掷在完整有效池配置下严格产生一条鱼和一份废料。
- `[x]` 正式 run `20260722T154251033213Z-smoke` 通过 IGESS 标准工作流加载 12 表 340 行，从 `tbtorpedo` 第一行初始化新档，记录 `fish_throw_resolved`、已确认的池/插值语义、生产数据哈希与 `model_digest=sha256:a1db4a728a10b4ecb8626a88c63ff7e4aa3b2f46490438cebaa86e8831d7c168`；checkpoint 恢复 run `20260722T154306291059Z-smoke` 未重复投掷。
- `[x]` 已确认并实现：鱼使用 `tbfish` 全表门槛池；TrashLuck 镜像 FishLuck 的对数 smoothstep；废料使用 `tbtrash.Denominator` 全表门槛池。

Phase 2 的纯结算到此完成。`ThrowOutcome` 已通过独立领域命令原子写入鱼背包、废料库存、统计和 `meta.revision`；鱼实例重量直接读取生成的 `tbfish.weight` 正整数，并按存档规范保存为整数克。图鉴等非数值字段保持不变。奖品已进入 Phase 3 事件循环，并可继续进入 Phase 4/5 后台生产。

### Phase 3：时间引擎和模拟循环

状态：`[~]`，主动投掷、加权行为事件循环、后台鱼厅金钱/垃圾佬材料、主动杠铃锻炼、每日在线/离线边界、历史境界追赶和付费新境界突破均已接入；buff 等领域事件仍待实现。

- `[x]` `TimeEngine` 已提供 `(start, end]` 绝对周期事件边界，鱼厅、废料加工、历史境界追赶和付费突破完成均按解析边界结算。
- `[~]` 加权模式按“当前在线模式的后台金钱/材料与当前前台锻炼力量结算→境界突破完成→前台行为完成→会话边界→timeline 采样→选择下一行为”稳定排序；buff 等新增领域事件优先级仍待定义。
- `[x]` 通用 `BehaviorScheduler` 已实现玩家级权重、固定/整数均匀时长、可用性过滤、目标选择、`idle` 和三路稳定 RNG。
- `[x]` Fish 已接入 `manual_throw / upgrade_fish / upgrade_fish_hall / purchase_torpedo / synthesize_barbell / exercise_barbell / fund_trash_man_breakthrough / strength_rebirth / trash_man_rebirth / idle`；付费突破与鱼雷/杠铃/鱼厅同为权重 `100`、固定 `1s` 的普通高优先级候选，两类重生达到门槛时仍硬优先于全部普通行为。
- `[~]` 已支持废料加工、历史境界在线追赶和付费新境界突破；buff 过期事件尚未实现。
- `[x]` 旧主动投掷模式支持事件边界 checkpoint；加权行为模式可在行为中间 checkpoint，恢复时继续已保存行为而不重抽。
- `[x]` 已验证在线训练后进入离线的连续运行与离线中 checkpoint 分段恢复一致，并完成生产 24h 与 7d 正式成长画像；两个 12 小时分段的正式运行不再作为当前验收口径。
- `[ ]` 验证 tick 与事件跳跃模式结果一致。

### Phase 4：鱼、摸鱼厅和金钱闭环

状态：`[~]`，固定最高收益编队、等级收入、容量、金钱结算、鱼升级材料扣款和 trace 已接入；生产画像已启用手动炸鱼及低优先级最低价格鱼升级，24h/7d 正式长时验证已完成，出售口径仍待确认。

目标链路：`炸鱼 -> 鱼实例 -> 自动最高收益上阵 -> 鱼厅产出金钱`，以及 `材料 -> 鱼升级 -> 更高鱼厅收入`。

- `[~]` 已实现鱼背包、领取、升级和固定最高收益鱼厅栏位事务；出售等待正式价格口径。
- `[x]` 接入基础金钱产出、等级 `×1.25^(n-1)` 曲线与变异收入倍率。
- `[x]` 已接入鱼升级材料价格 `B×1.5^(n-1)`、BigNumber 材料扣款、100 级上限和升级后自动重排；fixture 中的 `random_affordable` 从当前材料可支付、未满级目标中稳定随机选择。生产画像使用权重 `0.1` 的 `cheapest_below_material_tenth`，只选择最低升级价格，同价按 `instanceId` 升序决胜，并要求价格严格低于当前材料 `1/10`。
- `[x]` 实现鱼厅容量、收入计算和公式 trace。
- `[x]` 实现全局固定的 `max_income` 自动编队：按单鱼当前每秒收益降序填满容量，同收益按 `instanceId` 升序决胜；不再实现 `collector` 上阵策略。
- `[x]` 用解析公式验证固定阵容累计金钱，并验证连续 10 秒与 `5+5` 秒 checkpoint 恢复等价。

### Phase 5：废料、垃圾佬和材料闭环

状态：`[x]`，废料库存、在线/离线批量加工、材料产出、境界速度、转世材料倍率、在线历史境界追赶、付费新境界突破和 checkpoint 已接入。

目标链路：`炸鱼 -> 废料库存 -> 垃圾佬加工 -> 材料`。

- `[x]` 实现废料聚合库存和按 `trashId` 升序的批量加工队列；活动目标仍包含在聚合库存中，完成时才扣除。
- `[x]` 实现境界分解速度、转世材料倍率与固定基础工作量；材料按实际消费工作量连续产出，离线以 50% 工作速度处理同一守恒库存。
- `[x]` 已实现仅在线、最多追赶至 `highestRealmId` 的免费修炼，以及历史最高境界以上的付费突破；按当前行修炼时间推进，跨境界先结算旧速度再启用新速度，行为中途 checkpoint 不拆分提交。
- `[x]` 验证废料数量守恒、批量跨物品结算、变速后的剩余工作量和同一废料总产量不漂移。
- `[x]` 小数基础工作进度保存在 checkpoint 的 `engine_runtime_state`，不修改生产 PlayerState v1 的整数 `activeProgressSeconds` 字段。
- `[x]` 主动投掷和加权行为循环均在前台命令前原子结算鱼厅金钱与垃圾佬材料；timeline 可临时推导但不拆分事务。

验证证据：`tests/test_fish_throw_commands.py`、`tests/test_fish_engine.py`、`tests/test_fish_state.py`、`tests/test_checkpoint.py`、`tests/test_behavior.py` 和 `tests/test_behavior_config.py` 定向回归通过；生产快照字段契约测试单独以 `external_data` 标记。覆盖境界边界前后材料速度、首境界 `0s` 需求、历史最高境界封顶、行为中途 checkpoint 不提前提交，以及连续/分段恢复等价。

### Phase 6：升级和交叉养成

状态：`[~]`，材料升级鱼/摸鱼厅容量、材料合成杠铃/主动在线锻炼力量以及
金钱购买鱼雷均已完成生产表适配、原子扣款、互斥行为接入和 checkpoint；
垃圾佬新境界突破已完成生产表适配、原子扣款、互斥行为、在线边界结算、
checkpoint 和永久进展报表接入。

目标链路：

```text
金钱 -> 鱼雷 / 垃圾佬突破
材料 -> 鱼升级 / 鱼厅 / 杠铃
杠铃 -> 力量 -> FishLuck
鱼雷 -> TrashLuck
```

- `[x]` 实现鱼雷购买、拥有和自动选用：严格消费 `wallet.money`，失败不修改
  状态，成功后记录 `torpedo_purchased` 与 price/money/power/TrashLuck
  before/after/delta。生产 `highest_affordable` 只按拥有、power 和价格过滤，
  不使用当前力量或历史最高力量。
- `[x]` 实现鱼厅升级：当前等级行价格、末行零值满级哨兵、BigNumber 材料扣款、容量立即生效、`fixed_max_income` 重排和 `upgrade_fish_hall` 无目标行为均已接入；生产画像配置权重 `100`、固定 `1` 秒的高优先级行为。
- `[x]` 实现杠铃合成、显式装备与互斥前台 `exercise_barbell` 在线力量产出：价格消耗材料，速度为 `strengthPerExercise/timeCost`，仅锻炼时的装备项产出，库存数量不放大；合成后固定自动装备最高每秒力量，其他行为和离线均不产力量。
- `[x]` 生产画像已将鱼雷购买配置为权重 `100`、固定 `1s` 的优先行为，
  使用 `highest_affordable`；7 天正式 run 验证 8 次购买分布在第
  1/2/3/4/5/7 天；没有同秒或紧邻连续跳档，首日三次购买分别间隔
  `1,159s / 4,883s`。
- `[~]` 已验证鱼升级、鱼厅升级和杠铃合成严格消费材料、鱼雷严格消费金钱，
  且失败均不修改状态；垃圾佬突破仍等待对应规则完成。

验证证据：原 Phase 6 回归覆盖鱼厅当前行价格、BigNumber 扣款、末行零值
哨兵、容量严格递增、杠铃生产表 15 档与 `timeCost`、库存数量不放大、材料
不足失败不修改状态、`fixed_max_income` 扩容重排及行为中 checkpoint；
`tests/test_fish_torpedo_commands.py` 覆盖纯价格可支付判定、最高可支付目标、
扣款/拥有/自动装备、Luck 事件字段及失败不修改状态。正式结果见
`reports/torpedo-price-balance.md`。

### Phase 7：重生和永久成长

状态：`[~]`，两类重生事务、永久总倍率、无目标行为、在线历史境界追赶、checkpoint、生产硬优先级策略和 24h/7d 直接产出/重置进度恢复分析已完成；包含 FishLuck 机会成本的禁用重生反事实比较留待 Phase 9。

- `[x]` 实现力量重生及摸鱼厅永久倍率：`0 次=表外 1×`，完成第 `n` 次后读取 `tbstrengthrebirth.id=n`；命令先结算旧倍率，再仅清空当前力量并立即启用新总倍率。
- `[x]` 实现垃圾佬转世及材料永久倍率：`0 次=表外 1×`，完成第 `n` 次后读取一基 `tbtrashmanrebirth.id=n`；命令先结算旧倍率，再重置当前境界/修炼进度并立即启用新总倍率。
- `[x]` 实现历史最高境界保留与转世后在线追赶；按旧/新境界边界分段加工废料，达到历史最高境界后停止自动推进。
- `[x]` 实现统一生产重生策略：只要当前满足任一重生要求，本轮只允许选择可执行的重生；两种同时满足时先稳定选择一种，下一轮立即执行另一种。
- `[x]` 在正式 24h/7d 场景中输出重生时间线、永久产出立即生效时间和被重置进度恢复时间；报告明确区分直接现金流与完整反事实经济回本。
- `[x]` 已验证力量重生只重置 `wallet.strength`；垃圾佬转世只重置当前境界和修炼进度，历史最高境界、加工队列和其他数值状态保留。

验证证据：`tests/test_fish_rebirth_priority.py` 验证两类重生同时满足时会连续抢占全部普通行为；生产 run `20260724T163134465887Z-day_1_growth` 与 `20260724T164206268531Z-week_1_growth` 成功，模型摘要为 `sha256:9876ad1049c75a8c1d65276b972ba02bc8043d66374c51c50050fcc64b655bc6`，长期结论见 `reports/rebirth-long-term-baseline.md`。7d 事件审计确认三次力量门槛均由同秒杠铃锻炼完成事件直接切入重生开始事件，中间没有普通行为；当前 Fish 全量回归为 `110 passed, 3 deselected`。既有回归覆盖两张一基重生表契约、表外默认 `1×`、门槛不足/满档/突破中失败不修改状态、旧倍率先结算、永久总倍率 trace、重置/保留字段、转世后在线历史境界追赶、无目标行为可用性以及行为中 checkpoint 连续/分段恢复等价。

### Phase 8：离线、临时效果和长期模拟

状态：`[~]`，每日在线预算、在线/离线事件边界、离线鱼厅/废料加工、防重复 checkpoint 和 24h/7d 正式长时基线已完成；24h 离线上限、双倍领取和临时效果尚未确认或实现。

- `[x]` 实现 `session_pattern.daily_online_seconds` 驱动的每日连续在线窗口和离线区间；默认值为 `7200` 秒，即每天在线 2 小时、离线 22 小时，每 86400 秒重置。
- `[x]` 实现统一 `lastSettledAt` 结算锚点，在线/离线边界原子提交，离线中 checkpoint 恢复不会重复领取。
- `[x]` 实现摸鱼厅金钱和垃圾佬加工离线 `50%`，已装备杠铃离线 `0%`；力量只由在线 `exercise_barbell` 互斥行为产生。
- `[~]` 废料库存约束、50% 工作速度和批量结算已实现；离线时长 `24h` 上限仍待正式确认。
- `[x]` 新增 24h/7d 正式成长场景；7d 使用普通事件紧凑明细、重生完整 trace，并通过流式 JSON 输出与周规模 checkpoint 验证保持可审计性。
- `[ ]` 实现临时 Luck、速度、金钱和材料效果。
- `[ ]` 验证跨 buff 过期点积分与长时间事件跳跃。

验证证据：`tests/test_fish_offline_sessions.py` 覆盖默认 2h/22h 配置契约、在线训练严格截止、离线力量为零、鱼厅/废料加工 50%、离线不推进修炼、每日窗口纯函数以及离线中 checkpoint 连续/分段等价；`tests/test_fish_long_term_scenarios.py`、`tests/test_fish_hall_cache.py`、`tests/test_fish_progression_reports.py` 和 `tests/test_checkpoint.py` 覆盖正式场景契约、复制/独占提交完整等价、增量 Top-N 与全量排序等价、紧凑事件保留重生 trace、报表口径/确定性/7d 基线以及 24,000 条鱼 checkpoint 往返。当前 Fish 全量回归为 `115 passed, 3 deselected`。

### Phase 9：策略比较和数值报告

状态：`[~]`，24h/7d 核心强度与永久养成一等报表、机器可读 KPI、静态
HTML 和第一轮双 Luck 纯价格调参已完成；长期价格验证、策略分叉及
compare/gate/scan 消费仍待实现。

- `[x]` 每个正式 Fish run 输出 `luck_progression.json/csv`：按固定累计在线时间采样 Strength、FishLuck、TrashLuck 当前值/峰值/变化速度/停滞时间，并保留重生回落和永久里程碑标记。
- `[x]` 每个正式 Fish run 输出 `behavior_progression.json/csv`：只统计永久或跨鱼保留的成长，排除单鱼升级；捕获只有实际提高最佳鱼厅 CPS 时才计入，并输出在线时间间隔、分类、before/after/delta、每在线小时密度和完整在线场次空窗。
- `[x]` 静态 HTML 已显示 Strength 与双 Luck 当前/峰值曲线、永久进展密度、归一化变化幅度、KPI 和逐事件表。
- `[x]` “全部永久进展”最大在线空窗目标已确认：首个在线小时 `30s`、首日
  剩余在线时间 `60s`、第 2～7 日 `120s`、第 8～30 日 `300s`。阶段边界按
  模拟日划分，间隔只累计在线时间；后续 `gate` 必须同时检查相邻事件间隔和
  每个阶段结束时的尾部空窗。
- `[x]` “系统级永久进展”累计次数目标已重定标为：首日 `10` 次、首周 `20`
  次、首月 `40` 次。默认 2h/22h 画像对应首日 `5/在线小时`；第 2～7 日新增
  `10` 次，约 `0.83/在线小时`；第 8～30 日新增 `20` 次，约
  `0.43/在线小时`。报告需同时输出累计次数、阶段新增次数和每在线小时
  密度；`gate` 允许目标值上下各 `20%`，对应首日 `8..12`、首周 `16..24`、
  首月 `32..48` 次。当前 `9 / 23 / 36` 三阶段结果全部通过。
- `[x]` 双 Luck 停滞目标已确认。FishLuck 分阶段最大在线停滞为
  `5m / 10m / 20m / 30m`，历史峰值至少相对提高 `1%` 才算有效提升；
  重生恢复独立统计，超过 `90m` 在线时间报警。TrashLuck 分阶段最大在线停滞
  为 `30m / 60m / 2h / 6h`，任意严格增加均算提升，最高档鱼雷已拥有时改记
  “已封顶”。两个 Luck 独立判定，不能互相抵消。
- `[x]` 垃圾佬突破调价后的正式 24h/7d run 为
  `20260726T013137219561Z-day_1_growth` 与
  `20260726T013200487450Z-week_1_growth`，模型摘要
  `sha256:7721a63bd78f573cdd634b327faf0199fd1d7ee95e3a913ca97d8aff4528bfd1`。
  系统级永久进展为 `9 / 23`；同生产输入的 30d 领域运行结果为 36，最高
  境界 14、突破 13 次、垃圾佬转世 4 次。报告见
  `reports/trash-man-breakthrough-balance.md`。
- `[ ]` 输出鱼、废料、金钱和材料每小时产出。
- `[ ]` 输出稀有奖励等待时间 P50/P90/P99。
- `[ ]` 支持同一 checkpoint 分叉比较多种策略。
- `[ ]` 让 `scan` 覆盖 Fish Luban 可调字段。
- `[~]` `report` 已消费 Fish KPI；`compare`、`gate`、Dashboard 和 Agent Analyst 尚待接入。
- `[~]` 首轮价格调参已完成；双 Luck 峰值相对误差 `<=20%` 的允许范围已经
  确认，当前 7d 最大误差 `14.51%` 通过。仍需用长期场景验证 10、11 号鱼雷，
  再进入大规模参数扫描。

## 5. 当前数据状态与阻塞

可用数据：

- `tbfishrandompool`
- `tbbonusfirstlayer`
- `tbmutation`
- `tbbarbell`
- `tbstrengthrebirth`
- `tbfish` 中的基础每秒金钱、稀有度、`Denominator` 和整数克 `weight` 字段
- `tbtorpedo` 中的 25 档 power 与金钱价格
- `tbtrashrandompool` 中的 13 个鱼雷 power 上限区域及对应 `startLuck/endLuck`
- `tbtrash` 中的 39 条基础分解数据
- `tbfishhallupgrade` 中的容量和材料价格
- `tbtrashmanrealm` 中的 60 档境界倍率与修炼时间
- `tbtrashmanrebirth` 中的 10 档转世门槛与倍率

注意：上述 JSON 内已有的数值就是生产模拟基线，必须原样使用；文件“存在且非空”仍不等于已具备完整正式闭环，因为部分业务所需字段和计算规则尚未表达。

正式数据缺口或冲突：

- `[x]` Luban Python 表加载模块位于 `E:\fish-oasis\igess_export\python\schema.py`，配套 JSON 位于 `E:\fish-oasis\igess_export\json`；生产 Fish smoke 已验证，禁止回退到手写业务字段解析。
- `[x]` `tbfish` 的 121/121 行均有唯一正式 `Denominator`；已确认全表就是当前可用鱼池。
- `[~]` FishRandomPool 的 Luck 区间在文字 GDD 与 JSON 间冲突；模拟按 JSON 原值执行，仅文字文档同步待确认。
- `[x]` `tbtorpedo.price` 已由生成表提供并接入购买闭环；2～11 号完成首轮
  双 Luck 纯价格平衡，12 号以后保持当前生产值。
- `[x]` `tbtrash` 的 39/39 行均有唯一正式 `Denominator`；已确认物品级门槛取代旧权重语义并同步 GDD。
- `[!]` 鱼出售缺正式价格口径；出售不进入首个最高收益上阵/金钱产出切片。
- `[x]` 垃圾佬突破价格、在线闭关时长、历史追赶/新境界付费分界和闭关不停产规则已由 `tbtrashmanrealm` 与生产领域实现完整表达；杠铃离线力量为 `0`。
- `[!]` 离线 `24h` 上限、双倍领取成本和临时效果叠加未正式确认。

处理原则：已有字段无条件使用 `E:\fish-oasis\igess_export\json` 原值，并通过同快照的生成 Python 类型读取；接口、状态引擎、checkpoint、事件和策略不等待缺失字段。被阻塞机制可使用显式标记为 `fixture` 的最小配置验证，但 fixture 结果必须标记 `production_data=false`，不能作为生产概率、升级时间、经济节奏或平衡结论。

## 6. 当前里程碑与下一步

当前里程碑：**Phase 8 离线基础、杠铃、鱼厅、鱼升级、两类重生和垃圾佬付费新境界突破的生产画像已完成。默认画像 `daily_online_seconds=7200`；突破与鱼雷/杠铃/鱼厅升级使用权重 `100`，炸鱼/锻炼权重 `1`，鱼升级权重 `0.1`，两类重生达到门槛时硬优先。离线摸鱼厅/废料加工按 50%，杠铃力量为 0，历史追赶和突破均不推进。当前 24h/7d 正式结果和 30d 领域结果已经通过系统永久进展 gate；下一步是超月价格验证、compare/gate/scan、30d 产物压缩，以及 24h 离线上限/双倍领取/临时效果。**

Phase 9 当前新增里程碑：**核心强度与永久养成已经接入正式
JSON/CSV/HTML，并完成 24h/7d 基线。“全部永久进展”的分阶段最大在线空窗
已确认：首小时 30 秒、首日后续 1 分钟、首周后续 2 分钟、首月后续 5 分钟。
“系统级永久进展”的累计次数目标为首日 10 次、首周 20 次、首月 40 次；
20% 允许范围为 `8..12 / 16..24 / 32..48`，当前 `9 / 23 / 36` 全部通过。
FishLuck 和
TrashLuck 的分阶段停滞阈值、有效提升、重生恢复及封顶例外也已确认。下一步
实现同 RNG 策略分叉和这些 KPI 的 compare/gate 消费，并解决 30 天正式产物
体积问题后进入 scan 与正式参数扫描。**

执行顺序：

1. `[x]` 定义领域引擎适配协议和默认适配器。
2. `[x]` 建立 `FishEngineAdapter` / `FishEconomySimulator` 空壳。
3. `[x]` 让最小 Fish fixture smoke 进入 `WorkflowService` 和 `RunRegistry`。
4. `[x]` 生成标准 manifest、timeline、events、analysis。
5. `[x]` 接入 checkpoint 输入/输出和一个 fixture 参数覆盖。
6. `[x]` 接入 Luban 生成的 Python 表加载器，运行并登记 `production_data=true` smoke。
7. `[x]` 完成生产强类型表逐字段契约测试，并验证回归不退化。

Phase 0 已完成，后续顺序：

1. `[x]` 将 RNG 基线收敛为唯一 `resolve_throw()`，完成稳定领域键 RNG 与力量直接插值 Luck 纯函数。
2. `[x]` 将生成的 Luban 表对象适配为 `ThrowRules`，并通过生产一次投掷、标准事件和 checkpoint 防重复恢复验收。
3. `[x]` 确认鱼可用池范围、TrashLuck 区间插值、废料 `Denominator` 三项玩法语义并同步 GDD。
4. `[x]` 投掷领域命令从 PlayerState 锁定力量与已选鱼雷，按生产 `tbfish.weight` 原子写入鱼、废料、统计和 `meta.revision`；图鉴等非数值字段保持不变。新档从生产 `tbtorpedo` 第一行和显式初始力量创建。
5. `[x]` 建立主动投掷最小事件循环，并验证连续十秒与 5+5 秒 checkpoint 分段恢复等价。
6. `[x]` 建立通用加权行为/持续时长/目标调度接口，并以 Fish fixture 验证行为中 checkpoint、手动投掷、单鱼升级、鱼厅升级、杠铃合成和 idle。
7. `[~]` 固定 `max_income` 自动上阵、等级鱼厅收入、鱼升级材料消费、最低价/材料 `1/10` 生产升级画像、生产手动炸鱼和 24h/7d 正式长时验证已完成；等待出售口径后闭合 Phase 4。
8. `[x]` 废料聚合库存、批量加工、境界速度、材料产出、在线历史境界追赶、付费新境界突破与 checkpoint 已完成。
9. `[~]` 交叉升级、两类重生、离线基础和金钱→鱼雷→TrashLuck 已完成；
   默认画像已配置 2h/22h 作息、高优先级鱼雷购买/杠铃合成/鱼厅升级、
   低优先级最低价鱼升级，以及“达到要求立即重生”的两类重生硬优先级。
   24h/7d 正式调价基线与 30d 领域基线已完成，下一步验证 10、11 号鱼雷和
   第 15～60 境界的超月价格，并接入 compare/gate/scan。

## 7. 更新记录

| 日期 | 变更 |
| --- | --- |
| 2026-07-26 | 完成垃圾佬付费新境界突破生产闭环和价格/分解倍率联调：`moneyRequireToNextRealm` 进入强类型适配、原子扣款命令、默认权重 `100`/固定 `1s` 行为、仅在线突破、离线暂停、闭关旧境界不停产、完成事件、checkpoint 和永久进展报表。权威 1～59 号价格严格递增且不低于旧值，60 号为零值哨兵；关键前期价为 `20 / 100K / 5M / 50M / 500M / 100B / 1T`，分解倍率改为 `1 + 1.25×(ID-1)`。正式 run `20260726T013137219561Z-day_1_growth`、`20260726T013200487450Z-week_1_growth` 使用模型摘要 `sha256:7721a63bd78f573cdd634b327faf0199fd1d7ee95e3a913ca97d8aff4528bfd1`，24h/7d 系统进展 `9 / 23`；同生产输入 30d 领域结果 36，三阶段均通过 gate。7d 累计材料约 `10.735M`，较旧曲线约低 `5.5%`。Fish 回归 `116 passed, 3 deselected`，生产表契约 `2 passed`；`TrashManRealm.xlsx`、JSON、Lua 已同步，报告见 `reports/trash-man-breakthrough-balance.md`。 |
| 2026-07-25 | 人类将首月系统级永久进展目标由 25 提高到 40，首日/首周保持 `10 / 20`；20% 包含性 gate 相应改为 `8..12 / 16..24 / 32..48`。当前 30 天基线 21 次不再通过，距离首月下限 32 还差 11 次、距离名义目标还差 19 次，后续需要补第 8～30 日长期系统成长。 |
| 2026-07-25 | 人类同意下调系统级永久进展目标。审计确认当前不含新境界突破的有限系统进展总上限为 79，无法通过旧首月 gate 下限 96；新增 `month_1_growth` 720 小时场景并以相同生产数据、seed 运行 Fish 领域基线，首日/首周/首月累计系统进展为 `8 / 16 / 21`，其中首月分类为鱼雷 12、杠铃 4、力量重生 4、垃圾佬转世 1。当时的新目标定为 `10 / 20 / 25`，20% 包含性 gate 为 `8..12 / 16..24 / 20..30`，已由同日后续首月目标 40、gate `32..48` 取代。正式短期回归 `20260725T071037360301Z-day_1_growth`、`20260725T071055795326Z-week_1_growth` 成功，模型摘要 `sha256:0af70218120e84c76b7fec99f2af64787dd74178709a218bf7aa587c9bd755f5`，系统进展分别为 8、16 次。30 天正式 authoring run `20260725T064849887066Z-month_1_growth` 在大体积 `simulation_artifact` 阶段失败并已保留，领域内存基线成功，说明仍需补月场景产物压缩。报告见 `reports/system-progression-target-rebaseline.md`。 |
| 2026-07-25 | 人类确认杠铃价格必须随 ID 严格递增。3 号杠铃价格由 `750,000` 下调为 `75,000`，前五档变为 `20 / 7,500 / 75,000 / 500,000 / 7,200,000`；`FishBarbellDataAdapter` 新增严格递增契约。正式 run `20260725T061531328157Z-day_1_growth`、`20260725T061546887666Z-week_1_growth` 使用模型摘要 `sha256:6c6dd09c978d8b055bd7f3f8815185a64c25c40ff57ca8a696d991778269291f`。7d 3 号在第 2 天累计在线 `7,202s` 购买，4 号仍为第 5 天 `28,801s`；第三次力量重生由第 5 天提前到第 4 天，系统级永久进展增至 16 次，每日双 Luck 峰值最大相对误差降至 `14.51%`。Fish 回归 `111 passed, 3 deselected`，报告见 `reports/barbell-price-balance.md`。权威源 `Barbell.xlsx` 的 `Barbell!F7` 已同步为 `75`，与 `G7=3` 共同表示 `75,000`，且 JSON/Lua 生成物一致。 |
| 2026-07-25 | 人类确认两项 Phase 9 验收均采用 20% 允许范围。系统级永久进展当时采用的旧范围为首日 16～24、首周 40～60、首月 96～144；当前范围已经重定标为 `8..12 / 16..24 / 32..48`。双 Luck 仍沿用绝对相对误差不超过 20% 的口径。 |
| 2026-07-25 | 人类确认双 Luck 停滞口径：全部只累计在线时间；FishLuck 在首个在线小时、首日剩余时间、第 2～7 日、第 8～30 日的阈值依次为 5/10/20/30 分钟，历史峰值相对上次有效提升至少增长 1% 才重置计时，力量重生恢复期独立统计且超过 90 分钟在线时间报警；TrashLuck 对应阈值为 30/60 分钟、2/6 小时，任意严格增加均算提升，最高档鱼雷已拥有时标记已封顶。两个 Luck 独立判定，不得相互抵消。 |
| 2026-07-25 | 人类最初确认“系统级永久进展”的累计次数目标为首日 20、首周 50、首月 120；该目标因当前机制总量上限不足先下调，当前目标为 `10 / 20 / 40`。 |
| 2026-07-25 | 人类确认“全部永久进展”的阶段性最大在线空窗：首个在线小时不超过 30 秒，首日剩余在线时间不超过 1 分钟，第 2～7 日不超过 2 分钟，第 8～30 日不超过 5 分钟。间隔只累计在线时间；默认 2h/22h 画像按模拟日划分阶段，后续 gate 同时检查相邻事件间隔与阶段尾部空窗。 |
| 2026-07-25 | 完成双 Luck 纯价格平衡：新增 `purchase_torpedo` 领域命令和权重 `100`、固定 `1s`、`highest_affordable` 生产行为；购买只检查未拥有、power 提升和金钱可支付，不读取当前力量或历史最高力量，成功后原子扣款、拥有、自动装备并输出完整 price/money/power/TrashLuck before/after/delta。权威 `tbtorpedo.json` 的 2～11 号价格完成首轮调整。正式 run `20260725T040202603439Z-day_1_growth`、`20260725T040259487026Z-week_1_growth` 成功，模型摘要 `sha256:66017a648f3ccce9ddb100a6e14e6dd54c0ee9e85177172e6859195c9ea42674`；7d 共 8 次购买，分别落在第 1/2/3/4/5/7 天且无同秒或紧邻连跳，TrashLuck 从 3 到 30，每日双 Luck 峰值最大相对误差 `14.83%`，第 6/7 天误差 `0.72%/0.11%`。系统级永久进展增至 15 次，最大/尾部在线空窗降至 `14,330s/7,199s`。Fish 回归 `118 passed, 3 deselected`，报告见 `reports/torpedo-price-balance.md`。 |
| 2026-07-25 | 完成核心强度与永久养成一等报表：正式 Fish run 新增 `luck_progression.json/csv`、`behavior_progression.json/csv` 并登记 manifest，静态 HTML 显示 Strength/FishLuck/TrashLuck 当前值与峰值、重生标记、增长/停滞、永久进展密度、归一化幅度和事件表。捕获新增最佳鱼厅 CPS before/after/delta 与永久标记，单鱼升级明确排除；力量曲线直接消费四位有效数字规范化结算值并与 checkpoint 一致。正式 run `20260725T021336992137Z-day_1_growth`、`20260725T021442047474Z-week_1_growth` 成功；7d 共 94 次永久进展（87 次有效捕获、7 次系统进展），全部/系统最大空窗为 `6256s / 23044s`，系统尾部空窗 `21529s`，TrashLuck 连续 `50400s` 在线时间为 `3`。报告见 `reports/progression-report-baseline.md`；Fish 回归 `115 passed, 3 deselected`，Authoring/checkpoint/输出/报告组合回归 `240 passed`。 |
| 2026-07-24 | 完成生产 24h/7d 长时基线与重生恢复分析：正式 run `20260724T163134465887Z-day_1_growth`、`20260724T164206268531Z-week_1_growth` 成功，模型摘要 `sha256:9876ad1049c75a8c1d65276b972ba02bc8043d66374c51c50050fcc64b655bc6`。7d 共 50,400 个前台行为，发生 3 次力量重生和 1 次垃圾佬转世；三次力量重生均在锻炼达到门槛的同秒立即开始，鱼厅倍率/收入完成后立即生效。新增精确增量 Top-N、最低升级价堆、独占状态结算、普通事件紧凑明细、流式事件 JSON 和周规模 checkpoint 支持；优化前后 24h 除模型摘要外的事件、引擎状态和计数完全相等。报告见 `reports/rebirth-long-term-baseline.md`；最终 Fish 回归 `110 passed, 3 deselected`，checkpoint/输出/Authoring schema 组合回归 `175 passed`。 |
| 2026-07-24 | 人类确认两类重生共用同一条生产规则：只要当前达到相应重生要求，就以硬最高优先级执行。默认画像新增两类固定 `1` 秒重生行为；Fish 候选过滤在任一重生可执行时移除全部普通行为，两种同时满足时连续完成后才恢复普通选择。新增双重生抢占测试；Fish 全量定向回归显式排除既有 RNG CLI 子进程环境用例后为 `104 passed, 4 deselected`。 |
| 2026-07-24 | 人类纠正鱼升级资源口径：鱼升级消耗材料，不消耗金钱。原子命令、事件资源字段、`random_affordable` 和生产 `cheapest_below_material_tenth` 均改读写 `wallet.material`；生产门槛为最低升级价严格低于当前材料 `1/10`。不足材料时即使金钱充足也失败且状态不变；当前 Fish 全量为 `103 passed, 4 deselected`，通用配置回归为 `25 passed`。 |
| 2026-07-24 | 人类确认鱼厅升级也是高优先级行为，鱼升级为低优先级行为；生产 `default` 新增 `upgrade_fish_hall=100` 与 `upgrade_fish=0.1`，均固定 `1` 秒。本日最初曾将鱼升级错误建模为消费金钱并使用金钱 `1/10` 门槛，已由上方最新规则纠正。 |
| 2026-07-24 | 人类确认杠铃升级属于优先行为；生产 `default` 画像新增 `synthesize_barbell=100`、固定 `1` 秒时长和 `random_affordable` 目标策略。合成只从当前未拥有且材料可支付的杠铃中选择，没有目标时自动过滤；普通炸鱼和锻炼仍各为权重 `1`。 |
| 2026-07-24 | 人类确认默认玩家每天在线 2 小时、离线 22 小时后再次上线；`authoring_default.daily_online_seconds=7200`。生产 `default` 画像启用 `manual_throw=1` 与 `exercise_barbell=1` 等权行为，两者均按当前投掷间隔/杠铃 `timeCost` 使用固定 1 秒时长；未拥有杠铃时训练候选自动过滤。 |
| 2026-07-24 | 完成 Phase 8 离线基础首片并纠正杠铃语义：新增 `session_pattern.daily_online_seconds` 每日连续在线窗口、在线/离线事件边界和离线中 checkpoint 重放；摸鱼厅金钱与垃圾佬废料加工离线效率为 50%，垃圾佬修炼不推进。新增互斥前台 `exercise_barbell`，只有在线执行该行为时已装备杠铃才按 `strengthPerExercise/timeCost` 产出力量；合成、炸鱼、其他行为及离线均为 0。定向测试覆盖库存守恒、严格下线、每日窗口和连续/分段等价；当前 Fish 全量为 `102 passed, 4 deselected`。 |
| 2026-07-24 | 完成 Phase 7 垃圾佬转世首片：按新版权威导出确认 `tbtrashmanrebirth.id=1..10` 对应第 1..10 次转世，`completedCount=0` 使用表外 `1×`。新增连续一基表契约、境界门槛/满档/突破保护、原子转世命令、材料永久总倍率 trace 和无目标 `trash_man_rebirth` 行为；命令先按旧倍率统一结算，再重置当前境界/修炼进度并保留历史最高境界、加工队列及其他状态。fixture 覆盖转世后在线追赶、旧新倍率边界和行为中 checkpoint，生产权威表 10 档定向测试通过。 |
| 2026-07-24 | 完成 Fish 超长模块职责拆分并保持公共 API 兼容：`fish_state` 拆为 model/parse/validation/serialization/codec，`fish_trash` 拆为 model/rules/settlement，`fish_commands` 拆为结果 DTO 与 throw/hall/rebirth/barbell 命令，原 2496 行综合测试按领域拆为 7 个测试模块和共享 fixture。Fish 范围已无超过 600 物理行的 Python 文件；原模块的 26/7/16 个公共符号均由兼容门面保留。Fish 测试为 `93 passed, 3 deselected`；仓库全部 53 个测试文件分批回归通过，四组非 Fish 结果为 `513 passed`、`446 passed, 3 skipped`、`163 passed`、`71 passed, 3 skipped, 7 deselected`。 |
| 2026-07-23 | 完成 Phase 7 力量重生首片：确认生产 `tbstrengthrebirth` 是一基 `id=1..10`，`completedCount=0` 使用表外默认 `1×`，下一次门槛读取 `id=completedCount+1`，完成第 `n` 次后使用 `id=n` 的摸鱼厅永久总倍率。新增原子重生命令、总倍率收入/来源 trace 和无目标 `strength_rebirth` 行为；命令先按旧倍率结算统一在线生产，再只清空当前力量并保留其余数值状态。fixture 覆盖门槛不足、满档、行为中 checkpoint 和连续/分段恢复；生产权威表 10 档已验证。 |
| 2026-07-23 | 完成 Phase 6 杠铃表、合成/装备和最初的在线产出链；该日曾把已装备杠铃误建模为后台持续产出并预留离线 50%，此语义已由 2026-07-24 的 `exercise_barbell` 互斥主动行为与离线 0% 规则正式取代。生产 `tbbarbell.price/strengthPerExercise/timeCost`、材料扣款、自动装备最高速度、显式换装及 `synthesize_barbell + random_affordable` 仍保留。 |
| 2026-07-23 | 完成 Phase 6 摸鱼厅材料升级首片：人类确认当前等级行 `upgradePrice` 用于升级到下一行，最终零值行是满级哨兵。生产适配器校验可购买行正价、末行零值和容量严格递增；原子命令使用 BigNumber 扣材料、提升等级/revision，并按 `fixed_max_income` 模拟策略重排。新增无目标行为 `upgrade_fish_hall`，fixture 验证可用性过滤、鱼数量不影响行为概率，以及行为中 checkpoint 不提前扣款、恢复不重抽。生产 `default` 权重仍未配置。 |
| 2026-07-23 | 完成垃圾佬已确认的在线修炼首片：仅在线且最多追赶至历史最高境界，按当前境界行的 `cultivationSecondsToNextRealm` 推进；统一生产结算会按境界边界分段，旧速度结算到边界后才启用新速度。新增修炼/处理 trace，验证 `0s` 境界、封顶、材料变速和行为中 checkpoint 连续/分段等价；瓶颈与资助突破继续保持阻塞。 |
| 2026-07-23 | 完成 Phase 5 基础废料/材料链：生产 `tbtrash`、`tbtrashmanrealm`、`tbtrashmanrebirth` 驱动固定工作量批量加工；鱼厅金钱和垃圾佬材料在同一事务结算。按 `trashId` 稳定排队，支持跨多份废料的解析批处理、小数工作进度 checkpoint、境界变速、转世材料倍率和废料守恒；生产 smoke 已输出非零材料与公式 trace。 |
| 2026-07-23 | 新增 IGESS 通用离散行为调度器：玩家级权重、固定/整数均匀时长、目标池、可用性过滤、idle、三路稳定 RNG 和可序列化运行态。Fish 以 opt-in 双模式接入 `manual_throw / upgrade_fish / idle`，后台鱼厅收入不占行为时间；fixture 验证行为中 checkpoint 恢复不重抽。生产权重、时长和升级目标策略仍待确认，未写入正式配置。 |
| 2026-07-23 | 人类确认鱼升级规则：等级从 1 开始、上限 100；等级 `n` 产出为 `B×1.25^(n-1)×变异倍率`，从 `n` 升到 `n+1` 的价格为 `B×1.5^(n-1)`且不乘变异倍率，统一使用 BigNumber。新增原子扣款/升级命令、升级前后收益 trace 和固定最高收益阵容重排。 |
| 2026-07-23 | 完成 Phase 4-a：生产 `tbfish.baseMoneyPerSecond`、`tbmutation.incomeMultiplier` 和 `tbfishhallupgrade.slotQty` 接入固定最高收益编队；事件循环先结算旧阵容收入再投掷/重排，输出逐鱼公式 trace、CPS 和金钱。生产 10 秒 smoke 得到 `money=98`、`CPS=21`，连续与 `5+5` 秒恢复等价。 |
| 2026-07-23 | 人类确认简化上阵逻辑：模拟始终按单鱼当前每秒收益降序选择容量内前 `N` 条鱼，同收益按 `instanceId` 升序稳定决胜；不再模拟手动编队或 `collector` 上阵策略，缺失的出售价格不阻塞首个鱼厅金钱闭环。 |
| 2026-07-23 | 将生产 single-throw smoke 升级为显式主动投掷循环：初始力量只写入新 PlayerState，投掷时逐次锁定状态快照；`TimeEngine` 增加绝对周期边界，支持事件边界 checkpoint。10 秒连续运行与 5+5 秒恢复的事件、状态和 timeline 等价。 |
| 2026-07-23 | 明确 IGESS 只模拟数值体验：图鉴及其查看/领奖字段等非数值子系统被排除，存档兼容字段仅透传，投掷结算不读写。 |
| 2026-07-23 | `Fish.xlsx`/`tbfish` 新增正整数 `weight`；正式适配器将其按整数克写入 `FishInstance.weightGram`，并新增带投掷序号防重的奖励原子领域命令。生产工作流 checkpoint 现包含鱼实例、废料库存、投掷统计和递增 revision，并校验一次投掷进度的一致性。 |
| 2026-07-22 | 人类确认 `tbfish` 全表即全部可用鱼、TrashLuck 使用与 FishLuck 相同的对数 smoothstep、`tbtrash.Denominator` 取代旧稀有度池内权重随机、新档初始拥有并选中第一行鱼雷；GDD 同步修订，生产 run `20260722T154251033213Z-smoke` 与恢复 run `20260722T154306291059Z-smoke` 通过，Phase 2 标记完成。 |
| 2026-07-22 | 新增生产 Luban 表到 `ThrowRules` 的适配、鱼雷 power→TrashLuck 映射和 IGESS 标准一次投掷事件；正式 run `20260722T125549210389Z-smoke` 成功，恢复 run `20260722T125603035756Z-smoke` 未重复投掷。同步纠正 `tbfish` 121/121、`tbtrash` 39/39 行已有 `Denominator` 的数据状态，并保留三项玩法语义待确认。 |
| 2026-07-22 | TrashRandomPool 字段由 `powerRequirement` 更名为 `powerUpperBound`，明确表示当前鱼雷 power 区域的包含性右端点；Luban JSON/Python/Lua 生成物及生产契约同步更新。 |
| 2026-07-22 | FishRandomPool 字段由含义易混淆的 `strengthRequirement` 更名为 `strengthUpperBound`，明确表示当前力量区域的包含性右端点；FishLuck 改为直接按力量区间插值并保留生产表跳变。 |
| 2026-07-22 | 新增权威 `fish_throw.resolve_throw()` 与稳定领域键 RNG；当日最初采用的“力量→距离→Luck”设计已由上方最新记录修正为直接力量区间插值。 |
| 2026-07-22 | 权威生产目录调整为 `E:\fish-oasis\igess_export`，移除对旧 `gdd/data` 字节一致性的要求；确认 `tbfish.Denominator` 已进入 JSON 和生成类型，当前 14/121 行非空。 |
| 2026-07-22 | 接入 `E:\fish-oasis\igess_export` 的 Luban `schema.py + json` 正式产物；12 表 340 行逐字段契约、生产 smoke、checkpoint 恢复、report 和 compare 通过，Phase 0 标记完成。 |
| 2026-07-22 | Phase 0 核心接入完成：增加领域引擎派发、默认/Fish 适配器、Fish 空壳、标准产物、RunRegistry 元数据、checkpoint、fixture override、report/compare 测试；按团队约定取消手写 Fish JSON 解析，生产 smoke 等待 Luban Python 生成加载器。 |
| 2026-07-22 | 拍定炸鱼正式流程为“力量→距离→FishLuck→BonusChain→FinalFishLuck→FishRollPower”，FishRollPower 不反向影响轨迹。 |
| 2026-07-22 | 曾将 `E:\fish-oasis\gdd\data` 指定为权威数值源并增加一致性约束；该目录决定已被本日最新的 `igess_export` 权威目录记录取代。 |
| 2026-07-22 | 补充 `E:\fish-oasis\gdd` 规则来源、随机/物理/经济/重生/离线数值基线与待人类确认清单；修正“多张 JSON 表为空”的过期描述。 |
| 2026-07-22 | 首次合并 `projects/fish` 建模状态、Fish RNG 计划、玩家存档/checkpoint 进度与历史 HANDOFF；指定本文档为唯一进度源。 |
