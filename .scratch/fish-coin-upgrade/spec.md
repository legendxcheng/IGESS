# Fish 金币升级与上阵鱼培养策略

Status: ready-for-agent
Type: spec
Confirmed: 2026-09-16
Implementation: completed

## Problem Statement

实际 Fish 项目已将普通鱼升级从消耗材料改为消耗金币，而 IGESS 仍用材料判定可支付、执行扣款、筛选升级目标并记录事件。只刷新导表快照不会更新这些代码规则，数值策划得到的资源余额、杠铃购买时点和成长节奏会与实际游戏不符。

旧画像从全背包挑最便宜的鱼升级，还可能投入未上阵、无法即时增加鱼厅收入的鱼。用户希望模拟主动培养高品质鱼的玩家：培养对象覆盖鱼厅可用的普通鱼名额，优先补齐低等级，兼顾下一把杠铃的购买。

当前导表快照还包含神兽，模拟器却将其按普通鱼放入投掷池、计算固定产出并允许升级。即使本轮只研究普通鱼，也必须隔离这一不支持的机制，避免它污染正式运行。

## Solution

将普通鱼升级的规则、玩家策略、金币账本和调优报告一并同步至确认后的模型，继续使用既有 IGESS 正式运行流程。

升级目标依次按以下规则确定：以鱼厅容量减上阵神兽数得到普通鱼名额 X；从全背包选出鱼品质最高的前 X 条普通鱼；只保留当前已上阵、未满级的鱼；选择其中等级最低的一条。鱼品质指一级产出，包含变异倍率。未上阵鱼不接受追赶投入；金币不足时攒钱，不改买其他便宜升级。

玩家继续交替炸鱼、锻炼和升级，每次只升一级，耗时 3 秒，升级基础权重为 1。金币投资围绕下一把训练更快、价格最低的未拥有杠铃安排：买得起就优先购买；尚买不起时，仅执行预计能缩短攒钱时间的鱼升级。没有更强杠铃可买后，继续按既定目标规则培养。

本轮正式场景限定为普通鱼，不模拟神兽获取与收益联动；神兽不得升级。模型应交付可追溯的新运行和清晰的适用范围，供策划评估金币投入对产出和其他成长系统的影响。

## User Stories

1. As a game designer, I want ordinary fish upgrades to spend coins, so that simulated resource flows match the current game.
2. As a game designer, I want fish upgrade prices and income curves to remain unchanged, so that this migration does not silently rebalance the game.
3. As a game designer, I want mutation multipliers included in first-level income and upgrade prices, so that fish quality and costs use the actual rules.
4. As a game designer, I want fish quality measured by first-level income, so that an already upgraded fish is not mistaken for a higher-quality fish.
5. As a game designer, I want the cultivation group sized to hall capacity minus deployed beasts, so that ordinary fish investment matches the available hall slots.
6. As a game designer, I want the cultivation group selected from all owned ordinary fish, so that the strategy recognizes newly caught high-quality fish.
7. As a game designer, I want individual fish instances counted separately, so that multiple valuable fish of the same species can be cultivated.
8. As a game designer, I want upgrades limited to currently deployed members of that group, so that each selected upgrade has an immediate income-producing role.
9. As a game designer, I want undeployed fish excluded even when one upgrade would let them enter the hall, so that the player does not make speculative catch-up investments.
10. As a game designer, I want undeployed new fish to leave other eligible deployed fish selectable, so that a low-level newcomer does not block ongoing cultivation.
11. As a game designer, I want the lowest-level eligible fish selected first, so that investment does not concentrate indefinitely on one high-level fish.
12. As a game designer, I want higher-quality fish preferred when eligible levels are equal, so that quality remains a meaningful priority.
13. As a game designer, I want existing level investment preserved at equal-quality group boundaries, so that identical new catches do not repeatedly displace cultivated fish.
14. As a game designer, I want the selected fish retained when its upgrade is unaffordable, so that saving is not diverted to cheaper alternatives.
15. As a game designer, I want fish outside the top-quality group excluded from upgrades, so that spare funds do not leak into unwanted cultivation.
16. As a game designer, I want max-level fish to retain their group slots, so that reaching the cap does not expand the intended cultivation group.
17. As a game designer, I want target selection recomputed after relevant inventory and hall changes, so that upgrades follow the current player state.
18. As a game designer, I want no upgrade selected when the eligible group is empty, so that the player can continue other activities without invalid actions.
19. As a game designer, I want each simulated upgrade to add one level, so that human convenience buttons do not require a separate economic model.
20. As a game designer, I want upgrades to take three seconds and use a base behavior weight of one, so that cultivation alternates with other player activities.
21. As a game designer, I want the next barbell chosen as the cheapest unowned improvement in training speed, so that the coin-saving objective is explicit.
22. As a game designer, I want an affordable target barbell purchased before spending coins on fish, so that upgrades do not postpone an already available purchase.
23. As a game designer, I want unaffordable barbell targets to admit only fish upgrades that shorten estimated saving time, so that income investment supports the next training improvement.
24. As a game designer, I want upgrade time and current income multipliers included in that estimate, so that the spending decision reflects the modeled action and player profile.
25. As a game designer, I want the saving estimate identified as a current-state heuristic, so that it is not mistaken for a guarantee about future random outcomes.
26. As a game designer, I want cultivation to continue after all useful barbells are owned, so that the barbell budget condition does not permanently disable fish upgrades.
27. As a simulation maintainer, I want insufficient coins and invalid upgrade requests to leave state unchanged, so that transactions remain atomic.
28. As a simulation maintainer, I want beasts rejected by upgrade commands and excluded from ordinary-fish scenarios, so that unsupported rules cannot produce plausible but incorrect results.
29. As a simulation maintainer, I want player policy restrictions separated from game command rules, so that ordinary inventory fish remain valid game objects even when the simulated player chooses not to upgrade them.
30. As a simulation maintainer, I want mid-action checkpoint recovery to preserve the selected action, so that upgrades are neither charged early nor repeated after recovery.
31. As an execution planner, I want complete and compact event outputs to retain the coin ledger, so that long simulations remain auditable.
32. As an execution planner, I want upgrade spending, actual hall income gains and barbell purchase times visible in the tuning report, so that I can assess the economic effect of this change.
33. As a game designer, I want both default and paid profiles to use the same confirmed decision rules, so that profile comparisons isolate their existing reward differences.
34. As an execution planner, I want each formal run to identify its input snapshot, model and supported scope, so that results can be traced to the rules and data actually used.
35. As a game designer, I want new daily, weekly and monthly baselines with historical results preserved, so that changed rules are not judged against obsolete expectations.
36. As a simulation maintainer, I want validation through the existing formal workflow, so that the feature works with registration, artifacts, reports and recovery rather than only as isolated domain logic.

## Implementation Decisions

### 游戏规则与玩家策略分离

- 普通鱼升级统一消费金币，每次增加一级，等级上限保持 100。神兽禁止升级，在命令和策略两层均执行。
- 鱼品质是普通鱼的一级产出 P0，等于鱼种基础产出乘变异倍率。等级 L 的产出为 P0 × 1.25 的 L−1 次方；本级升级价格为 P0 × 1.5 的 L−1 次方。使用现有大数计算，不按展示精度提前取整。
- 鱼升级完成前按旧等级、旧阵容结算至命令时间；成功后原子扣金币、提高等级、更新 revision 并按当前实际收益重排上阵。失败不提交部分状态。
- “只升级已上阵鱼”属于生产玩家策略，不能错误地变成普通鱼原子命令的通用禁令。普通背包鱼在实际游戏中仍允许升级；本轮玩家策略不会发起该行为。
- 鱼厅扩容、鱼雷和境界突破的材料消费，以及杠铃的金币消费，沿用现有规则。收益倍率只影响入账，不改变升级价格。
- 本轮不改变玩家存档的金币、材料或鱼等级字段，不补偿历史升级投入，不自动重置玩家成长。

### 目标选择顺序

1. 使用当前鱼厅容量减去当前已上阵神兽数量得到 X。前 X 条按鱼实例计数，不按鱼种去重；普通鱼不足 X 条时取全部。
2. 对全背包普通鱼按鱼品质降序取前 X 条。品质相同先保留等级更高的鱼，再按实例身份升序稳定决胜。
3. 与当前已上阵鱼取交集，并排除满级鱼。必须先取前 X 再做交集，不能改成对所有上阵鱼直接排序，也不能先过滤未上阵鱼再用组外鱼补足 X。
4. 在交集中按等级升序选择目标；同等级按品质降序，再按实例身份升序决胜。
5. 选定目标后才判定金币和杠铃资金条件。目标不可支付或不满足资金条件时，本轮不升级，不转选便宜、等级更高或品质更低的替代鱼。
6. 前 X 中的满级鱼保留名额。X 为零、没有普通鱼或交集中没有未满级鱼时，没有升级候选。
7. 未上阵的新鱼不接受任何铺垫升级，也不以其低等级阻塞交集中其他鱼。捕获、扩容、升级、上阵变化后重新计算有效目标。
8. 目标排名若使用缓存，必须与上述全量规则等价。现有单纯最低价格排序的缓存不能继续作为生产策略的依据。

### 杠铃目标与金币安排

- 下一目标是未拥有、训练速度严格高于当前装备的最低价杠铃；训练速度使用每次力量收益除以训练耗时。购买后更新目标，保留既有装备逻辑。
- 金币足够购买目标杠铃时，禁止本轮鱼升级抢先花掉金币。仍保留既有重生、突破及非金币系统的调度优先关系；不能只依赖较大行为权重来近似这条资金约束。
- 金币不足以购买目标杠铃时，只有选定鱼当前可支付且升级预计严格缩短杠铃攒钱时间，才允许升级。预计时间相等或更长均不升级。
- 估计使用当前在线鱼厅实际金币速率，含当前永久倍率和画像倍率；计入三秒升级期间的旧产出。升级后增收使用鱼厅总收入的实际变化，而非单鱼展示值。
- 设当前金币为 M、杠铃价格为 K、升级价格为 C、当前在线金币速率为 R、升级后速率增量为 D、操作时长为 d。不升级的预计等待是零与 (K−M)÷R 中较大者；升级后的预计等待是 d，加上零与 [K−(M+R×d−C)]÷(R+D) 中较大者。生产画像 d 为三秒。
- 存在待购买目标时，要求 R 和 D 为正，且升级后预计等待严格小于不升级预计等待。零产出不得通过默认值或除零结果放行。
- 该估计是每次决策时的静态在线启发式，不预测未来捕鱼、重生、其他消费或离线切换，不使用未来随机结果，不承诺真实购买时点必然提前。正式模拟仍执行既有在线与离线规则。
- 已无未拥有且更强的杠铃时，取消该等待时间门槛，继续执行鱼目标选择、当前金币可支付判定和行为调度。
- 移除生产画像原有的材料余额十分之一门槛，不额外引入金币余额十分之一限制或固定预留比例。

### 行为、接口与模块责任

- 默认画像与现有付费画像均采用新鱼升级策略和新杠铃目标策略。升级基础权重从 0.1 改为 1，每次持续三秒，继续与炸鱼和锻炼交替，不引入独立自动升级循环。
- 保留每日在线窗口、离线产出、其他行为时长、既有重生与突破优先规则，以及两画像各自的收益倍率。
- 领域命令负责合法性与原子扣款；鱼厅计算负责价格、品质和实际阵容收益；行为适配负责目标池、资金判定及调度；画像配置声明所选策略。不得让策略直接修改玩家状态。
- 同步升级结果对象、完整事件和紧凑事件中的资源标签及余额契约，使其明确表示金币消费。旧策略的名称、验证和生产引用必须一致处理，不能把仍名为材料策略的配置静默解释为金币策略。
- 新策略的确定性决胜不得引入不必要的随机抽样。checkpoint 沿用既有进行中行为保存机制，恢复时不重新选择目标、动作时长或随机结果。
- 沿用现有模型摘要与 checkpoint 校验，不让新旧消费规则在不匹配模型下静默混跑。

### 神兽与生产数据边界

- 普通鱼正式场景排除神兽获取及产出模拟，神兽不进入普通鱼投掷池和升级目标池；不能继续把神兽按固定收入普通鱼处理。
- 使用导表快照已有的明确分类语义识别普通鱼与神兽，不依赖四个已知神兽 ID 的硬编码。新增神兽不能绕过限制。
- 含神兽的玩家状态或 checkpoint 不得在本轮场景中被伪装为完整支持；在实际消费不支持规则之前给出明确诊断，不删除或修改玩家原始状态来继续运行。
- 前 X 规则的定义保留对上阵神兽数量的扣除；本轮无神兽正式场景中该数量为零。这不代表已经实现神兽获取或收益联动。
- 继续读取同次生成的强类型表与 JSON，遵守依赖范围校验；仅存在额外未使用表或神兽记录不应阻塞普通鱼场景。
- 保留输入原始内容及哈希，规则过滤发生在模型内，不篡改导表快照。运行与报告明确其普通鱼适用范围，不能把生产数据来源等同于完整游戏机制覆盖。

### 正式运行、账本与报告

- 沿用正式运行、领域引擎、运行历史库和标准产物管线，不创建第二套模拟入口或报告体系。
- 完整和紧凑事件均保留足以审计的升级目标、升级前后等级、价格、金币余额前后和鱼厅实际增收；金币支出不能在周/月事件压缩后丢失。
- 调优报告呈现鱼升级金币支出、鱼厅产出变化、有效增收升级比例和杠铃购买时点，并结合既有力量、FishLuck、TrashLuck、鱼雷与境界进展判断连带影响。
- 单鱼升级继续不计入系统永久进展。不能为改善该指标而重定义升级事件类别。
- 每次正式运行记录导表快照来源、内容哈希、模型摘要、画像、场景、随机种子与适用范围。保留所有既有历史结果。
- 当前规则说明需同步金币流与含变异的价格口径；历史日志保留历史语境。实施进度继续由既有 RoadMap 统一维护。
- 遵守既有执行工具包分发与源码隔离 ADR；本次不改变分发架构，不发布新执行工具包。

## Testing Decisions

### 测试边界

沿用用户已确认方案中的现有边界，不新增测试专用接口。主要验收边界是正式工作流：输入项目、导表快照、画像、场景及可选 checkpoint，观察运行结果、事件、最终玩家状态、运行登记和报告。精确交易失败与边界算例使用已有领域命令入口补充，不为每个缓存、排序帮助函数或分支分别建立测试边界。

好测试断言外部行为与资源守恒，不断言私有调用次数、堆的形状、缓存键或实现函数拆分。小型显式 fixture 用于构造边界；正式数值结论必须来自生产数据，不能用 fixture 替代。

### 既有先例与覆盖模块

- 既有 Fish 工作流测试已覆盖引擎派发、运行登记、产物、checkpoint、比较及报告失败保留证据，作为主验收先例。
- 既有鱼厅命令测试已覆盖价格公式、原子消费、失败不变和收益重排，作为币种迁移的精确测试入口。
- 既有行为测试已覆盖升级前旧收益结算、目标策略配置与动作中 checkpoint；沿用相同边界验证新候选策略。
- 既有长场景测试已覆盖复制事务与原地事务等价、紧凑事件；既有鱼厅缓存测试已覆盖追加鱼和升级后的全量排名等价。
- 覆盖正式运行编排、Fish 数据适配、鱼厅及升级命令、行为决策、杠铃选择、checkpoint 和报告，不增加平行的正式模拟实现。

### 必须验证的外部行为

| 范围 | 验收要求 |
| --- | --- |
| 消费资源 | 金币不足而材料充足时失败；金币足够时只扣金币，材料不变；恰好付清成功且余额不负数。 |
| 原子性 | 未知鱼、满级或神兽升级失败时，钱包、等级、revision 和上阵状态保持不变。 |
| 价格与收益 | 含变异、不同等级和大数边界与实际公式一致；升级先结算旧收益，再产生新收益。 |
| 前 X 范围 | 按鱼品质选全背包前 X 个实例；同种鱼可占多个名额；不能以当前等级产出或稀有度替代品质。 |
| 上阵交集 | 只升级前 X 与当前上阵的交集；未上阵新鱼不升级也不阻塞其他交集候选；升后能上阵不能冒充当前已上阵。 |
| 排序与储蓄 | 最低等级优先；同级优先品质；同品质边界保留等级投入；目标不可支付时不改选便宜鱼。 |
| 空集与满级 | X 为零、普通鱼不足 X、交集为空及交集全部满级均正确；满级鱼的名额不被组外鱼补位。 |
| 动态变化 | 捕获高品质鱼、鱼厅扩容、等级和上阵变化后，行为结果与全量规则一致且可重放。 |
| 杠铃目标 | 排除已拥有及训练速度不更快的档位，选择最低价有效目标，购买后更新。 |
| 金币优先 | 已可支付的目标杠铃不被鱼升级抢走预算；已有重生和突破优先规则保持有效。 |
| 等待估计 | 严格改善、相等、恶化分别放行或拒绝；包含三秒旧产出和实际画像倍率；零产出不错误放行。 |
| 杠铃终局 | 没有更强未拥有杠铃后，仍可培养已上阵目标鱼，不需要虚构下一目标。 |
| 行为时间 | 单次只升一级、三秒提交；期间不同时锻炼；画像权重为 1，既有在线/离线窗口有效。 |
| 两种画像 | 默认与付费画像使用相同规则；收益倍率正确影响入账和等待估计，不乘消费价格。 |
| checkpoint | 连续运行与动作中分段恢复的事件和最终状态等价，无提前扣款、重复升级或重选目标。 |
| 神兽范围 | 普通鱼场景不会捕获或升级神兽，不生成神兽固定收入；额外神兽配置可存在，含神兽存档明确诊断。 |
| 账本与报告 | 完整与紧凑事件的金币支出、余额和增收可核对；单鱼升级不计入系统永久进展。 |
| 来源与失败 | 生产数据来源、输入哈希、模型摘要和普通鱼范围可追溯；报告失败保留证据且正式运行失败。 |

### 正式验证与基线

- 完成上述定向回归后，通过标准工作流运行生产 smoke 和一天场景；不得仅凭领域函数成功宣布迁移完成。
- 使用确认后的模型及生产快照重建一周和一月基线，保持既定随机种子、在线模式与画像口径。正式运行及其要求的报告和产物均成功后才记录完成。
- 审计金币消费、新策略实际选择、鱼厅产出和杠铃时点，并检查力量、双 Luck、鱼雷、境界及永久进展的连带变化。
- 旧模型报告仅作历史参考，不直接用旧 gate 数字验收新模型。规则、策略与生产数据同时变化时明确说明，不能归因给单一字段。
- 不为本次迁移新增一套可长期启用的旧币种兼容模型或额外调参扫描。

## Out of Scope

- 修改实际游戏的 Excel、Luban 源表、生成 JSON/Lua、升级价格曲线、产出曲线或等级上限。
- 实现神兽获取、神兽收益与最强普通鱼的联动、神兽完整存档模拟及相关付费机制。
- 新增升十级行为、批量升级按钮、自动连点或背包鱼追赶投资。
- 新增出售鱼的命令或策略、升级退款、旧投入补偿和存档重置。
- 为游戏原子命令增加“普通鱼必须已上阵才能升级”的限制。
- 改成最高品质单鱼持续升级、全背包最低价策略、回本时间主排序或组外便宜替补策略。
- 改变现有随机掉落算法、重生、突破、在线/离线制度或其他资源消费规则，普通鱼场景排除神兽的必要修正除外。
- 构建预测未来掉落、离线与所有系统收益的全局最优投资求解器。
- 重构 IGESS 正式运行架构、增加独立报告管线、改变执行工具包源码隔离和分发规则。
- 发布 GameBalancer、推送分发仓库或进行广泛参数扫描。

## Further Notes

- 用户已在 2026-09-16 明确“确认”整体方案，并要求使用 to-spec 发布。本规格直接综合已确认内容，没有重新开启访谈。
- 本地 issue tracker 的发布位置为本功能目录下的 spec.md，分诊状态为 ready-for-agent；这表示可以进入实现，不代表代码或正式模拟已完成。
- 术语以根目录 [CONTEXT.md](../../CONTEXT.md) 的“鱼升级”“鱼品质”“Fish 稀有度”“导表快照”“依赖范围校验”“正式运行”和“比较基线”为准。
- 适用架构约束为 [ADR-0001](../../docs/adr/0001-distribute-execution-toolkit-from-separate-repository.md) 和 [ADR-0002](../../docs/adr/0002-distribute-igess-without-python-source-files.md)；本规格不改变这些取舍，无需新增 ADR。
- 事实核查基准：实际 Fish 提交 0a7fed33c03e330ae8a3a78918b78435cf67525d，日期 2026-09-15；IGESS 核查基准 10bd058。实现时如代码或数据继续变化，重新核对实际差异，不把该基准当作自动锁定的生产输入。
- 核查时实际导表包含 17 张表、1626 行，其中 Fish 为 121 条普通鱼和 4 条神兽；生成类型验证通过不代表全部游戏语义已经接入模拟。行数是审计事实，不得硬编码为永久校验要求。
- 实际升级币种及指数常量来自游戏运行代码，不在 Luban 数值表中；既有生产快照链接和同批次生成类型仍是唯一生产数值输入。
- 同等级、持续上阵且无额外倍率时，单级增量回本时间为 4 × 1.2 的等级减一次方秒。一级产出同时影响价格与增收，因此品质优先是用户确认的培养偏好，不等价于绝对最短回本。
- 只允许已上阵鱼升级，意味着新高品质鱼可能长期留在背包中等待自然进入最佳收益阵容；这是确认后的边界，不能用自动追赶或强制按品质上阵绕过。
- 实施后的进度与正式运行证据继续记录在 [Fish RoadMap](../../projects/fish/RoadMap.md)。原有工作区未跟踪文件与历史报告须保留。

## Comments

- 2026-09-16：按用户指定的 grill-with-docs，读取并应用 grilling 与 domain-modeling；对实际项目及模拟实现分别完成只读核查。未修改模拟代码、生产表或生成文件，未运行正式数值模拟。
- 2026-09-16（首轮回答）：用户选择先做普通鱼升级、神兽不可升级；选择主动增收；只模拟升一级，十级入口只是方便人类玩家。已更新范围、设计树及术语。
- 2026-09-16（第二轮回答）：用户要求最高品质（一级产出最高）鱼优先；Q5 杠铃阶段目标及 Q6 权重 1、每级 3 秒均采纳推荐。已记录品质偏好，并说明按当前公式同等级品质不会改变增量回本时间。
- 2026-09-16（第三轮回答）：用户将 Q7 修正为品质前 X 条普通鱼内最低等级优先，X 为鱼厅容量减上阵神兽数，替代最高品质单鱼锁定；Q8 采用最低价且更强的未拥有杠铃为目标。
- 2026-09-16（第四轮回答）：用户否决 Q9 的未上阵追赶例外，明确只升级当前已上阵鱼。最终建议以品质前 X 与上阵鱼的交集作为候选，不因未上阵的新鱼阻塞其他候选，杠铃资金条件保持有效。
- 2026-09-16（整体确认与发布）：用户确认完整方案并显式调用 to-spec。保留已确认的正式工作流与领域命令测试边界，按标准模板发布为 ready-for-agent；模拟实现尚未开始。

- 2026-09-16（实施完成）：实现提交 `5a1f509`；正式 smoke/1d/7d/30d、全量与定向测试已通过。双轴审查无阻塞问题，证据见 [verification.md](verification.md) 与 [review.md](review.md)。
