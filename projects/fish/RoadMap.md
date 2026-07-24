# Fish 模拟 RoadMap

更新时间：2026-07-24
项目范围：`projects/fish`、`projects/fish-rng` 与 Fish 领域模拟代码  
当前总状态：**Fish 专用引擎已接入 IGESS；鱼厅金钱、垃圾佬材料和已装备杠铃力量已进入同一个原子在线结算。废料加工支持境界变速、批量队列、小数进度 checkpoint 和数量守恒，垃圾佬可在线追赶至历史最高境界。通用玩家行为接口已接通 Fish fixture，材料→摸鱼厅容量、材料→杠铃→力量以及力量重生→摸鱼厅永久总倍率已完成；新境界瓶颈、资助突破、鱼雷购买、垃圾佬转世、离线和长期策略模拟仍未完成**

## 1. 本文档是唯一进度源

本文档统一记录 Fish 的经济规则建模、RNG、玩家存档、模拟器接入、正式场景和数值分析进度。

### 数值体验模拟边界

IGESS 只关注会改变数值体验的资源、概率、时间、产出、消耗、成长曲线、
策略选择和 KPI。图鉴、已查看状态、图鉴奖励领取、表现、教程、通知等非数值
子系统明确不建模，也不得进入领域事件、策略或报表。正式存档 Schema 中为兼容
游戏而保留的无关字段仅做原样透传和结构校验，模拟过程不读取、不修改。

维护规则：

1. 只有本文档维护阶段状态、任务勾选和“下一步”。
2. `projects/fish-rng/FISH_ECONOMY_SIMULATOR_PLAN.md` 保留详细架构与验收背景，不再维护进度标记。
3. `projects/fish-rng/HANDOFF.md` 是 2026-07-20 的历史交接快照，不再作为当前状态依据。
4. `projects/fish-rng/PLAYER_STATE_MODEL.md` 只描述玩家存档模型，不维护项目总进度。
5. 每次完成任务时同时填写证据；没有测试、运行产物或可检查代码的任务不能标记完成。
6. 模拟中的具体数值必须与游戏实际数值完全一致，`E:\fish-oasis\igess_export` 是唯一权威生产快照；正式运行读取其中的 `json\*.json` 和同次生成的 `python\schema.py`，不得用 RoadMap、文字 GDD、旧 `gdd/data`、示例、fixture 或代码默认值覆盖。
7. 具体玩法语义和计算规则到 `E:\fish-oasis\gdd` 查找；文字 GDD 或旧数据副本与 `igess_export/json/*.json` 冲突时，数值无条件以权威导出 JSON 为准，缺失字段、公式歧义和无法由数据表决定的行为再与人类确认。
8. 每次模拟必须记录实际加载的数据目录、文件清单、内容摘要和 `model_digest`，确保结果能追踪到与游戏相同的一版数值。

状态标记：

- `[x]`：完成且已有可检查证据。
- `[~]`：部分完成，尚未达到该项验收标准。
- `[ ]`：未开始或没有可验证成果。
- `[!]`：被正式数据或外部决定阻塞；可用明确标记的 fixture 继续验证机制。

## 2. 当前进度总览

| 工作线 | 状态 | 当前结论 | 证据 |
| --- | --- | --- | --- |
| 通用经济规则原型 | `[~]` | `projects/fish` 已达到 `runnable`，但只有主动活动每秒产生 2 金钱的最小 smoke，不代表正式 Fish 经济 | `economy.yaml`、`changes/`、自动 smoke run |
| RNG 一期基线 | `[x]` | BonusChain、变异、鱼与废料独立随机流已有验证基线；Probe 已复用权威 `resolve_throw()`，FishLuck 直接按力量和 `tbfishrandompool` 插值 | `src/igess/fish_throw.py`、`src/igess/fish_rng.py`、相关测试 |
| PlayerState v1 | `[x]` | 正式存档字段、大数 DTO、严格业务校验、新档和规范 JSON 已实现 | `src/igess/fish_state.py`、`tests/test_fish_state.py` |
| 通用 checkpoint v1 | `[x]` | checkpoint 外壳、digest/engine 校验、原子读写及可选行为运行态已实现；无行为的旧 JSON 形状不变 | `src/igess/checkpoint.py`、`tests/test_checkpoint.py` |
| Fish checkpoint codec | `[x]` | `PlayerState` 可作为 Fish `engine_state` 保存和恢复 | `FishCheckpointCodec` 及定向测试 |
| IGESS Fish 引擎接入 | `[x]` | 领域引擎协议、派发、Luban Python 强类型表、生产 smoke、标准产物、checkpoint 恢复和 compare 已接通 | `src/igess/engines.py`、`tests/test_fish_engine.py`、生产 run `20260722T052544104476Z-smoke` |
| FishEconomySimulator | `[~]` | 鱼厅金钱、垃圾佬材料、在线历史境界追赶和已装备杠铃力量统一结算；旧主动投掷循环保持兼容，加权行为循环支持投掷、鱼升级、摸鱼厅升级、杠铃合成、力量重生和 idle，并由 fixture 验证任意分段恢复不重抽 | `src/igess/fish_production.py`、`src/igess/fish_trash.py`、`src/igess/fish_barbell.py`、`src/igess/fish_behavior*.py`、相关测试 |
| 正式经济闭环 | `[~]` | 鱼厅/金钱、废料/材料、在线历史境界追赶、材料→鱼厅容量、材料→杠铃→在线力量和力量重生→鱼厅永久倍率已接通；鱼雷购买、新境界突破、垃圾佬转世和离线尚未闭合 | Phase 4–8 |
| 正式调参与报告 | `[ ]` | 尚未达到 `ready`，没有 Fish 正式场景、KPI 基线或平衡结论 | Phase 9 |

当前不能把项目描述成“完整 Fish 经济模拟器”。准确口径是：

```text
通用最小经济 smoke 可运行
+ RNG 一期基线已验证
+ PlayerState / checkpoint 基础已完成
+ FishEconomySimulator 已接入生产数据驱动的投掷、鱼厅金钱、废料材料、在线历史境界追赶、摸鱼厅升级、杠铃合成/装备/在线力量、力量重生/鱼厅永久倍率和可选加权行为循环
+ 投掷、鱼升级、摸鱼厅升级、杠铃合成、力量重生及统一在线生产结算状态迁移已实现；新境界瓶颈/突破、鱼雷购买、垃圾佬转世和离线迁移尚未实现
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
   `synthesize_barbell`、`strength_rebirth`、`idle`。摸鱼厅、垃圾佬和
   已装备杠铃持续产出属于后台系统，不进入行为权重，也不占前台时长。
3. 领域适配器先过滤当前不可执行的行为和目标，再对剩余正权重重新归一化；
   鱼数量只影响升级目标池，不得隐式提高 `upgrade_fish` 的行为概率。
4. 行为选择、整数时长和目标选择使用三个独立稳定随机域，键为
   `(root_seed, profile_id, sequence_id, domain)`；输入顺序不改变重放结果。
5. checkpoint 保存 sequence 游标和进行中的完整行为，恢复时不得重新选择行为、
   时长或目标。纯记录边界只临时推导被动收入，不拆分领域结算事务。
6. Fish 当前为单鱼升级和杠铃合成提供显式 opt-in 的 `random_affordable`
   目标策略；相应行为权重大于零时必须明确配置。杠铃目标池只包含当前未拥有
   且材料可支付的 ID，避免玩家行为重复合成不提高产出的库存副本。生产
   `default` 画像的行为权重、持续时长和目标策略尚未配置，不得用 fixture
   数值代替。`upgrade_fish_hall` 是无目标行为，仅在未满级且当前材料足以
   支付时可选；`strength_rebirth` 同样无目标，仅在未满档且当前力量达到
   `tbstrengthrebirth[id=completedCount+1]` 的门槛时可选。

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
2. 鱼等级从 `1` 开始，最高 `100` 级。当前等级为 `n` 时，单鱼升级前的基础秒产出为 `B×1.25^(n-1)`；变异收入倍率在等级倍率之后乘入最终产出。从 `n` 升到 `n+1` 的价格为 `B×1.5^(n-1)`，价格不乘变异倍率。价格、产出和扣款统一使用 BigNumber，不额外做整数取整。
3. 摸鱼厅容量读取 `FishHallUpgrade.slotQty`；当前 JSON 有 `21` 行，容量从 `10` 到 `30`，升级消耗材料。模拟采用顺序映射：`upgradeLevel=0` 读取第一行，等级 `n` 读取第 `n+1` 行；从 `n` 升到 `n+1` 消耗当前第 `n+1` 行的 `upgradePrice`。只有存在下一行时才能升级；最后一行容量 `30`、`upgradePrice=0` 是满级哨兵，不是免费升级。升级命令先按旧容量结算后台生产，再原子扣材料、提升等级和 revision；随后按 IGESS 已锁定的 `fixed_max_income` 模拟策略重排阵容。若后续配置增加显式等级字段，再替换顺序映射。
4. 杠铃消耗材料，当前 `tbbarbell` 有 `15` 档，`strengthPerExercise` 从 `2` 到 `5,000,000`，生产行的 `timeCost` 当前均为 `1` 秒；装备后的在线力量速度为 `strengthPerExercise / timeCost`。只有 `equippedId` 对应的杠铃产出，库存 `count` 不作为倍率。合成先按旧装备结算到命令时刻，再原子扣材料、增加一件库存和 revision，并按固定 `highest_strength_per_second` 策略自动装备当前速度最高的已拥有杠铃；显式换装命令只允许选择已拥有 ID。离线 50% 仍在 Phase 8 实现。
5. 鱼雷消耗金钱并提升废料 Luck；当前 `Torpedo` 表有 `25` 行、power 从 `50` 到 `30B`，但没有价格字段。
6. 废料当前 `39` 行，全部 `baseDecomposeSeconds = 300`；材料基础速度从 `2/s` 到 `10M/s`。Phase 5 v1 将其解释为基础工作量与每单位基础工作材料：每真实秒推进 `decomposeSpeedMultiplier` 单位工作，材料为 `baseMaterialPerSecond × 已消费工作量 × 转世产出倍率`。因此加速缩短耗时但不减少同一废料的基础总材料。
7. 垃圾佬境界当前 `60` 档，`decomposeSpeedMultiplier` 从 `1` 到 `15.75`，每档通常增加 `0.25`；修炼时间字段从 `0s` 到 `36310s`。境界突破费用和瓶颈判定字段尚缺。
8. 已确认的在线修炼首片只负责转世后的历史境界追赶：当 `realmId < highestRealmId` 且没有进行中的突破时，在线时间累加当前境界行的 `cultivationSecondsToNextRealm`；完成后按配置 ID 顺序进入下一境界并清零本境界进度，最多推进至 `highestRealmId`。跨境界的统一生产结算先按旧境界速度结算到边界，再按新境界速度继续处理废料；离线时间不推进，超过历史最高境界的瓶颈/资助规则不在此片内。
9. 资源变化必须先结算到当前服务端时间，再原子执行消费/换装/升级，成功后 `meta.revision += 1`。

#### 3.4.7 重生规则

力量重生只把当前力量归零；垃圾佬转世只把当前境界重置到初始境界。鱼、废料、金钱、材料、鱼雷、杠铃、摸鱼厅升级、垃圾佬非境界升级、历史最高境界和已获得永久倍率默认保留。

当前表基线：

- 力量重生 `completedCount=0` 时使用不在表内的默认 `1×`；生产
  `tbstrengthrebirth` 为一基 ID `1..10`，完成第 `n` 次后使用 `id=n`
  的摸鱼厅总倍率。下一次重生读取 `id=completedCount+1` 的力量门槛；
  共 `10` 档，门槛 `10^3` 到 `10^12`，总倍率 `2×` 到 `11×`。
- 力量重生命令先按旧倍率结算全部后台生产到命令时刻，再原子把
  `wallet.strength` 归零、将 `strengthCompletedCount` 增加到目标表 ID、
  增加 revision 并立即启用新总倍率；其他数值状态全部保留。
- 垃圾佬转世共 `10` 档：表内境界门槛 `0,4,8,...,36`，材料总倍率 `2×` 到 `11×`。
- 垃圾佬转世后仅在线自动修炼至历史最高境界；超过历史最高境界后才重新需要资助突破。
- 自动修炼和闭关期间仍按当前境界处理废料并产出材料。

#### 3.4.8 离线结算

1. 摸鱼厅金钱、垃圾佬材料、杠铃力量均享受离线收益，效率为在线的 `50%`。
2. 垃圾佬自动修炼与突破闭关首版仅在线推进。
3. 离线时长上限目前只有 `24h` 建议值，尚未成为已确认正式配置。
4. 材料离线收益受废料库存限制，不能凭空产生。
5. `lastSettledAt` 是唯一结算锚点；即使超过离线上限也推进到当前服务端时间，防止分次登录重复领取。
6. 普通领取与双倍领取互斥且只能成功一次；双倍领取消耗道具，具体道具/价格尚未确认。

#### 3.4.9 待人类确认清单

- `[~]` `05-a-力量与Luck计算流程.md` 的 FishRandomPool Luck 连续区间（如池 1 为 `1→5`）与当前 `igess_export/json/tbfishrandompool.json`（池 1 为 `1→3`，且多处池间有空档）冲突；模拟数值已明确以权威导出 JSON 为准，需人类确认的只是文字 GDD 是否同步修订。
- `[x]` 已于 2026-07-22 拍定正式流程为 `力量快照→按 strengthUpperBound 右端点选区→区内插值 FishLuck→BonusChain→FinalFishLuck→FishRollPower→鱼结果`；轨迹由最终落点反推，不进入经济结算，废料继续使用独立的 TrashLuck/TrashRollPower 链。
- `[x]` `strengthUpperBound` 是当前区域的包含性右端点；相邻行 Luck 不连续时按权威 JSON 原样保留跳变。
- `[x]` 当前 `tbfish` 121/121 行均已有唯一正式 `Denominator`；已确认 `Fish.xlsx`/`tbfish` 全表就是所有可用鱼，正式结算使用全表门槛池。
- `[x]` 当前 `tbtrash` 39/39 行均已有唯一正式 `Denominator`；已确认物品级门槛正式取代旧的稀有度池内权重随机，`05-核心随机算法.md` 已同步。
- `[!]` `tbtorpedo` 没有购买价格；无法完成“金钱→鱼雷”闭环。
- `[x]` `TrashRandomPool.powerUpperBound` 是当前鱼雷 power 区域的包含性右端点；TrashLuck 正式使用与 FishLuck 相同的对数进度 + smoothstep 区间插值并保留跨行跳变；表现层下探深度不进入经济结算。
- `[x]` 新档初始拥有并选中 `tbtorpedo` 第一行鱼雷；具体 ID 从生成表第一行读取，不在存档工厂中硬编码。
- `[!]` 缺少鱼直接出售价格公式或字段。
- `[x]` 上阵规则已简化为全局固定的最高收益编队：自动选择容量内当前每秒收益最高的鱼，不再比较 `collector`、手动编队或其他上阵策略。
- `[x]` 鱼升级规则已确认：等级 `1..100`；等级 `n` 产出为 `B×1.25^(n-1)×变异倍率`，从 `n` 升到 `n+1` 的价格为 `B×1.5^(n-1)`且不乘变异倍率，统一使用 BigNumber。
- `[x]` 生产 `tbbarbell.timeCost` 已给出每次锻炼秒数，当前 15 行均为 `1`；在线速度按 `strengthPerExercise/timeCost`，只有已装备杠铃产出且库存数量不放大。离线 50% 批量结算留在 Phase 8。
- `[x]` 已于 2026-07-23 确认力量重生表是一基 ID：`completedCount=0` 为表外默认 `1×`；完成第 `n` 次后使用 `tbstrengthrebirth.id=n`，下一次门槛读取 `id=completedCount+1`。
- `[~]` Phase 5 v1 已采用固定工作量公式并用 BigNumber 结算材料；`0` 次转世为 `1×`，第 `n>=1` 次转世暂按表 `id=n-1` 取倍率。该映射需在 Phase 7 实现转世命令前由人类最终确认。
- `[!]` 垃圾佬境界瓶颈、突破金钱成本、闭关时长与普通修炼时间的关系缺少正式字段。
- `[!]` 垃圾佬转世表的 `id=0` 是否表示“第 1 次转世”仍需确认；`realmRequirement=0` 与初始境界 ID 为 `1` 的语义也需确认。
- `[x]` 已于 2026-07-23 确认摸鱼厅顺序映射：当前 `upgradeLevel` 使用当前行价格升级到下一行；最后一行 `upgradePrice=0` 是满级哨兵，不允许免费升级。
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

状态：`[~]`，Schema/codec、投掷、鱼升级和统一生产结算的运行时集成已完成；两类重生等后续状态迁移未完成。

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
- `[~]` 已实现一次投掷的鱼领取、废料入库、统计、鱼升级以及鱼厅金钱/垃圾佬材料统一结算原子事务；鱼升级会扣除金钱、增加等级并重排固定最高收益阵容。鱼出售等领域命令仍待正式口径；图鉴明确不属于 IGESS 模拟范围。
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

状态：`[~]`，主动投掷、加权行为事件循环、后台鱼厅金钱/垃圾佬材料/已装备杠铃力量及在线历史境界追赶均已接入；新境界突破、离线和 buff 等领域事件仍待实现。

- `[~]` `TimeEngine` 已提供 `(start, end]` 绝对周期事件边界，鱼厅、废料加工和历史境界在线追赶已解析跳跃结算；新境界突破等后续领域事件跳跃契约仍待扩展。
- `[~]` 加权模式按“后台金钱/材料/力量/在线修炼结算→前台行为完成→timeline 采样→选择下一行为”稳定排序；突破、离线和 buff 等新增领域事件优先级仍待定义。
- `[x]` 通用 `BehaviorScheduler` 已实现玩家级权重、固定/整数均匀时长、可用性过滤、目标选择、`idle` 和三路稳定 RNG。
- `[x]` Fish 已接入 `manual_throw / upgrade_fish / upgrade_fish_hall / synthesize_barbell / strength_rebirth / idle`；fixture 已验证权重、持续时长、单鱼升级与杠铃合成目标策略、无目标鱼厅升级/力量重生和行为中 checkpoint。生产 `default` 画像尚未启用，慢速自动炸鱼仍属于后续独立行为。
- `[~]` 已支持废料加工和不超过历史最高境界的在线自动修炼；新境界瓶颈、资助突破和 buff 过期事件尚未实现。
- `[x]` 旧主动投掷模式支持事件边界 checkpoint；加权行为模式可在行为中间 checkpoint，恢复时继续已保存行为而不重抽。
- `[ ]` 验证连续 24 小时与两个 12 小时恢复运行一致。
- `[ ]` 验证 tick 与事件跳跃模式结果一致。

### Phase 4：鱼、摸鱼厅和金钱闭环

状态：`[~]`，固定最高收益编队、等级收入、容量、金钱结算、鱼升级扣款和 trace 已接入；行为机制已由 fixture 验证，生产玩家权重、时长和目标策略以及出售口径仍待确认。

目标链路：`炸鱼 -> 鱼实例 -> 自动最高收益上阵 -> 鱼厅产出金钱 -> 金钱消费`。

- `[~]` 已实现鱼背包、领取、升级和固定最高收益鱼厅栏位事务；出售等待正式价格口径。
- `[x]` 接入基础金钱产出、等级 `×1.25^(n-1)` 曲线与变异收入倍率。
- `[x]` 已接入鱼升级价格 `B×1.5^(n-1)`、BigNumber 扣款、100 级上限和升级后自动重排；fixture 中的 `random_affordable` 从当前可支付、未满级目标中稳定随机选择。
- `[x]` 实现鱼厅容量、收入计算和公式 trace。
- `[x]` 实现全局固定的 `max_income` 自动编队：按单鱼当前每秒收益降序填满容量，同收益按 `instanceId` 升序决胜；不再实现 `collector` 上阵策略。
- `[x]` 用解析公式验证固定阵容累计金钱，并验证连续 10 秒与 `5+5` 秒 checkpoint 恢复等价。

### Phase 5：废料、垃圾佬和材料闭环

状态：`[~]`，废料库存、批量加工、材料产出、境界速度、转世材料倍率、在线历史境界追赶和 checkpoint 已接入；新境界瓶颈和资助突破尚未实现。

目标链路：`炸鱼 -> 废料库存 -> 垃圾佬加工 -> 材料`。

- `[x]` 实现废料聚合库存和按 `trashId` 升序的批量加工队列；活动目标仍包含在聚合库存中，完成时才扣除。
- `[x]` 实现境界分解速度、转世材料倍率与固定基础工作量；材料按实际消费工作量连续产出。
- `[~]` 已实现仅在线、最多追赶至 `highestRealmId` 的自动修炼；按当前境界的 `cultivationSecondsToNextRealm` 推进，跨境界先结算旧速度再启用新速度，行为中途 checkpoint 不拆分提交。超过历史最高境界的瓶颈和资助突破等待正式费用/触发规则。
- `[x]` 验证废料数量守恒、批量跨物品结算、变速后的剩余工作量和同一废料总产量不漂移。
- `[x]` 小数基础工作进度保存在 checkpoint 的 `engine_runtime_state`，不修改生产 PlayerState v1 的整数 `activeProgressSeconds` 字段。
- `[x]` 主动投掷和加权行为循环均在前台命令前原子结算鱼厅金钱与垃圾佬材料；timeline 可临时推导但不拆分事务。

验证证据：`tests/test_fish_throw_data.py`、`tests/test_fish_engine.py`、`tests/test_fish_state.py`、`tests/test_fish_rng.py`、`tests/test_checkpoint.py`、`tests/test_behavior.py` 和 `tests/test_behavior_config.py` 定向回归 `118 passed, 3 deselected`；生产快照字段契约定向测试 `1 passed`。覆盖境界边界前后材料速度、首境界 `0s` 需求、历史最高境界封顶、行为中途 checkpoint 不提前提交，以及连续/分段恢复等价。

### Phase 6：升级和交叉养成

状态：`[~]`，材料升级摸鱼厅容量与材料合成杠铃/在线产出力量均已完成生产表适配、原子扣款、行为接入和 checkpoint；鱼雷购买与垃圾佬新境界突破仍受正式数据或规则缺口阻塞。

目标链路：

```text
金钱 -> 鱼雷 / 垃圾佬突破
材料 -> 鱼厅 / 杠铃
杠铃 -> 力量 -> FishLuck
鱼雷 -> TrashLuck
```

- `[ ]` 实现鱼雷购买、拥有和选用。
- `[x]` 实现鱼厅升级：当前等级行价格、末行零值满级哨兵、BigNumber 材料扣款、容量立即生效、`fixed_max_income` 重排和 `upgrade_fish_hall` 无目标行为均已接入。
- `[x]` 实现杠铃合成、显式装备与在线力量持续产出：价格消耗材料，速度为 `strengthPerExercise/timeCost`，仅装备项产出，库存数量不放大；合成后固定自动装备最高每秒力量。
- `[ ]` 实现购买、合成策略以及等待时间/回本报告。
- `[~]` 已验证鱼升级严格消费金钱、鱼厅升级和杠铃合成严格消费材料且失败不修改状态；鱼雷购买和垃圾佬突破等待对应规则完成。

验证证据：Fish/行为/checkpoint 定向回归 `125 passed, 3 deselected`；生产快照定向测试 `3 passed`；仓库完整回归 `1281 passed, 6 skipped, 10 deselected`。覆盖鱼厅当前行价格、BigNumber 扣款、末行零值哨兵、容量严格递增、杠铃生产表 15 档与 `timeCost`、仅装备项产出、库存数量不放大、旧装备先结算再换装、材料不足失败不修改状态、`fixed_max_income` 扩容重排、两类行为目标策略及行为中 checkpoint 连续/分段恢复等价。

### Phase 7：重生和永久成长

状态：`[~]`，力量重生事务、摸鱼厅永久总倍率、无目标行为和 checkpoint 已完成；垃圾佬转世、重生策略与回本分析尚未实现。

- `[x]` 实现力量重生及摸鱼厅永久倍率：`0 次=表外 1×`，完成第 `n` 次后读取 `tbstrengthrebirth.id=n`；命令先结算旧倍率，再仅清空当前力量并立即启用新总倍率。
- `[ ]` 实现垃圾佬转世及材料永久倍率。
- `[ ]` 实现历史最高境界与转世后在线追赶。
- `[ ]` 实现重生策略与回本分析。
- `[~]` 已验证力量重生只重置 `wallet.strength`，其他数值状态保留；垃圾佬转世的重置项和保留项仍待实现验证。

验证证据：Fish/行为/checkpoint 定向回归 `130 passed, 3 deselected`；生产权威快照与 Fish 标准工作流外部测试 `3 passed`。Python 3.11 仓库回归为 `1283 passed, 8 skipped, 10 deselected`，另有 `1` 个既有 RNG CLI 用例因该解释器未安装项目依赖 PyYAML 而在收集后的子进程运行失败；同一失败集在依赖完整的当前环境中除 Python 3.10 不支持的 6 个 `Exception.add_note` 用例外均通过。覆盖一基表契约、表外默认 `1×`、门槛不足/满档失败不修改状态、旧倍率先结算、只清力量、永久总倍率 trace、无目标行为可用性以及行为中 checkpoint 连续/分段恢复等价。

### Phase 8：离线、临时效果和长期模拟

状态：`[ ]`。

- `[ ]` 实现在线会话与离线区间。
- `[ ]` 实现统一 `lastSettledAt` 结算锚点且不能重复领取。
- `[~]` GDD 已明确离线效率为在线 `50%`；`24h` 上限、双倍道具和临时效果叠加仍待确认。
- `[ ]` 实现离线时长上限、废料库存约束与批量结算。
- `[ ]` 实现临时 Luck、速度、金钱和材料效果。
- `[ ]` 验证跨 buff 过期点积分与长时间事件跳跃。

### Phase 9：策略比较和数值报告

状态：`[ ]`。

- `[ ]` 输出资源、能力、升级、重生和关键阶段时间线。
- `[ ]` 输出鱼、废料、金钱和材料每小时产出。
- `[ ]` 输出稀有奖励等待时间 P50/P90/P99。
- `[ ]` 支持同一 checkpoint 分叉比较多种策略。
- `[ ]` 让 `scan` 覆盖 Fish Luban 可调字段。
- `[ ]` 让 `compare`、`gate`、`report`、Dashboard 和 Agent Analyst 消费 Fish KPI。
- `[ ]` 建立正式场景与 KPI 基线后才开始平衡性结论和调参。

## 5. 当前数据状态与阻塞

可用数据：

- `tbfishrandompool`
- `tbbonusfirstlayer`
- `tbmutation`
- `tbbarbell`
- `tbstrengthrebirth`
- `tbfish` 中的基础每秒金钱、稀有度、`Denominator` 和整数克 `weight` 字段
- `tbtorpedo` 中的 25 档 power
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
- `[!]` `tbtorpedo` 缺购买价格。
- `[x]` `tbtrash` 的 39/39 行均有唯一正式 `Denominator`；已确认物品级门槛取代旧权重语义并同步 GDD。
- `[!]` 鱼出售缺正式价格口径；出售不进入首个最高收益上阵/金钱产出切片。
- `[!]` 垃圾佬突破费用/瓶颈规则仍不完整；杠铃的在线锻炼周期与材料价格已由当前生产 `tbbarbell` 完整表达，离线效率在 Phase 8 统一接入。
- `[!]` 离线 `24h` 上限、双倍领取成本和临时效果叠加未正式确认。

处理原则：已有字段无条件使用 `E:\fish-oasis\igess_export\json` 原值，并通过同快照的生成 Python 类型读取；接口、状态引擎、checkpoint、事件和策略不等待缺失字段。被阻塞机制可使用显式标记为 `fixture` 的最小配置验证，但 fixture 结果必须标记 `production_data=false`，不能作为生产概率、升级时间、经济节奏或平衡结论。

## 6. 当前里程碑与下一步

当前里程碑：**Phase 7 力量重生首片已完成。`completedCount=0` 明确使用表外默认 `1×`，下一次读取生产 `tbstrengthrebirth.id=completedCount+1` 的门槛，完成第 `n` 次后使用 `id=n` 的摸鱼厅永久总倍率。重生命令先按旧倍率结算在线金钱/材料/力量，再仅清空当前力量并原子提交计数、revision 和新倍率；`strength_rebirth` 无目标行为及行为中 checkpoint 已接通。下一条是垃圾佬转世→材料永久总倍率，但实施前仍需人类确认零基 `tbtrashmanrebirth.id=0` 与初始境界 `realmId=1` 的门槛语义。生产玩家画像仍需另行配置后才能开展长时经济节奏分析。**

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
7. `[~]` 固定 `max_income` 自动上阵、等级鱼厅收入和鱼升级金钱消费已完成；等待生产行为画像、正式长时场景验证与出售口径后闭合 Phase 4。
8. `[~]` 废料聚合库存、批量加工、境界速度、材料产出、在线历史境界追赶与 checkpoint 已完成；新境界瓶颈和资助突破待正式规则。
9. `[~]` 交叉升级已完成材料→鱼厅容量、材料→杠铃→在线力量和力量重生→鱼厅永久总倍率；鱼雷购买与垃圾佬突破受正式字段/语义阻塞。确认垃圾佬转世零基表与境界门槛语义后，继续垃圾佬转世、离线闭环、正式场景、策略比较、KPI 和调参回归。

## 7. 更新记录

| 日期 | 变更 |
| --- | --- |
| 2026-07-24 | 完成 Fish 超长模块职责拆分并保持公共 API 兼容：`fish_state` 拆为 model/parse/validation/serialization/codec，`fish_trash` 拆为 model/rules/settlement，`fish_commands` 拆为结果 DTO 与 throw/hall/rebirth/barbell 命令，原 2496 行综合测试按领域拆为 7 个测试模块和共享 fixture。Fish 范围已无超过 600 物理行的 Python 文件；原模块的 26/7/16 个公共符号均由兼容门面保留。Fish 测试为 `93 passed, 3 deselected`；仓库全部 53 个测试文件分批回归通过，四组非 Fish 结果为 `513 passed`、`446 passed, 3 skipped`、`163 passed`、`71 passed, 3 skipped, 7 deselected`。 |
| 2026-07-23 | 完成 Phase 7 力量重生首片：确认生产 `tbstrengthrebirth` 是一基 `id=1..10`，`completedCount=0` 使用表外默认 `1×`，下一次门槛读取 `id=completedCount+1`，完成第 `n` 次后使用 `id=n` 的摸鱼厅永久总倍率。新增原子重生命令、总倍率收入/来源 trace 和无目标 `strength_rebirth` 行为；命令先按旧倍率结算统一在线生产，再只清空当前力量并保留其余数值状态。fixture 覆盖门槛不足、满档、行为中 checkpoint 和连续/分段恢复；生产权威表 10 档已验证。 |
| 2026-07-23 | 完成 Phase 6 杠铃在线链：生产 `tbbarbell.price/strengthPerExercise/timeCost` 强类型适配，在线速度为每次力量除以锻炼秒数；仅已装备杠铃产出，库存数量不放大。合成命令先结算旧装备，再原子扣材料、增加库存/revision，并固定自动装备最高每秒力量；保留显式已拥有换装命令。新增 `synthesize_barbell + random_affordable` 行为，只选择未拥有且可支付目标；fixture 覆盖材料不足不变、旧新装备结算顺序和行为中 checkpoint。离线 50% 留在 Phase 8。 |
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
