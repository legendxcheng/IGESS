# Fish 同源模拟：图鉴奖励、寻宝兽开放与鱼潮

Status: resolved

日期：2026-10-14。范围：Fish 源项目的独立 Lua 模拟宿主，以及 IGESS 的 fish_source 调度、观察和报告。本规格由已确认讨论整理，随后经用户调用 implement-spec 实施完成；结果见文末 Answer 与验证记录。

## Problem Statement

数值策划已调整 Fish 的系统开放与奖励规则，但现有模拟尚未完整覆盖图鉴、领枪、寻宝兽开放和鱼潮收益，无法据此判断真实的前期成长、材料供给与长期经济。

旧 Python 模型排除了图鉴，继续在其中复制规则会扩大与游戏的差异。用户已经确认以后仅使用 fish_source，旧 fish 项目停用并保留历史记录。同源 Lua 后端虽然调用游戏业务服务，但当前操作接口和玩家策略还没有覆盖新增链路；固定 100cm 的投掷选点也不能正确表达随力量成长进入第四水域的过程。

鱼潮如果只记奖励、不占玩家时间或不扣换弹材料，会高估收益与力量成长。反之，为数值评估完整重建 UE 漂流、碰撞、原生射击和多人争夺，并非本次目标。

## Solution

以 fish_source 为唯一在用模拟后端，复用源游戏的图鉴、枪械、投掷、钱包、鱼蛋与孵化服务。IGESS 决定玩家行为及其发生时间，源 Lua 决定资格、金额、扣款、奖励和存档变化。

接入三条成长链：

1. 首次获得鱼种与变异组合后形成历史图鉴，可以主动领取一次金币或材料；正常图鉴集齐后可领枪，变异图鉴按源规则形成枪强化。
2. 玩家第一次实际将鱼雷投到第四水域或更远时永久获得寻宝兽；该次投掷开始发放废料，此前投掷不发废料。材料的其他合法来源不受此门槛影响。
3. 永久拥有任意枪后开放鱼潮，免费路径是图鉴满后领枪，已到账的付费枪同样满足拥有条件。正常参与一场鱼潮固定占用 120 秒、成功获取 5 颗随机蛋，并承担 6 次换弹费用；期间停止炸鱼和锻炼，后台生产继续。鱼蛋按源规则入包和孵化，再影响鱼厅及图鉴。

报告展示开放时点、一次性奖励、鱼潮耗时与换弹支出，以及这些变化对金币、材料、力量和永久进展的影响。每场 5 颗是明确的经济近似，不表示逐发射击或多人竞争经过验证。

## User Stories

1. As a balance designer, I want all new Fish simulations to use fish_source, so that there is one maintained simulation backend.
2. As a balance designer, I want historical Python reports to remain available, so that previous findings can still be traced.
3. As a balance designer, I want gameplay rules to execute through the source Lua services, so that simulation results follow game changes.
4. As a balance designer, I want simulations to consume the selected read-only production export, so that results describe the tables I actually exported.
5. As a balance designer, I want historical codex progress to track each fish and mutation combination, so that repeated catches do not create new unlocks.
6. As a balance designer, I want selling fish to preserve codex history, so that inventory cleanup does not reverse progression.
7. As a balance designer, I want eligible individual fish rewards to be claimed through player actions, so that unlock time and spendable reward time remain distinguishable.
8. As a balance designer, I want money and material rewards to follow their configured types and amounts, so that early liquidity is measured correctly.
9. As a balance designer, I want previously unlocked but unclaimed rewards to remain claimable, so that resumed states retain legitimate rewards.
10. As a balance designer, I want duplicate requests and checkpoint restoration to preserve one-time rewards, so that no income is counted twice.
11. As a balance designer, I want normal codex completion and gun claiming to be separate milestones, so that the free fish-tide unlock path is visible.
12. As a balance designer, I want any legitimately owned gun to satisfy fish-tide access, so that the rule does not falsely require a codex gun.
13. As a balance designer, I want gun ownership and equipment to remain distinct, so that an unequipped gun does not silently determine reload costs.
14. As a balance designer, I want mutation codex upgrades to follow the source rules, so that permanent gun progression remains accurate.
15. As a balance designer, I want throws to use source-derived reachable landing distances, so that increasing strength can lead to later water areas.
16. As a balance designer, I want the treasure beast to unlock on the first confirmed landing in area four or beyond, so that sufficient strength alone does not unlock it early.
17. As a balance designer, I want the qualifying throw itself to grant eligible trash, so that material income does not start one throw late.
18. As a balance designer, I want pre-unlock throws to grant no trash, so that early processing income is not overstated.
19. As a balance designer, I want legitimate sale and codex material income to remain available independently, so that treasure-beast gating does not remove unrelated rewards.
20. As a balance designer, I want permanent access to survive rebirth and restoration, so that later strength resets do not close an unlocked system.
21. As a balance designer, I want fish-tide rounds to follow source scheduling intervals, so that participation frequency reflects the game configuration.
22. As a balance designer, I want each normal completed participation to grant five random eggs, so that fish-tide yield has a simple reproducible model.
23. As a balance designer, I want egg rarity and mutation to use source probability rules, so that the approximation preserves reward composition.
24. As a balance designer, I want each participation to occupy 120 seconds, so that fish-tide rewards have an explicit time cost.
25. As a balance designer, I want throwing and exercise to stop during participation, so that one player cannot perform multiple foreground activities simultaneously.
26. As a balance designer, I want background production to continue during participation, so that the time cost does not incorrectly stop passive income.
27. As a balance designer, I want six reloads to be charged using the equipped gun's source cost, so that fish-tide material expenditure is visible.
28. As a balance designer, I want unaffordable participation to have an explicit outcome, so that the simulation never creates debt or free reloads.
29. As a balance designer, I want egg and fish capacity limits to remain effective, so that constrained inventory does not create impossible rewards.
30. As a balance designer, I want hatching to use source deadlines and reward rules, so that fish do not appear immediately when eggs are obtained.
31. As a balance designer, I want hatched fish to enter the existing economic and codex chains, so that fish-tide rewards influence later progression.
32. As a balance designer, I want offline and insufficient-time rounds to be recorded as missed opportunities, so that daily play schedules remain meaningful.
33. As a balance designer, I want mid-round checkpoints to preserve costs, random outcomes and remaining time, so that segmented runs match uninterrupted runs.
34. As a balance designer, I want rejected or partially admitted source operations to remain diagnosable, so that infrastructure failures are not disguised as gameplay outcomes.
35. As a balance designer, I want one-time rewards and recurring production shown separately, so that short reward spikes do not look like sustainable income.
36. As a balance designer, I want system unlocks separated from individual codex entries, so that frequent small rewards do not hide long system-progression gaps.
37. As a balance designer, I want room timing, player policy and random seeds recorded with the run, so that numerical changes can be attributed and reproduced.
38. As a maintainer, I want existing session and formal-run interfaces to be the main test boundaries, so that tests validate behavior without depending on private implementation structure.
39. As a balance designer, I want fresh one-day, seven-day and thirty-day formal results, so that the revised growth curve has a consistent baseline.
40. As an execution planner, I want source-isolated offline packaging to remain compatible, so that the new simulation does not require access to game source or a running DS.

## Implementation Decisions

### 1. 已确认范围与归属

- 仅扩展 fish_source；旧 Python Fish 模型不继续接入新规则，不删除历史报告，不把旧后端结果作为本次比较基线。
- 修改范围包含 fish-oasis 的模拟宿主及其协议，以及 IGESS 的同源适配器、玩家策略、checkpoint、收入观察和报告。用户已讨论并接受需要扩展源项目宿主；规格发布后另由用户调用 implement-spec 授权实施。
- 游戏已有的业务资格、概率、配置金额、扣款与奖励继续由源服务执行。IGESS 不直接修改游戏存档，不重新实现一套图鉴或孵化经济公式。
- 优先复用源服务已有的时间、装备、原生换弹、存档和通知依赖注入接口，在宿主中提供明确的模拟适配器。确实缺少可复用边界时，仅做支撑同源调用的最小提取，保持游戏生产行为不变。
- 不启动真实编辑器或 DS；本次自动验证不声称覆盖真实碰撞、网络或原生枪械表现。

### 2. 图鉴、领奖与枪

- 图鉴成员、开放鱼、神兽排除、鱼种与变异组合、正常图鉴完整条件等均取源服务投影，不根据鱼 ID 大小、背包现存数量或展示名称推断。
- 单鱼奖励以源配置稳定奖励 ID 防重，金额使用源 BigNumber 契约，保留金币与材料类型；失败不能写成已领，改请求 ID 也不能重复领取。
- 获取鱼只产生图鉴解锁与领取资格；领奖必须经过显式命令。历史已解锁未领取的条目继续有资格，查看状态不作为领取前提。
- 正常图鉴集齐后的领枪和装备是独立命令；永久拥有任意合法枪即满足鱼潮开放，不要求枪已装备。参与及扣费时仍需有效装备。
- 变异图鉴枪强化按源规则自动登记并报告，不因此授予枪。源端已有枪强化可以先于枪拥有这一事实必须保留。
- 本次基线不模拟付费订单或凭空授予付费枪；通过已有源接口构造的合法非图鉴枪拥有状态可用于开放条件回归。

### 3. 寻宝兽与投掷

- 取消正式成长策略中固定近距离选点的限制。默认使用源投掷准备结果及落点流程提供的自然可达目标，按源时序完成最终入水确认；不在 Python 中写力量到水域的替代阈值。
- 开放事实取源存档的永久资格：首次服务端确认最终数值落点位于第四水域或更远时开放。拥有足够力量、处于第四区场景、选点尚未最终入水或鱼品质较高均不替代该条件。
- 该次投掷即可获得源规则允许的废料，此前投掷不授予废料。继续结算已合法持有的其他资产和奖励，不把寻宝兽未开放误解为材料钱包不可使用。
- 仅在源服务允许时调度寻宝兽专属养成；重生后仍保留开放资格。查询现有初始境界不能代替资格判断。

### 4. 鱼潮已确认数值近似

| 参数 | 本次确定口径 |
| --- | --- |
| 正常完成每场获取 | 固定 5 颗随机蛋，表示成功取得蛋，不表示五次命中 |
| 前台占用 | 固定 120 秒；换弹时间已包含其中，不再额外叠加 |
| 互斥行为 | 暂停炸鱼、锻炼；本场期间不调度其他主动消费或装备切换 |
| 后台行为 | 鱼厅、已开放寻宝兽的合法生产，以及源规则允许的孵化等继续推进 |
| 换弹 | 固定 6 次；每次费用读取本场装备枪的源配置 |
| 成本 | 6 × 本场锁定的单次材料费用，以源 BigNumber 精确结算 |
| 随机 | 复用源蛋随机服务的区域与变异分布；允许抽到相同配置的多颗蛋，实例身份不同 |
| 枪伤害 | 记录真实枪及强化状态，但本版不根据伤害增加或减少正常场的 5 颗收益 |

- 鱼潮开场间隔读取源配置。当前快照为 600 秒间隔、120 秒生成窗口，不能把这些值当成永久生产常量。每场 5 颗、占用 120 秒与换弹 6 次是独立的模拟策略参数，写入运行清单。
- 每场直接模拟玩家成功取得的蛋，不建立共享场景蛋池，不模拟每场最多生成数量的耗尽或其他玩家抢夺；报告必须标明此近似，不能据此评价实际竞争、射速、命中率或枪械战斗收益。
- 当前源随机入口使用区域输入 1。宿主复用这一入口，不因玩家力量、已满图鉴或装备枪自行更改供给分布；源入口后续变化须显式更新模型身份。

### 5. 为可执行性确定的模拟约定

以下是规格采用的边界约定，区别于用户明确指定的 5 颗、120 秒和 6 次。它们属于模拟策略，不修改生产玩法。

- **房间时间。** 使用固定、可记录的房间时间原点，按源绝对时间分槽规则计算场次。离线不停止场次时钟，重连不重新倒计时，不补发错过的场次。每个玩家每场至多参与一次；默认仅在开场边界尝试加入，不模拟中途加入。
- **完整参与。** 开场时必须在线、已开放鱼潮、有合法装备枪，并且距玩家计划下线至少还有 120 秒；否则跳过并记录原因。正式运行的截断或 checkpoint 边界不等于玩家下线，允许保存进行中的场次。
- **材料不足。** 开场按当前枪报价检查整场六次预算；不足则整场跳过，不扣费、不发蛋，也不占用 120 秒。不会按材料比例猜测少拿几颗。此约定取代讨论中尚未定稿的“可能少拿”建议。
- **容量不足。** 开场先按源规则结算已到期蛋，再检查至少五个可用蛋位；不足则整场跳过，不收费。正常场中不再调度其他主动发蛋行为。最终入包仍必须逐项通过源服务，不强行突破容量或把未入包蛋算成收益。
- **开场扣费。** 锁定枪、单次报价和场次身份，在同一虚拟开场时点通过源换弹服务与模拟原生适配器完成六次成功换弹的经济结算。模拟适配器不声称产生了真实原生弹药或命中证据。材料总额预检与前台互斥保证正常场有足够预算；每次回执保留身份与实际扣款，恢复不能再次扣费。
- **结束给蛋。** 完整占用 120 秒后，按固定场次和蛋序号取得五个随机结果，通过源蛋服务发放。孵化截止时间从实际入包时刻按源规则计算，不在开场提前产鱼。逐颗入包状态可恢复；发生服务异常时保留已受理部分和失败证据，不能重抽、补发已入包项或宣称该场已成功。
- **边界调度。** 调度器预知开场边界，避免启动跨越该边界的普通前台动作；可结算并停止锻炼。已提交的投掷或交易不被强行回滚；无法合法结束时本场跳过并说明。其他当前普通行为优先级只在这些边界与新增领取行为处调整。
- **领奖策略。** 默认在空闲决策点优先处理可领取的单鱼奖励与枪奖励，按稳定奖励 ID 顺序，每次领取占用 1 秒；装备操作也占用 1 秒。鱼潮参与中不插入领取。正常图鉴首次可领和实际领枪时间分别报告。
- **装备策略。** 默认装备已拥有枪中当前源攻击力最高者，同值按稳定枪 ID 决胜；明确更换后会按新枪费用收费。这是玩家策略，不修改“领枪不自动装备”的源规则，且不宣称它在固定五蛋模型下经济最优。
- **同秒顺序。** 先结算截至该时刻的源后台状态及到期事务，再处理已开始动作的完成，然后判定场次进入资格，最后开始普通新动作。若恰为计划下线，先按在线窗口结束条件判定，不新开鱼潮或领奖动作。

### 6. 宿主接口与恢复

- 扩展现有版本化会话协议和能力查询，覆盖图鉴及待领奖励投影、领取、枪拥有与装备、寻宝兽开放、可达落点、鱼潮状态、换弹回执、蛋库存与孵化结果。沿用查询、命令、虚拟时间推进、checkpoint 和 restore 的单一会话边界，不为每个系统另建进程或服务。
- 新操作在启动时检查宿主能力，缺失则给出明确诊断，不把旧宿主当成新模型继续产报告。操作和查询字段以稳定业务身份及源 BigNumber DTO 传输。
- 既有换弹服务支持原生依赖注入，优先用宿主适配器承接；保留源报价、钱包事务、受理、成功结算及防重语义。源蛋服务的通知和时间依赖同样适配，不引入真实 UI。
- 当前蛋入包会产生后续孵化随机种子；不能只固定抽蛋 RNG。所有新增随机事实，包括每颗蛋的孵化种子，必须进入确定性来源及重放契约。优先使用现有可注入能力；必要时在源端增设窄的随机提供者入口，生产默认行为保持不变。
- 为场次、六次换弹、五颗蛋分别使用稳定操作身份。checkpoint 保存或可确定性重建当前场次、剩余占用时间、已扣次数及金额、已确定随机结果、已入包蛋身份、未完成回执和领取进度。
- 源蛋 Grant 的 sourceId 不能被假定为跨会话永久防重凭证；宿主需要将已受理事实与现有整会话重放契约结合验证。同请求重试、通知或保存延迟都不能被当成新奖励。
- 模拟停止在第 60 秒时不提前给蛋，也不把未消费的第 60～120 秒算成完成。恢复后只推进剩余时间，源后台生产照常；重放与连续运行的业务回执和最终资产一致。
- 代码、策略或导表身份变化时继续拒绝不兼容 checkpoint，保留历史可读报告。

### 7. 输入、账本和报告

- 生产导表快照保持只读；加入图鉴奖励、枪、蛋和鱼潮实际依赖的配置与规则身份。缺失或非法的实际依赖应形成业务诊断，不使用零金额、默认概率或本地复制表静默替代。
- 正式运行记录源代码、IGESS 适配器、导表快照、Lua 版本、种子、场景、画像及策略摘要；新增鱼潮参数、房间时间原点、入场条件、落点和领取策略均参与归因。
- 分别记录图鉴解锁、奖励领取、正常图鉴完成、领枪、装备、枪强化、寻宝兽开放、鱼潮参与与跳过、六次费用、蛋入包和孵化事件。
- 金币与材料统计区分一次性图鉴奖励、既有鱼厅与加工收入、卖鱼材料及换弹支出。换弹手续费是支出；领取鱼厅待领金额仍是转账，不能与新奖励一起重复计算。收入观察必须识别实际源回执，而不是因只看到钱包下降而丢失同段后台收入。
- 一次性奖励可纳入在线总获取量，但单独列示；报告不得把它解释成稳定每秒生产能力。每场成本展示实际已扣总额，孵化前的蛋不计作已获得鱼或鱼厅产出。
- 增加首个满正常图鉴、首枪领取、首次参与鱼潮、首次寻宝兽开放的累计在线时间；并保留墙钟场次时间，解释离线错过。
- 单鱼图鉴解锁、一次性领取和系统开放分开统计。系统进展使用实际源提交的开放或永久强化事实；反复参与鱼潮、换弹、重复鱼和重复查询不增加系统开放次数。新增来源参与同一进展统计时按业务身份去重。
- 汇总每场参与、跳过原因、占用时间、获得及孵化蛋数、金币与材料奖励、换弹费用及期末库存。明确当前枪伤害未影响固定五蛋收益这一解释边界。

## Testing Decisions

用户已确认测试边界：**以现有同源 Lua 会话接口验证规则、账本和恢复，以 IGESS 正式运行验证接入与报告；本次不要求编辑器、真机或 DS。**

- 好的测试通过公开查询、命令回执、时间推进和可恢复状态断言外部行为，不断言私有调用顺序、辅助函数数量或代码结构。主要测试边界保持为一个版本化宿主会话；正式工作流检查用于确认产物交付。
- 沿用源项目已有宿主测试与 CLI 跨进程 replay 测试；复用 IGESS 正式同源 smoke、checkpoint 输入变更拒绝、批量与逐秒模式等价、在线采样不改变业务及收入观察测试。已有图鉴领奖、枪规则、投掷开放、蛋入包与孵化测试提供 fixture 和服务行为先例，不在 IGESS 复制算法期望。
- 使用受控 fixture 在会话边界构造可重复边界条件；fixture 仅用于机制验证，正式数值结论必须来自只读生产快照。

验收覆盖：

1. 同鱼同变异重复捕获只产生一次图鉴资格；不同变异独立。出售、重生和恢复保留历史进度。
2. 正确领取金币与材料，包括大于普通浮点精确范围的金额；同请求与新请求重复领取均不重复入账。失败不标已领，历史未领奖励可领取，来源配置非法时明确拒绝。
3. 未满图鉴不能领枪；满正常图鉴后领取才拥有，拥有后才开放鱼潮；合法非图鉴枪也能开放。未装备不能开始需装备的参与操作。变异强化沿用源语义，不能凭强化获得枪。
4. 固定近落点被移除后，自然可达落点随源力量规则变化。第四水域边界内外、力量足够但实际近投、选点未入水均准确；首个有效达标投掷立即有废料，之前为零，后续重生不关系统。
5. 未开放寻宝兽时，合法卖鱼和图鉴材料仍能入账；寻宝兽专属操作遵守源资格。
6. 正常场恰好占用 120 秒、获取五个独立实例、扣六次源费用；费用为零合法，负值或非法报价拒绝。同配置蛋可重复出现，不执行去重重抽。
7. 参与期间无投掷奖励或锻炼力量；鱼厅、合法加工及源孵化时间仍推进，换弹耗时不额外叠加。
8. 预算恰好足够与差一个最小货币单位的行为明确；不足场零收费、零发蛋、零参与耗时。高阶枪按实际装备费用，图鉴攻击加成不提高单次换弹价。
9. 开场蛋位恰好五个与不足五个、蛋到期释放容量、鱼包满导致孵化阻塞均遵守源服务；腾位后孵化不丢鱼或重抽。确认孵化鱼进入源图鉴及后续奖励链。
10. 对齐开场、生成窗口、离线、重连、在线剩余 119／120 秒和同秒下线边界。不同采样间隔不增加参与次数，不补领离线场次，不产生负的剩余时长。
11. 分别在换弹前后、鱼潮中途、逐颗发蛋之间、孵化到期前后以及领奖后恢复；跨进程连续与分段结果的资产、随机事实、回执、场次及操作计数一致。
12. 换弹或蛋服务保存、通知、回执延迟不会重复扣款或重复发蛋；已受理但未完成副作用的结果不当成未发放重试。真正异常保留失败运行与证据，不返回正常完成场。
13. 快速时间推进不得越过鱼潮或孵化边界而漏算；与逐秒参考模式的最终状态与业务事实一致。若快速路径暂不支持某新边界，应回落准确推进而非改变结果。
14. 收入观察能核平期初余额、合法收入、各项支出与期末余额；图鉴奖励、领取转账、换弹、加工与卖鱼不重复或错分。报告不会把单鱼领奖数量当成系统开放数量。
15. 缺宿主能力、缺依赖表、非法奖励、代码或导表变更的 checkpoint 均给出清晰失败。源输入文件在验证前后保持不变。
16. 通过正式工作流产生 smoke 及 1／7／30 天报告，登记运行清单、源成长与行为产物、标准事件和 checkpoint；长场景报告失败不能宣称正式运行成功。运行结果允许揭示长期无法开放或无法负担等数值问题，不以修改生产表强行使其通过。
17. 新依赖能被现有源码隔离打包流程解析；已有运行包等价性与交付审计检查继续通过。此项验证不自动发布或推送执行工具包。

## Out of Scope

- 旧 fish Python 模型的新功能、规则同步、重新调参或跨后端数值基线比较。
- 编辑生产 Excel、Luban 数值、生成 JSON 或 Lua 表；正式数据仍由策划修改并导出。
- 真实鱼潮场景生成、漂流、碰撞、寻路、命中、逐发弹药、原生换弹动画、多人抢蛋及枪械战斗平衡。
- 为模拟每场五蛋而修改游戏生产掉落、换弹次数、费用或全局开放规则。
- 付费订单、商品定价、购买计划和自动授予付费枪；只保留源规则对任意合法枪拥有的兼容。
- 图鉴 UI、查看红点、粒子、教程、网络复制、客户端交互与实际 DS 验收。
- 新增任意奖励公式、重新设计正常／变异图鉴目标或新增累计进度奖励体系。
- 自动迁移旧 Python checkpoint、删除历史报告、发布或推送 GameBalancer。

## Further Notes

- 用户明确确认：仅使用 fish_source；开放口径跟随游戏当前实现；鱼潮正常场为五颗随机蛋、两分钟前台占用、六次换弹；测试沿用已有同源会话与正式运行接口。
- 入场不足整场预算或五个蛋位时跳过、结束时发蛋、领取和装备各一秒、最高源攻击力选枪等是本规格的实施约定，未冒充用户逐项指定的玩法规则。修改这些策略需更换策略身份并重建对应基线。
- 建议按“图鉴与寻宝兽 → 鱼潮与孵化 → 报告及正式基线”实施；首阶段结果只能标明已覆盖范围，不能宣称整份规格完成。
- 当前已有的同源模拟报告不能自动补出新系统行为。新报告必须重新运行；改版前后成长差异同时包含规则和策略变化，不作为单字段调表效果。
- 遵循现有分发与源码隔离 ADR：运行本地离线，生产快照只读，新 Lua 能力随已有运行包交付，报告不泄露实现源码，发布另行处理。
- 本规格发布不证明图鉴、鱼潮、寻宝兽已通过模拟验收，也不证明源游戏引擎侧功能已通过实机验收。

## Answer

01–07 全部实施并解决，双仓集成分支为 `feature/fish-source-unlocks-and-tides`。公开会话、恢复、账本、源码隔离运行包与正式 smoke / 1 / 7 / 30 天基线已完成自动验证，Standards 与 Spec 审查问题全部关闭。详见 [实施验证记录](verification.md) 与 [最终交付票](issues/07-formal-baselines.md)。

生产配置保持只读，旧 fish 历史保留，仅维护 fish_source。当前生产表的首日鱼潮材料不足及 30 天观察到的 20 个单鱼奖励配置缺口均已明确记录；未为促成参与或领取而修改输入。本次不声称源游戏的编辑器、DS 或实机已验收；用户验收另待确认。
