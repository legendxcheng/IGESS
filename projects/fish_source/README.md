# Fish 同源 Lua 模拟项目

此项目通过 IGESS 正式入口运行 Fish 源项目的 Lua 业务服务，无需 DS。自 2026-10-14 起，这是 Fish 唯一在用的模拟项目；新规则、调优、正式运行与报告均在此维护。`projects/fish` Python 后端停用，保留历史代码与报告，不再作为新运行或比较基线。当前进度与待办见 [RoadMap.md](RoadMap.md)。

```powershell
uv run igess model simulate --project projects/fish_source --scenario smoke
uv run igess model simulate --project projects/fish_source --scenario day_1_growth
uv run igess model simulate --project projects/fish_source --scenario day_2_growth
uv run igess model simulate --project projects/fish_source --scenario day_3_growth
uv run igess model simulate --project projects/fish_source --scenario day_4_growth
uv run igess model simulate --project projects/fish_source --scenario day_5_growth
uv run igess model simulate --project projects/fish_source --scenario day_6_growth
uv run igess model simulate --project projects/fish_source --scenario week_1_growth
uv run igess model simulate --project projects/fish_source --scenario month_1_growth
```

Day1～Day6 是累计场景：`day_N_growth` 默认从新玩家开始运行到第 N 个自然日结束（N × 24 小时），使用默认免费画像、每天在线 2 小时，每累计在线 300 秒采样。按当前调参阶段选择一条命令即可，Dashboard 会从配置自动加载这些场景。独立运行适用于改表后验证前 N 天；输入不变时可显式选择上一轮 checkpoint 接续，见下方“按天接续”。

## Agent 通过已运行的 IGESS 跑测

`fish_sim` 代跑默认提交到本机主 Dashboard `http://127.0.0.1:8771`，服务后台执行，页面显示当前任务和完成结果。启动及查询命令（IGESS 根目录）：

```powershell
.\.tmp\py311-venv\Scripts\python.exe .agents/skills/fish_sim/scripts/run_dashboard.py submit --scenario week_1_growth
.\.tmp\py311-venv\Scripts\python.exe .agents/skills/fish_sim/scripts/run_dashboard.py status
```

续跑加 `--resume-run-id <成功运行ID>`。交接提交回执中的网页和状态链接；`accepted` 不表示模拟成功。服务不可用时不会自动另起 CLI 或重启服务。历史库与运行参数边界见 [服务跑测说明](../../.agents/skills/fish_sim/references/dashboard-runs.md)；下面的 CLI 保留给显式独立执行及开发验证。

## 按天接续

先运行 Day1；确认结果后，以返回的 `output_dir/final_checkpoint.json` 运行 Day2，再以 Day2 的新 checkpoint 运行 Day3，依次推进。截止时间仍是目标场景的绝对时间：完整 Day1 接 Day2 时，本段为 86400～172800 秒。

```powershell
uv run igess model simulate --project projects/fish_source --scenario day_2_growth --checkpoint-in "<Day1运行目录>/output/final_checkpoint.json" --json
uv run igess model simulate --project projects/fish_source --scenario day_3_growth --checkpoint-in "<Day2运行目录>/output/final_checkpoint.json" --json
```

Dashboard 的正式运行表单中，选择目标场景，再在“起点”中选择成功历史结果；保留“从新玩家开始”则独立模拟。页面／任务组件更新后需要重启 Dashboard 服务，模拟任务不能代替服务重启。

接续要求模型、源码、导表、适配器、种子与玩家策略身份一致。跨场景仅允许延长时长，画像、初始状态、采样和输出类型须一致（允许长程场景的 `compact_event_details` 存储差异），因此也支持 Day6 接首周或首周接首月。修改数值表、配置或代码后从零重跑；本次适配器升级前的 checkpoint 仍按原身份规则拒绝，需先生成新基线。原报告和 checkpoint 保留，每次接续产生新的运行目录。

续跑报告标为“续跑区间”，事件／成长计数只覆盖本次新增区间；钱包、累计收入、随机状态与生命周期首次记录延续历史。需要前 N 天的完整成长统计时，使用独立累计运行或逐段报告，不能把单段报告当成全程报告。源恢复仍重放历史操作以重建状态，省去前段策略决策和采样处理，但不是零成本加载；节省时间取决于实际运行，不能保证每天耗时固定。

`igess model status --project projects/fish_source` 使用同一个源引擎执行十 tick 就绪检查，检查源能力和输入并观察状态变化；检查不登记正式运行，也不创建运行报告。通过后仍需以上正式入口生成可归因的报告。

`economy.yaml` 的 `engine.source_runtime.project_root` 默认指向同盘兄弟目录 `E:\fish-oasis`，`data_root` 指向该源项目的 `igess_export/json`。运行需要本机 `lua55`。修改目录布局时更新这两个路径。每次运行会冻结 Lua 模块和所选 JSON 导表，记录二者内容摘要、IGESS 适配器摘要、Lua 版本、策略、种子和模型摘要。标准 timeline、events、analysis、Web 报告、同源成长/行为产物和 checkpoint 位于本项目 `runs/`。

本项目的 `Datas/` 与 `luban_exports/` 仅满足 IGESS 当前 authoring 项目的通用配置结构；Fish 数值实际来自 `engine.source_runtime.data_root`。编辑这些通用工作簿不会改变同源 Fish 数值。要测试新的 Fish 数值，应更新所选 Fish JSON 导表，并在运行产物中核对 `selected_export_sha256`。不应把两个后端的运行当成单因素数值改动比较。

GameBalancer 使用发布时从游戏源码编译的 `bundle/fish-runtime`，不会实时读取开发机的游戏分支。修改 Excel 并导出 JSON 后可直接重新模拟；游戏 Lua 规则、宿主接口或表结构变化后，需要重新构建并更新 GameBalancer。开发机直接运行与交付包是否同步，应分别核对当前源码摘要、包内 `runtime.json.source_code_sha256` 和报告中的 `packaged_source_code_sha256`，不能由其中一条路径成功或失败推断另一条。

2026-10-23 同步修复将已验收的图鉴、枪、蛋和鱼潮宿主接口接回当前游戏源码，同时使用当前游戏的关闭材料回退规则。模拟商店购买候选只包含已开放的神器，并在实际第四区入水、寻宝兽永久开放后可用；已拥有的关闭神器仍可通过源服务选择和使用。该门槛纳入报价缓存身份，解锁后立即刷新。修复及工具版本验证见 [同步修复记录](../../.scratch/fish-sync-audit-20261023/repair-verification.md)。

Web 报告读取同源状态和交易回执，展示力量、双 Luck、钱包与待领金额、金币投资、杠铃购买及每日／每周成长操作。突破资助不等于突破完成；峰值仅指记录中的采样峰值。旧长场景按天采样，无法补出 5 分钟在线毛产出与精确停滞，缺失指标明确显示为未记录。可用 `igess report --run <运行目录>/output --out <运行目录>/report` 更新已有报告展示，无需重新模拟。

成长图同时纳入正常图鉴完成、新枪永久获得、新鱼种与新变异组合。新鱼种按 Fish ID 首次获得，新变异按 Fish ID＋非普通变异 ID 首次获得；首次即变异时展示两个标签，总次数只计一个收集事件，分类标签数可重叠。普通捕获与实际孵化共用永久解锁历史，卖出后重获不重计，鱼蛋入包不提前计入。领取枪、拥有枪与装备明细仍分别保留，新枪成长只按永久拥有计一次。

新运行在 `source_profiles.collection_growth` 与行为产物中保存本段起始解锁／枪事实及冻结导表名称；checkpoint 继续时从恢复后的源状态建立基线，不重放历史成长。成长时点是源观察时点，同批多组合按稳定身份展示并注明未区分先后，不从曲线采样补造时间。旧新玩家完整事件可重生成；旧续跑缺起始历史时，新鱼种首次不推断，页面显示覆盖不完整。名称优先使用运行保存的快照名称，否则显示 ID。相邻在线时段共用边界秒时只归入后一个时段。规格与验收见[收集成长点](../../.scratch/fish-collection-growth-points/spec.md)。

新运行的 1～7／30 天场景每累计在线 300 秒采样（`sampling_time_basis: online`），离线时间不消耗采样周期；另记录上下线、离线奖励领取及两类重生前后状态，相同状态去重。采样只查询源状态，不改变玩家操作；间隔与时间口径写入运行清单。增加采样点需要重新模拟，不能通过重生成旧报告补齐。状态采样仍不代表完整在线毛产出或连续时间真实峰值。

“资源（材料）余额”有独立图表，直接展示源状态的 `material`，横轴为累计在线时间。默认线性视图保留零余额，可切换对数视图查看数量级；它是扣除消耗后的余额，不是累计获取量。通用资源曲线和总览也使用“资源（材料）”名称，与游戏界面对应。

2026-10-08 起的新运行同时提供资源与金币的每秒产出、累计产出、当前剩余三类折线图。
IGESS 对源状态变化和成功回执做收入统计：加回消费，抵消钱包与鱼厅待领金额之间的领取转账，
排除离线奖励领取；材料累计值包含在线加工和卖鱼，另保留卖鱼分项。统计随 checkpoint 保存。
每秒速率按相邻采样点之间的实际在线秒数平均，悬停显示窗口长度；默认在线采样间隔为 300 秒，
上下线及重生边界可能形成较短窗口。当前剩余为可花费的钱包余额，包含离线入账，待领金币仍单独展示。
旧运行没有这组在线产出统计时，不能仅重生成报告补齐每秒及累计产出，需要重新模拟；已有余额继续展示。

单鱼图鉴通过源目录与领取服务接入：捕获只增加历史解锁，空闲时按稳定奖励 ID 优先领取，每次占用 1 秒。
`codex_fish_unlocked` 与 `claim_fish_reward` 分别记录解锁和实际入账时点；前者是观察事件，不计为接受命令或系统开放。
金币、材料的一次性图鉴奖励各有累计分项，恢复后继续保留，累计获取包含它们；加工材料分项扣除卖鱼和图鉴奖励，鱼厅领取仍只算转账。
报告中的图鉴一次性曲线不代表稳定每秒生产能力。合法关闭条目和神兽不会出现在可领奖投影中，非法实际奖励依赖会使运行明确失败。


`source_priority_v1` 使用画像权重在当前可执行操作中选择玩家意图，并按配置的操作耗时、每日在线窗口和领取周期推进。默认投到源准备回执的自然目标，使用源飞行模拟器的最终入水耗时（向上取整到秒），而非固定 100cm；力量、水域映射和飞行速度均由 Lua 提供。仅用于受控对照时可显式设置 `landing_distance_cm`，运行清单分别记录 `source_natural_v1` 和 `explicit_distance_v1`。价格、合法性、扣款、奖励、重生和生产由源 Lua 决定；源规则拒绝会记入事件。力量为零等无法计算当前幸运值的状态在成长产物中记为缺失，不填零。付费倍率等没有源服务支撑的假设画像会在运行前拒绝。

寻宝兽使用源 `unlocked` 永久资格；拥有初始境界或足够力量不会直接开放。实际入水至第四水域后，首投立即获得废料；此前合法卖鱼等材料来源照常结算。正式报告记录开放前后状态、实际水域、墙钟及累计在线时点。运行截断于自然飞行中时，checkpoint 保留目标和入水截止时间，不提前奖励；玩家实际下线仍交给源服务结束当前投掷。

寻宝兽突破成本按 `TrashManRealm.materialRequireToNextRealm` 读取，允许相邻成本下降或持平，以支持大门槛后接较低的小阶段成本。非满级成本必须为合法正数，满级仍为零；境界顺序、分解速度和返祖相关校验保留。成本节奏由源表决定，模拟不补资源或调整支付规则。该源规则变化需要新建运行，旧源码摘要 checkpoint 不可直接续跑。

鱼厅金币按 `stable_slot_batch_v1` 全部领取：默认每 300 秒启动一批，按槽位编号固定本轮有余额且未被拒绝冷却阻塞的槽位，每槽调用源 `collect_slot` 一次并占用 2 秒。周期从批次建立时计时，领取期间生产继续；已访问槽位新产出的金币留到下一轮，避免首槽持续产出阻塞后续槽位。批次优先于其他普通动作，实际入账仍在单槽动作开始时由 Lua 完成，领取只算转账。

领取批次跨实际下线或鱼潮后继续；距离下线／鱼潮边界不足 2 秒时等待边界，保留未领取槽位。运行截断则保留剩余批次与当前动作剩余耗时，恢复不重复提交已尝试槽位。执行前余额清空、槽位移除或被冷却阻塞时直接跳过；源拒绝记事件并消耗本槽 2 秒，继续其他槽位，下轮再按源状态判断。运行清单记录批次策略、耗时和周期基准；适配器摘要随代码改变，旧代码身份 checkpoint 仍拒绝恢复。查看修复后的经济节奏需要新建模拟，旧报告重生成不会改变策略结果。

该画像是新策略，不沿用旧 Python 后端的选鱼、出售保护、最高鱼雷等目标策略。普通同权候选按固定轮转选择，单项行为选择第一个满足源报价的目标；不合法目标由源服务拒绝。若配置旧 `behavior_target_policies`，运行会在预检中拒绝，避免误以为它生效。

卖鱼采用 `over_30_lowest_level_one_cps_backpack_v1`：背包与摸鱼厅的鱼合计严格超过 30 条时，在领取奖励／金币之后、其他普通行为之前逐条出售背包中资质最低的普通鱼，降到 30 条即停止。上阵鱼计入总数但不出售，神兽不作为可卖候选；无合法候选时继续其他行为。资质按一级 CPS（包含变异倍率、不含鱼等级提升）排序，同值取最小实例 ID。源 `query_actions.fishSales` 提供可售背包鱼的 `levelOneCps` 和 `materialAdded`，Python 精确比较报价，不重算经济公式。卖鱼权重缺失或为零时禁用；每条沿用画像的 `sell_fish` 耗时（默认 3 秒），材料结算及收入统计保持源回执，拒绝冷却与截断恢复沿用既有动作契约。运行清单记录卖鱼策略和保留数量，新策略效果需要重新模拟，旧报告不会随代码更新改变。

这套宿主覆盖普通鱼数值链，不模拟 UE 世界碰撞、网络复制、真实玩家路线和 DS。`advance_mode: equivalent_batch_v1` 只在区间内没有定时任务和活动 buff 时合并生产事务，保留逐秒模式的最终回执、revision 与状态；`accurate` 可作为逐秒对照。早期 1 天同源正式运行中快速模式约 20 秒、逐秒模式约 53 秒，四份核心业务产物逐字节一致；旧 Python 正式运行约 1.6 秒，但策略语义不同，不能把耗时比当成严格同工作量比值。7 天和 30 天配置中沿用的 `compact_event_details` 标记目前不压缩同源回执。

2026-09-25 性能优化复用源宿主的背包投影和行动报价，并消除输入冻结时复制后重复读文件的开销。相同生产输入和密集采样下，1 天正式运行三次中位数由 16.37 秒降至 10.43 秒（耗时减少 36.28%）；30 天单次对照由 598.70 秒降至 451.71 秒（减少 24.55%）。四份核心产物及 checkpoint 操作/回执历史相同，30 天保留全部 837 个采样点。测量范围、波动和回归证据见 [性能验证](../../.scratch/fish-source-performance/verification.md)。缓存不改变价格或结算，不减少五分钟采样；不兼容旧代码指纹的 checkpoint 仍按原契约拒绝恢复。

图鉴枪模拟接入源服务：正常图鉴完成后在空闲点按稳定奖励 ID 领取（每次 1 秒），然后装备当前源攻击力最高的已拥有枪（同值取最小枪 ID，装备 1 秒）。领取与装备分离；任意合法枪永久拥有即开放鱼潮资格，变异图鉴强化不授予枪，也不改变换弹单价。正式基线不授予付费枪。行为产物与 Web 报告分别记录满图鉴、领取、拥有、首次装备、永久强化和鱼潮开放的房间时间及累计在线时间；checkpoint 保留去重事实。策略摘要与适配器摘要参与运行身份。鱼潮资格与参与事实分开记录。

鱼蛋生命周期已接入源随机、入包和孵化服务。受控会话可逐颗调用 `grant_random_egg`（稳定 requestId）以及 `settle_eggs`；这些操作不作为正式画像的免费奖励行为。区域输入固定为 1，抽蛋与每颗蛋孵化种子独立确定，重复配置允许独立实例。`query.eggs` 提供库存、源容量、鱼包满阻塞、入包回执和孵化事实；IGESS 行为产物、事件与 Web 报告观察入包和孵化，孵化前不计作鱼收益。源截止时间按实际入包计算，离线计时并在上线结算；快速推进有可结算的孵化边界或待完成保存/通知时回落逐秒；鱼包已满且无待完成副作用时，到期蛋保持原状，允许批量生产。每次推进重新检查源容量，腾出鱼位后恢复孵化边界，截止时间和随机结果不变。完整会话 replay 保留逐颗受理与去重。运行包依赖包含蛋与鱼潮随机池。

单场鱼潮已通过源会话 `start_tide`／`complete_tide` 接入：先结算到期蛋，通过只读 `query_tide(roundId)` 估算本场装弹预算，预检预算与五个蛋位，锁定装备枪并调用源换弹服务扣费，在同一模拟时刻逐颗调用源随机与入包服务，前台占用为 0 秒。开始到完成之间宿主仍拒绝其他主动操作，完成后立即恢复普通调度；蛋孵化从本次即时入包开始计时。回执区分参与、支付待结算、发蛋待完成、失败与完成；重试返回本次新增支出，累计支出及逐次源事务另行保留。查询只投影当前／最近一场和总场数，历史场次身份仍可安全重试，正式事件保留各场完整事实。

正式策略按源 `tides.config.intervalSeconds` 连续调度，`source_runtime.room_origin_seconds` 默认为 0，并与源生成窗口、入场策略写入清单。只在绝对开场边界判断入场；离线不冻结、不重置且不补场。开场时离线、未解锁或前台忙碌均逐场记录跳过；只要开场时仍在线，就不要求额外预留 120 秒。普通动作不会为了赶场截短既定耗时，锻炼在边界结算并停止，已提交自然飞行跨开场时该场记忙碌。运行清单记录固定五蛋、0 秒占用、按攻击力与 HP 估算装弹的近似，Web 报告展示阶段、耗时、每次换弹与实际总支出；不推断真实命中率或多人竞争。

### 按枪攻击力与鱼蛋 HP 估算装弹

`fixed_eggs_damage_hp_zero_time_v3` 每场保留 5 颗源随机蛋，按攻击足够时快速打蛋的假设将前台占用计为 0 分钟。每颗蛋所需子弹为 `ceil(源 Egg.baseHp / 当前源枪攻击力)`，先逐颗取整再求和；每匣固定 30 发，本场装弹次数为 `ceil(总子弹数 / 30)`。攻击力包括源永久图鉴强化。HP 与攻击力通过源 BigNumber 精确比较，不先转浮点数。

`query_tide(roundId)` 只读预览同一场身份下的五颗蛋，不入包、不推进时间、不写 replay 历史。实际入场重新读取源状态并冻结 `ammunition`（枪、攻击力、逐蛋 HP／发数、总发数、匣数及费用），预算与扣款共用此报价；结算仍按相同逐蛋 requestId 走源抽蛋与入包服务，重试／恢复不重抽、不重复扣费。费用为源单次换弹价格乘估算次数，每次扣费仍由 GunReloadService 完成。

当前采用空弹匣起算，首匣付费，同场余弹可继续打下一颗蛋，场后余弹不结转；假定每发命中，不模拟射速、换弹耗时或多人伤害分摊，0 分钟是数值模拟的时间近似，不代表真实战斗耗时测量。没有把固定五蛋改为按火力决定产量。需要原生库存攻击力的 `best_gun` 不在免费画像覆盖内，会明确拒绝。新报告展示发数／装弹次数；旧报告不补造这些数据。旧源码／适配器 checkpoint 不能续跑，需新建基线；GameBalancer 需另行发布。

### 养成优先与鱼潮材料预留

鱼潮开场采用 `growth_first_wallet_fraction_near_term_reserve_v1`：已满足条件且买得起的鱼厅扩容、神器、杠铃、突破资助及两类重生优先于鱼潮；单鱼反复升级不属于该入场拦截集合。养成线之间仍使用现有权重和轮转，领取、卖鱼、上阵及已开始的动作保持原调度。

没有可执行成长时，读取本场 `query_tide` 的 `materialCost` 源报价，得到整场费用。整场费用超过入场前材料余额的 25% 就跳过，恰好相等通过此项检查。每场重新读取余额和源报价，所有已入账材料均属于余额；这不是日消费限额，连续多场的累计消费可能超过某一时点余额的 25%。

通过单场限额后，再检查近期成长预留：每条材料养成线仅取下一合法目标，以最近约 1800 秒累计在线收入估计未来最多 1800 秒能否攒够，预测范围受当天剩余在线时间限制。离线奖励和一次性图鉴奖励不进入收入估计。按既有权重和轮转选择一个近期目标；若余额不能同时覆盖目标价格及本场装弹费用，则跳过鱼潮。无有效观察或没有近期目标时，仍必须通过 25% 检查。两项检查均通过才尝试入场，合法性、扣款和奖励仍由源 Lua 负责。

跳过事件区分 `growth_action_ready`、`tide_material_budget_exceeded` 和 `growth_material_reserved`。单场限额回执附余额、整场费用、25%限额和比例；预留回执附目标、价格、已观察收入和预测窗口。金额使用精确十进制字符串。

运行清单 `tide_admission_policy` 保存比例、收入窗口及预留口径。checkpoint 的 `growth_tide_budget` 保存有界收入观察历史；25%限额由当前余额重新计算。新策略需从新玩家重跑，旧适配器 checkpoint 继续拒绝；同版本截断／恢复保持决策和源回执一致。验证见 `tests/test_fish_growth_priority.py`。这项修改不会自动更新 GameBalancer。

正式运行可用 `--until-seconds` 保存中途状态，再用同一场景或兼容的更长场景与 `--checkpoint-in` 继续。截止秒为场景内绝对秒，不改变场景或模型身份；不可早于恢复点，等于恢复点允许只读重新生成产物。此选项仅支持 fish_source。

```powershell
uv run igess model simulate --project projects/fish_source --scenario day_1_growth --until-seconds 660 --json
uv run igess model simulate --project projects/fish_source --scenario day_1_growth --checkpoint-in <运行目录>/output/final_checkpoint.json --json
```

运行清单 `execution_window` 记录本段起止、请求截止与原场景总长。恢复报告的事件、accepted_commands 与孵化计数只覆盖本段；钱包、在线收入累计、active_time_seconds 和源 totalThrows 延续存档。生命周期 `first_times` 和 `lifecycle_gun_milestones` 随 checkpoint 保留，分别记录墙钟与累计在线时点；恢复报告的在线耗时仅算本段，横轴累计在线坐标延续此前进度，不能把本段首事件当作生命周期首次。鱼潮开始与完成在同一调度时刻处理，正式截断不会留下等待中的鱼潮；底层源会话仍保留支付／发蛋待完成的重试身份。已落地但尚未结束的投掷占用、普通动作耗时与锻炼均可恢复；采样只观察阶段，孵化截止独立于报告间隔。

宿主库存投影聚合源分页并返回真实 `capacity`，不将每页 50 条当成总容量；`source_progression` 保存期末鱼库存、蛋库存与满鱼包孵化阻塞。金额 DTO 在策略报价比较、timeline、收入与报告保留源 BigNumber 精度，包括超过 80 位的系数。受控联合回归覆盖免费图鉴枪链、实际第四区落点后的资助、换弹与逐蛋通知待完成的跨进程恢复；最终生产基线与审查证据见 [实施票 07](../../.scratch/fish-source-unlocks-and-tides/issues/07-formal-baselines.md)。

源换弹延迟结算为退款时，回执用非负 `materialSpent` / `materialRefunded` 分列本次扣款与退款，累计净支出和累计退款另行保留；退款回冲鱼潮净支出，不计为加工或图鉴收入。跨进程重试沿用同一操作身份，已结算退款不重复入账。


## 查询性能优化

2026-11-01 后续实施接入单次完整查询的快照复用：`SnapshotScope` 按会话、coroutine 和查询生命周期隔离，通过既有 ArchiveService 注入服务；枪查询仅复制会被修改的 combat 分支。各服务校验选项不同，仍执行原校验。规格、实施票与整周对照证据见[查询快照复用](../../.scratch/fish-query-snapshot-reuse-20261101/spec.md)所在目录，契约和回归入口见源 `simulation/README.md`。

2026-11-01 当前源码接入幸运值直接查询：`FishThrowService.QueryLuck` 复用 `ThrowOutcomeResolver` 的前置校验与源映射，正常观察只返回四个所需字段。自定义 options、异常目录与数值边界保留完整 Resolve 回退；真实投掷、精度、池边界、源随机结果及 checkpoint 身份保持。实现契约见源 `simulation/README.md` 的“幸运值只读查询”，本轮证据见[验收记录](../../.scratch/fish-luck-query-20261101/verification.md)。以下查询／状态观察优化记录属于当时冻结版本，所选源树是否仍包含对应实现须重新核对；本轮未重接其余优化，也未发布 GameBalancer。

源宿主共享单次观察快照和完整校验，缓存鱼厅稳定投影，一次构造完整背包，并直接获取幸运映射；同次计算复用相同鱼组合的纯结果。精确大数分块运算和 JSON 编码减少内部开销，保留精度、随机、操作时点、采样、回执及恢复身份；可变返回值仍隔离。

源接口与缓存契约见 `<source>/simulation/README.md` 的“查询性能与隔离”；配对测速、完整最终状态及恢复证据见[查询性能验证](../../.scratch/fish-source-query-performance/verification.md)。本地源码更新不代表 GameBalancer 运行包已发布。


2026-10-29 状态观察新增可选变化传输：运行时依据源能力自动选择，在原有每个观察点重建完整独立状态，完整 Query 保留为回退接口。源宿主为每个会话创建冻结规则生产计算器，复用稳定鱼厅产出；动态余额、交易校验、精确大数、回执和 checkpoint 身份规则不变。原批量推进算法保留，未接入没有实测收益的事件分段候选。规格、逐次状态差分及整周配对见[状态观察与推进性能](../../.scratch/fish-state-and-advance-performance/spec.md)及[验收记录](../../.scratch/fish-state-and-advance-performance/verification.md)。本地实现不代表 GameBalancer 已更新。
