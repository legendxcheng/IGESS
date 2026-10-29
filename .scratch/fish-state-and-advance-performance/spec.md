# Fish 状态观察与推进结算性能优化

Status: ready-for-human

日期：2026-10-29。

来源：用户在进一步性能评估后确认“按你的思路继续优化 1、2”，并调用 `to-spec`。本规格覆盖减少完整状态的重复构建与传输、优化已有时间推进与结算；本次发布规格，不自动进入实现。

## Problem Statement

数值策划修改导表后，需要反复等待整周正式运行，才能比较成长和经济变化。上一轮已将同输入整周运行的中位数从约 524 秒降至 229 秒，但等待时间仍影响调优迭代效率。

针对已交付版本的新一轮整周诊断中，正式运行耗时 214.5 秒：7,573 次完整状态查询累计 93.1 秒，2,702 次时间推进累计 76.0 秒，行动候选查询累计 7.4 秒。完整状态响应累计编码约 441 MB，其中 Lua 编码约 29 秒。背包、图鉴等未变化内容仍重复构建、复制或传输；推进已支持等价批量模式，但结算和逐秒回落仍有较大成本。

这些是带探针的归因数据，不是新增优化成绩，不能与此前 229 秒直接计算加速倍数。诊断已核对四份核心业务产物、完整最终状态、checkpoint 行为与源操作/回执历史一致。仅观察到事务存在两次完整存档复制，也不足以将其认定为最大的剩余热点。

## Solution

策划继续通过原有正式运行入口使用同一导表、玩家策略和采样规则，得到相同结果和报告，同时缩短模拟等待时间。

1. 在保持每个原有观察时点与完整逻辑状态的前提下，让未变化的状态部分复用已有投影或只传输变化部分。余额、时间、revision、资格及待完成行为始终及时更新。
2. 优化现有等价批量推进：复用输入未变化的生产计算；对需要处理定时任务的区间，评估能否按真实边界分段推进，减少不必要的逐秒工作。
3. 分别验证两条路线的实际收益，再验证组合结果。新一轮比较基线是当前已交付优化版，性能结论来自同机、同输入、无探针的整周正式运行。

## User Stories

1. As a balance designer, I want weekly formal runs to finish sooner, so that I can complete more tuning iterations.
2. As a balance designer, I want to keep the existing simulation entry, so that optimization adds no operating steps.
3. As a balance designer, I want the same selected export snapshot to remain read-only, so that timing comparisons do not change production values.
4. As a balance designer, I want unchanged player priorities and action durations, so that faster runs still represent the same simulated player.
5. As a balance designer, I want the same online and offline windows, so that performance work does not change available play time.
6. As a balance designer, I want all existing five-minute online samples and boundary observations preserved, so that reports retain their detail.
7. As a balance designer, I want identical seeded outcomes, so that tuning differences remain attributable.
8. As a balance designer, I want exact balances, prices, and rounding preserved, so that large values do not change progression decisions.
9. As a balance designer, I want unchanged income and expense accounting, so that wallet transfers are not mistaken for new production.
10. As a balance designer, I want growth milestones at the same observed times, so that collection and fish-pool reports remain comparable.
11. As a simulation maintainer, I want unchanged state sections to be reused, so that repeated observations avoid unnecessary work.
12. As a simulation maintainer, I want transport to omit unchanged state sections when supported, so that unchanged inventory and collection data are not repeatedly encoded.
13. As a simulation maintainer, I want each reconstructed observation to equal a complete query, so that strategy and reporting consumers see the same state.
14. As a simulation maintainer, I want field removal and empty collections represented correctly, so that reconstruction cannot retain deleted state.
15. As a simulation maintainer, I want dynamic balances and revisions refreshed at every existing observation point, so that decisions never use stale values.
16. As a simulation maintainer, I want catches, sales, upgrades, deployment, and hatching to invalidate the relevant projections, so that inventory changes are immediately visible.
17. As a simulation maintainer, I want reward claims, equipment, rebirths, and unlocks to invalidate their dependencies, so that cached eligibility and rates remain correct.
18. As a simulation maintainer, I want query options respected, so that optional luck data cannot leak between observations with different options.
19. As a simulation maintainer, I want independent returned objects, so that a caller cannot corrupt authoritative state, caches, or earlier observations.
20. As a simulation maintainer, I want session-specific observation identities, so that players and runs cannot share stale cache contents.
21. As a simulation maintainer, I want missing or mismatched transport baselines handled explicitly, so that incomplete state is never silently accepted.
22. As a simulation maintainer, I want the complete query interface retained, so that existing clients and differential checks remain available.
23. As a simulation maintainer, I want observation operations excluded from mutation history, so that transport changes do not alter recovery behavior.
24. As a simulation maintainer, I want restored sessions to rebuild observation caches, so that checkpoints do not depend on transient cache state.
25. As a balance designer, I want stable production inputs reused across settlements, so that repeated calculation does not increase waiting time.
26. As a balance designer, I want timers and hatching processed at their existing boundaries, so that batching does not shift rewards or unlocks.
27. As a balance designer, I want simultaneous events to retain their existing order, so that boundary outcomes remain deterministic.
28. As a balance designer, I want full-inventory hatching and later capacity recovery preserved, so that optimization does not lose or duplicate fish.
29. As a balance designer, I want buff activation and expiry respected, so that production intervals use the correct multipliers.
30. As a balance designer, I want truncation to preserve unfinished throws, actions, tides, and eggs, so that stopping a run does not finish work early.
31. As a balance designer, I want resumed runs to match uninterrupted runs, so that long simulations can be continued reliably.
32. As a simulation maintainer, I want unchanged rejection and rollback behavior, so that optimized execution cannot hide invalid states or partially commit rewards.
33. As a simulation maintainer, I want unchanged request identities and idempotency, so that retries do not duplicate charges or rewards.
34. As a simulation maintainer, I want exact revision and receipt equivalence, so that fewer internal steps do not change public behavior.
35. As a simulation maintainer, I want both optimization routes measured independently and together, so that complexity is justified by attributable benefits.
36. As a balance designer, I want repeatable end-to-end timing against the current delivered version, so that claimed improvements describe my actual workflow.
37. As a simulation maintainer, I want first-day runs checked for regression, so that weekly improvements do not penalize common short iterations.
38. As an execution-toolkit owner, I want local optimization and toolkit publication treated separately, so that delivery scope remains explicit.

## Implementation Decisions

1. **保持同源分工。** Python 负责玩家意图、调度、观察消费和产物；游戏 Lua 服务继续负责规则、合法性、价格、扣款、奖励、随机和生产。优化不建立第二套经济模型。
2. **基线重新冻结。** 冻结实施开始时的实际工作区源码、适配器、场景和所选导表，记录摘要。若与本次诊断身份不同，先说明差异并重测相关基线。不得把上一轮优化前版本作为本轮收益分母，不覆盖旧回执和冻结目录。
3. **保留完整查询接口。** 公开完整查询保持其输入选项、完整 DTO、只读行为和拒绝语义。新的状态传输能力通过显式能力协商启用，缺少能力时使用既有完整查询。不能将缺失字段直接作为“未变化”的隐含约定。
4. **完整逻辑观察不变。** 状态投影、传输与重建可以优化，但策略、收入观察、成长观察和报告模块仍在相同时间收到相同完整逻辑状态。不得以减少动作后查询、降低采样频率或延迟成长观察取得收益。
5. **按依赖划分可复用部分。** 根据真实读取字段识别背包、鱼厅稳定字段、图鉴、枪及其他候选投影的依赖。时间、余额、槽位待领、revision、飞行、鱼潮、蛋状态、有效 buff 和动态资格不能被整体缓存掩盖。是否引入某部分缓存由收益和依赖清晰度决定。
6. **缓存失效覆盖内容与上下文。** 缓存身份覆盖实际依赖及会话冻结规则，包含相关鱼实例、配置身份、变异、等级、位置、鱼厅等级、神兽参考鱼、重生倍率、解锁和领取历史。不能仅用对象引用、数量或全局 revision 代替依赖。不同查询选项必须得到各自正确结果。
7. **变化传输有明确基准。** 若采用增量协议，响应必须区分完整基准与变化响应，标明会话和基准身份，明确字段删除、空集合、数组顺序、缺失值和空值的语义。基准不匹配时不得继续拼接；只能在同一状态时点获取完整状态或明确报错，不能重放业务命令来修复观察。
8. **重建保持对象隔离。** 后续变化不能原位污染前一份观察；调用方修改返回对象不能污染权威存档、缓存或其他会话。尤其保留收入差分和里程碑比较所依赖的前后状态独立性。共享不可变内容需有可验证的隔离边界。
9. **观察协议不进入业务历史。** 新增观察操作必须显式归为只读，不推进时间、不消费随机数、不改变业务 revision，也不追加到 checkpoint 的源操作/回执历史。完整状态接口仍可用于审计与同版本验证。
10. **传输缓存不持久化。** checkpoint 不保存派生缓存或增量传输基准；创建、恢复和重新连接后从独立完整观察建立基准。源码与适配器身份继续严格校验，不放宽跨版本恢复限制。
11. **保留推进的准确对照路径。** 既有逐秒模式继续作为等价性参照，优化默认整合到已有等价批量模式，不新增玩家策略，也不把模拟速度选项变成经济语义选项。
12. **先归因推进成本。** 分清生产纯计算、存档处理、定时任务、孵化检查与批量回落的实际开销。分段推进和跨结算复用是待实验验证的候选，不预先宣称已经证明可行或有固定收益。
13. **复用纯生产结果。** 只缓存依赖明确且输入未变化的纯计算；动态余额、实际经过时间、生产边界与交易结果仍实时结算。不能缓存整份结算回执，不能以不同舍入顺序或浮点近似替换精确大数计算。
14. **按真实事件边界分段。** 若改造批量回落，应以定时任务、buff、孵化、既定观察点及玩家操作边界为限制，不越过可能改变行为的事件。只处理经证明等价的空区间；事件前后使用正确状态，并保持同一时刻已有执行顺序。
15. **保持特殊边界。** 覆盖鱼包满导致的孵化阻塞与容量恢复、保存或通知待完成、在线/离线切换、鱼潮阶段和自然飞行。时间推进仍接受原有合法时间输入，不因新分段实现暗中缩窄接口。
16. **结算与事务契约不削弱。** 保留最终回执、revision、幂等身份、异常、回滚及持久状态。不能简单跳过完整校验、取消回滚副本或暴露权威可变存档作为捷径。通用存档事务框架重写不属于本轮默认范围。
17. **组合必须可归因。** 状态观察优化与推进优化分别保留可比候选，先验证各自行为和收益，再验证组合。最终实现无需保留面向用户的实验开关；收益不足或不能证明等价的候选不接入。
18. **身份和交付同步。** 新增影响行为的适配模块、协议能力和源实现必须纳入既有运行身份。若模块职责、入口或维护契约变化，更新项目说明、Fish 技能与代码导航。本轮不构建或发布执行工具包。
19. **保留用户工作区。** 使用独立冻结目录进行候选实验，保留用户已有未提交变更，不回滚、清理或整文件覆盖无关工作。跨仓实现前遵循源仓适用指引。

## Testing Decisions

1. **主验收接缝是现有正式模拟入口。** 使用同一场景、策略、动作耗时、种子、所选导表、在线窗口、采样口径和推进模式，贯穿输入冻结、源执行、checkpoint、登记、产物与报告。无需另建简化模拟器。已向用户核对这一验收安排；发布时尚未收到针对该核对的单独回复，先按此前讨论的方案写入，后续补充直接更新本节。
2. **好测试观察外部行为。** 断言完整状态、回执、事件、随机结果、精确金额、失败结果、恢复和对象隔离，不断言私有缓存键、某函数调用次数、内部批量次数或易抖动的毫秒门槛。普通回归与性能测速分开。
3. **沿用已有差分工具。** 复用正式运行回执、核心产物逐字节比较、完整 Query DTO 比较以及解压 checkpoint 的源历史与行为恢复字段比较。只对白名单中的代码身份、运行路径和耗时元数据放行，不宽泛忽略业务字段或直接比较排序后事件。
4. **逐次观察差分。** 为状态传输候选增加独立诊断记录：在每个既有逻辑观察点记录消费者实际收到的完整状态及查询选项，与冻结完整查询基线按相同序列比较。不得额外推进时间或增加业务操作。诊断记录不加入正式性能计时。
5. **最少的补充接口测试。** 只有正式入口不易制造的条件，才使用现有 Lua 会话/CLI 或运行时接缝：完整状态与变化重建、字段删除与空集合、基准错配、首次观察、查询选项、能力回退、多会话隔离、返回对象被修改、非法存档与拒绝码。不得以重放写操作处理观察同步错误。
6. **推进对照。** 在现有源会话入口比较准确模式与等价批量模式，观察相同时间边界的完整状态、随机结果、回执、revision 和待完成副作用。覆盖边界之前、恰好边界、边界之后及同一时刻多个事件，覆盖原接口允许的非整数时间。
7. **覆盖缓存依赖变化。** 包括捕获、出售、升级、上阵/撤下、换位、鱼厅升级、神兽参考鱼变化、图鉴领奖、枪拥有/装备、两类重生、寻宝兽解锁、buff 变化；同时覆盖只变余额或时间的情形。不要只用重复读取静止存档证明真实库存变动时的性能。
8. **恢复与幂等。** 真实跨进程恢复与连续运行比较，覆盖飞行中、动作中、鱼潮中、蛋到期前后、满包孵化及待完成保存/通知。恢复重建观察基准不漏发、不重发奖励；重试保持操作身份。旧代码指纹不兼容的 checkpoint 继续被拒绝，不为差分绕过恢复身份检查。
9. **性能分阶段测量。** 两条候选先分别做整周正式对照，保留收益来源及失败候选记录。最终组合至少三组同机串行、无探针整周配对，并检查首日运行；不并行运行测试或其他模拟，记录已有系统负载和运行顺序。
10. **本轮性能验收。** 与本轮冻结优化版相比，三组整周候选均更快、中位数下降，且改进应超出基线重复运行的自然波动；首日无稳定回退。若差异不能与噪声区分，增加必要的少量配对或判定收益未证实。本轮未约定固定加速倍数，不把上一轮“两倍”目标自动移植过来，也不把查询局部收益当作整周收益。
11. **最终字节验收。** 最终配对使用实际拟交付源码字节、配置与适配器，不混入不同换行版本、不同导表或不同策略的成绩。报告包括原始耗时、范围、中位数、比较身份、等价检查与限制。
12. **现有回归作为先例。** 沿用完整观察隔离与拒绝码测试、完整库存查询、生产重复投影、精确大数、JSON 编码、源 CLI 恢复，以及正式运行、自然落点、鱼潮、鱼蛋、收入和成长报告测试。按实际改动选择并完成所需回归，明确既有失败和环境跳过，不把局部通过表述为完整套件通过。

## Out of Scope

- 整体重写 Python 或 Lua；迁移 LuaJIT；引入 C/C++、Rust 原生热点模块。本轮用户只确认了前两条优化路线。
- 更改生产导表、经济公式、玩家策略、动作耗时、随机链、大数精度、舍入、在线窗口或报告采样密度。
- 合并玩家决策、减少必要观察，或把多个有观察依赖的动作合为一条不可观察批次。
- 合并业务命令与查询、将整个玩家策略迁入 Lua、改成另一套后台模拟器。
- 重写通用存档事务框架，或取消写入校验、异常回滚和对象隔离。
- 放宽跨版本 checkpoint 身份约束，或将本轮差分等价误当作旧存档迁移授权。
- 并行多种子吞吐量工程、Dashboard 改造、报告视觉改版、历史数据清理。
- 自动提交、推送、构建或发布 GameBalancer；UE、PIE、DS 和多人行为验收。

## Further Notes

- 本规格发布于本地 Markdown issue tracker，状态为 `ready-for-agent`；规格就绪不代表已经实现、达到性能目标或完成人工验收。
- 本轮诊断材料：[摘要与等价检查](../fish-performance-next-20261029/summary.json)、[原始剖析](../fish-performance-next-20261029/profile.json)、[基线身份](../fish-performance-next-20261029/identities.json)。探针只注入临时运行副本，记录的身份指被测基线；内部计时可能嵌套，不能直接相加。
- 上一轮实际交付与性能依据：[查询性能验收](../fish-source-query-performance/verification.md)。其中旧版/候选命名仅属于上一轮，不能直接套用到本轮。
- 维护入口：[Fish 项目说明](../../projects/fish_source/README.md)、[进度](../../projects/fish_source/RoadMap.md)、[Fish 技能](../../.agents/skills/fish_sim/SKILL.md)。相关源宿主契约在源仓模拟说明中。
- 下一步实施前将本规格拆成可独立验证的工作项。若候选只能通过改变规则、减少观察或大幅扩大范围取得收益，应报告证据并停止该候选，不擅自扩大授权。

## Implementation Result

2026-10-29：用户已授权实施，技术验收完成，等待用户验收。状态观察与冻结生产复用已交付；事件分段未证明收益而丢弃。最终证据见 [验收记录](verification.md)。
