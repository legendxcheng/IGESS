# Fish 同源模拟查询性能优化

Status: ready-for-agent

日期：2026-10-28。来源：用户反馈一周模拟约需七分钟，在性能定位后确认优化并调用 `to-spec`、`to-tickets`、`implement`。实施中首轮配对仅节省约 12%，用户明确要求“至少比原来快一倍”；目标更新为同输入一周端到端耗时至少减半。

实施追加范围：允许优化精确大数的内部整数运算，保持原精度、舍入、错误与公开接口；先在隔离候选验证旧实现差分，再接入正式长程验收。此范围不授权近似计算、改经济公式或跳过业务校验。此前仅限查询的约束以此追加范围为准，其余排除项继续有效。

## Problem Statement

数值策划每次调整导表后，需要通过正式运行观察一周的成长与经济变化。一次模拟等待约七分钟，拖慢了试调、比较、再调整的循环。

最近一周运行的引擎耗时为 433.118 秒，其中源执行与交互为 430.996 秒，启动、输入校验、checkpoint 和关闭合计约两秒。当前已经启用等价批量推进；仅调整启动或报告生成不能解决主要问题。

对当前输入的首日诊断记录了 1,183 次完整状态查询，含通信往返共约 10.629 秒；推进请求约 3.035 秒，报告生成约 0.376 秒。Lua 指令采样进一步显示查询、鱼产出计算、大数运算和存档处理存在显著开销。完整状态响应仍多次构建鱼厅等投影，相关服务分别获取存档副本，随后编码并发送完整状态。

这些数据支持优先优化查询路径，但首日不能代表后期背包和收集规模，性能探针本身也会增加开销。历史七分钟记录用于说明症状，不直接作为修改后的严格测速基线。

## Solution

保持当前正式运行入口、玩家策略、生产导表、精确结算和报告内容，通过减少查询中的重复工作缩短等待时间：

1. 对输入未变化的派生计算复用原源规则计算结果，优先处理鱼厅生产率及其相关投影；余额、待领金额、时间和 revision 仍反映当前状态。
2. 在一次只读查询范围内减少重复获取和复制完整存档，让相关投影使用同一个一致观察时点，同时保留对权威存档、缓存和调用方的隔离。
3. 首次观察即提供后续成长观察需要的幸运值，避免对同一状态完整重查；幸运值与真实投掷共用源前置映射，查询不再计算会被丢弃的假投掷奖励。真实投掷的随机链和完整奖励结算保持原样。
4. 对同一套冻结默认规则下的宿主观察做一次完整存档验证，再调用各源服务内部投影。原公开 Query 和所有写流程保留原校验；这不是为自定义规则服务提供免校验入口，投影调用方必须保证规则和已验证快照一致。
5. 完整背包在一次评估/排序后返回全部条目，保留现有公共分页接口和模拟原有完整 DTO。对一次同步源计算内重复的鱼种/变异/等级组合复用纯计算结果，返回的大数和条目仍独立；不跨操作缓存规则或实例，不改变神兽参考鱼与动态结算。

6. JSON 编码复用有界不可变字段名，对精确匹配的大数 DTO 使用等价字段顺序与标量编码；保持协议文本、转义和非法值拒绝语义。

完成上述各项的等价性和性能验证。合并执行与查询请求、增量状态协议和批量推进算法改造不纳入本轮。优化默认作用于现有同源运行，无需策划切换策略或接受精度下降。

交付包括可归因的优化前后结果、正式报告及测速证据；用户确认的验收门槛为端到端至少 2 倍速度，不能以局部热点倍率代替整周结果。

## User Stories

1. As a balance designer, I want weekly simulations to finish faster, so that I can complete more tuning iterations in the same working session.
2. As a balance designer, I want to keep using the existing formal simulation entry, so that performance work does not add a new operating procedure.
3. As a balance designer, I want simulations to execute the source Lua rules, so that faster results still describe the current game.
4. As a balance designer, I want the selected production export to remain read-only, so that a performance change cannot alter my tuning inputs.
5. As a balance designer, I want player priorities and action durations to remain unchanged, so that differences cannot be explained by a different simulated player.
6. As a balance designer, I want all five-minute online samples and boundary observations preserved, so that faster runs retain the same report detail.
7. As a balance designer, I want exact BigNumber balances and quotes preserved, so that large values do not change purchasing or progression decisions.
8. As a balance designer, I want identical random outcomes for identical inputs and seeds, so that I can attribute changes to tuning rather than the optimizer.
9. As a balance designer, I want unchanged fish production calculations to be reused, so that repeated observations avoid unnecessary work.
10. As a balance designer, I want current balances, pending income and revisions on every observation, so that cached calculations never hide new income or spending.
11. As a balance designer, I want fish upgrades, sales, deployment and hall changes reflected immediately, so that strategy decisions use the current inventory and production rate.
12. As a balance designer, I want rebirth, output multipliers and timed effects reflected immediately, so that permanent and temporary progression remain accurate.
13. As a balance designer, I want catches and egg hatching reflected at the existing observation points, so that collection milestones retain their original timing.
14. As a balance designer, I want codex claims, gun ownership, equipment and unlock changes reflected immediately, so that rewards and tide eligibility remain correct.
15. As a balance designer, I want online and offline transitions to retain their current settlement behavior, so that simulated income is not inflated or lost.
16. As a balance designer, I want pending throws, tides, eggs and ordinary actions preserved at truncation, so that stopping a run does not complete work early.
17. As a balance designer, I want resumed runs to match uninterrupted runs, so that I can safely continue a long simulation.
18. As a balance designer, I want request identities and retry receipts preserved, so that optimization cannot duplicate charges or rewards.
19. As a balance designer, I want collection and fish-pool milestones preserved, so that the growth report remains comparable after optimization.
20. As a simulation maintainer, I want multiple projections in one query to observe a consistent state, so that snapshot reuse does not produce mixed revisions.
21. As a simulation maintainer, I want returned values to remain independent of authoritative state and cached values, so that callers cannot mutate future simulation results.
22. As a simulation maintainer, I want caches isolated by session and rebuilt after restoration, so that players and runs cannot contaminate one another.
23. As a simulation maintainer, I want invalid input and rejected operations to remain visible, so that caching cannot turn a failure into a stale successful response.
24. As a simulation maintainer, I want source and adapter identities to change when their code changes, so that performance results remain traceable.
25. As a balance designer, I want performance measured on matched weekly runs without profiling overhead, so that the reported improvement is credible.
26. As a balance designer, I want variation and remaining bottlenecks reported, so that I understand the practical limits of the improvement.
27. As an execution-toolkit owner, I want local optimization and toolkit publication treated separately, so that I know which users have actually received the faster runtime.

## Implementation Decisions

1. **保持同源分工。** Python 继续负责玩家意图、调度、采样、协议与产物；Lua 源服务继续负责合法性、价格、生产、扣款、奖励、随机与重生。禁止在 Python 复制经济公式，或以近似数值替换精确大数路径。
2. **范围限于查询计算和观察快照。** 优先调整 Lua 模拟查询组合、鱼厅生产投影及必要的源只读查询接缝。IGESS 侧主要承载差分验收和性能测量。源交易流程、生产结算算法、行动调度和线协议行为保持原契约。
3. **缓存派生值，不缓存整份活状态。** 区分鱼产出、规则报价等可复用计算与余额、槽位待领、revision、时间、飞行、鱼潮、蛋状态等动态字段。不能因鱼列表未变就返回旧余额或旧状态。查询选项对返回结果的影响也必须保留。
4. **依据实际依赖定义失效。** 缓存身份来自被复用计算真实读取的数据和本会话冻结规则，不能仅用对象引用、鱼数量、数组长度或全局 revision 代替依赖分析。相关依赖包括鱼实例、配置身份、变异、等级、位置、鱼厅等级、神兽参考鱼以及实际参与计算的重生或其他倍率；具体范围沿源规则读取路径确认。
5. **库存与资格变化不延迟。** 若复用背包、图鉴、枪或行动报价的已有缓存，保留各自对永久解锁、领取历史、拥有与装备、寻宝兽开放、库存以及存档变化的失效条件。无充分收益证据时不扩展到新的缓存领域。
6. **单次查询内复用观察快照。** 在一个同步只读操作中尽量只获取一次一致快照，交给相关纯投影计算。快照作用域不得跨越业务命令、生产结算、回调或会话切换。若流程可能修改状态，先结束该作用域并重新获取。
7. **保持存档封装。** 不将权威可变存档暴露给查询调用方，不全局替换存档服务为返回共享可变表。若增加内部快照投影入口，原公开查询继续通过校验与独立结果契约运行；只读共享必须由实现与测试共同保证，不能仅依赖注释。
8. **结果属于调用方。** 修改一次返回的嵌套字段，不得改变权威存档、缓存或之后的返回值。缓存拥有独立结果，源存档后续原位修改也不能悄悄修改缓存内容。允许保留必要的边界复制，不追求消除所有复制。
9. **缓存按会话存活。** 不在多个会话、数据快照或不同玩家之间共享可变缓存。恢复和重新建会话后按当前状态重建缓存，不写入 checkpoint，不以相同 revision 推断不同会话状态相同。
10. **查询保持纯观察。** 不推进时间、消费随机数、触发奖励、修改 revision 或改变请求顺序；非法状态和源查询错误仍按现有协议暴露，不能回退旧成功值掩盖错误。
11. **兼容性边界不放宽。** 维持现有协议与 checkpoint 格式及输入身份校验。实现改变必须反映在源或适配器摘要中；不得为了跨版本对照绕过旧 checkpoint 的代码身份校验。跨版本差分与同版本恢复等价是两种独立验证。
12. **先冻结基线，再修改。** 当前工作区包含既有未提交变更，应冻结实际代码、配置和只读导表作为优化前基线，记录源码与适配器身份，不把旧提交或旧报告自动当成当前基线。不回滚、覆盖或混入无关修改。
13. **性能探针独立于正式路径。** 沿用现有可运行的诊断和计时方法；探针只用于热点归因，不进入交付代码，不参与最终加速倍率计算。保留诊断文件与正式测速文件的明确身份。
14. **文档随真实改动更新。** 若新增内部投影接缝、调整模块职责或验证方式，更新 Fish 技能与代码导航，以及受影响的项目说明。未变化的玩法口径无需重写。

## Testing Decisions

**验收接缝。** 主接缝是已有正式模拟入口：从冻结配置和导表启动真实 Lua，会经过策略、调度、源服务、checkpoint、登记与报告生成。用户已确认上一轮提出的“相同输入跑一周，核对事件、随机结果、最终状态及恢复等价性”的方向；本规格沿用该边界。仅在正式入口难以直接覆盖返回对象修改、跨会话隔离等条件时，补充已有 Lua 会话/公开 CLI 协议测试，不建立另一套经济模型。

**好测试的标准。** 检查外部可观察的状态、回执、事件、失败结果和恢复行为，不断言私有缓存结构、函数调用次数或缓存命中率。耗时在独立基准中评估，不给普通功能测试加入易抖动的毫秒阈值。测试夹具只制造边界，不进入生产测速导表。

1. **正式差分。** 优化前后使用相同场景、种子、策略、行动耗时、在线窗口、导表快照、采样周期及推进模式。四份核心业务产物逐字节一致；源操作与回执历史、最终可观察状态、行为恢复字段、随机结果和 revision 一致。只对运行身份、代码相关摘要、运行目录和耗时等必然变化的元数据使用明确白名单，不能宽泛忽略业务差异。
2. **重复观察与对象隔离。** 同状态重复查询结果一致，查询本身不改变状态。修改返回值及其嵌套表后再次查询，结果仍正确；会话 A 的读取或修改不影响会话 B。覆盖有、无幸运值投影的查询选项。
3. **鱼与鱼厅失效。** 覆盖捕获、孵化、出售、升级、上阵、撤下、换位、鱼厅升级，以及神兽引用的普通鱼升级或撤下。既测改变计算依赖的操作，也测只改变余额或时间的操作；结果与优化前源服务一致。覆盖超过单页容量的库存。
4. **动态状态与资格。** 覆盖生产推进、领取、花费、两类重生、实际相关倍率变化、在线/离线切换，以及图鉴领取、枪拥有/装备和寻宝兽开放变化。缓存不能滞后一轮更新观察、报价或资格。已有非法状态、合法拒绝和大数边界回归继续通过。
5. **生命周期与恢复。** 在自然飞行、普通动作、鱼潮、蛋孵化/满包阻塞及待完成副作用边界截断，比较同一版本的连续运行和分段恢复运行。比较最终状态与源历史；分段事件和采样按现有本段/生命周期契约拼接或对齐，不能要求本来就有不同范围的报告整份相等。重试保持请求身份，不重扣、不重奖。
6. **准确与批量推进。** 复用现有逐秒/等价批量差分，确认只读优化没有破坏其等价性；本轮不改批量算法。
7. **正式产物。** smoke 必须登记成功，manifest、核心数据、checkpoint 与报告齐全；报告指标、收集成长与鱼池成长继续与事件一致。缺 Lua 或源仓库导致的 skipped 必须报告，不能算集成通过。
8. **性能测量。** 冻结同一组输入，在同机、同 Python/Lua 环境下串行交替运行优化前后版本；不得同时跑其他模拟或测试。首日和一周场景各取至少三组配对测量，记录每次端到端正式工作流耗时、中位数、最小/最大值，以及源执行、启动、checkpoint、产物和报告阶段。记录可获取的系统环境与负载信息，避免将机器波动解释为收益。
9. **性能通过条件。** 一周是主验收场景：三组配对均应更快，且端到端中位数不超过冻结基线的一半（至少 2 倍速度）；首日不得出现可重复的性能回退。若方向不稳定，扩充至五组并分析波动，仍无法区分收益与噪声则不得标记性能验收通过。报告实际节省秒数和百分比，不以带探针的首日数据外推一周，也不以历史 433 秒直接计算倍率。未达到减半目标时必须明确记录未达标。
10. **覆盖后期工作量。** 一周完整场景必须包含真实后期库存与收集状态，不能仅用 smoke/首日推断。默认不跑三十天；仅当本轮发现一周不足以覆盖的增长型开销或状态问题时，增加有明确目的的长程验证。

测试先例包括：正式入口的真实 Lua 产物和输入摘要测试、准确/批量模式等价测试、完整库存与大数联合测试、自然飞行和鱼潮恢复测试、Lua 宿主的查询返回值隔离及缓存失效测试，以及上一轮性能优化的核心产物/解压 checkpoint 历史比较脚本。具体导航见 Further Notes。

## Out of Scope

- 修改生产 Excel、导出 JSON、经济公式、随机算法或 BigNumber 精度。
- 修改玩家策略、行为权重、行动耗时、在线时段、自然落点、采样密度、事件观察时点或报告口径。
- 合并执行与查询请求、增加增量 DTO 协议、迁移 Python 策略到 Lua、并行拆分单个玩家时间线。
- 改写逐秒/批量推进算法、跳过孵化或定时器边界、取消回执或历史来换取速度。
- 修改旧 checkpoint 的跨版本兼容策略，或自动迁移历史运行。
- 恢复旧 Python Fish 后端、替换 Lua 运行时、引入新的部署依赖。
- Dashboard 交互改版、运行历史清理或其他独立维护功能。
- GameBalancer 构建、发布、提交或推送；本地源码优化不会自动更新冻结的执行工具包。
- UE、PIE、DS、网络复制、碰撞、原生武器或多人竞争验证。

## Further Notes

### 证据与导航

- 当前项目契约：[README](../../projects/fish_source/README.md)、[RoadMap](../../projects/fish_source/RoadMap.md)、[领域术语](../../CONTEXT.md)。
- 技能与代码导航：[fish_sim](../../.agents/skills/fish_sim/SKILL.md)、[code-map](../../.agents/skills/fish_sim/references/code-map.md)。
- 本次首日诊断：[Python 往返计时](../fish-source-performance/diagnosis-20261028-profile-day_1_growth-timing.json)、[Lua 探针运行计时](../fish-source-performance/diagnosis-20261028-profile-lua-day_1_growth-timing.json)、[Lua 热点采样](../fish-source-performance/debug/diagnosis-20261028-profile-lua-day_1_growth-lua.json)。两次首日的四份核心业务产物和 checkpoint 逐字节一致，仅证明该次探针未改变结果，不代表优化已经实施或验证。
- 七分钟症状：[一周运行清单](../../projects/fish_source/runs/20261028T050028132400Z-week_1_growth/output/run_manifest.json)。该运行与首日诊断的模型身份不同，不能混作严格性能对照。
- 上轮优化参考：[验证记录](../fish-source-performance/verification.md)、[计时脚本](../fish-source-performance/timed_simulation.py)、[比较脚本](../fish-source-performance/compare_results.py)。旧硬编码路径和旧运行身份须按本轮冻结基线更新或抽成参数，不覆盖旧证据。
- 现有正式测试：[formal](../../tests/test_fish_source_formal.py)、[joint](../../tests/test_fish_source_joint.py)、[natural landing](../../tests/test_fish_source_natural_landing.py)、[tides](../../tests/test_fish_source_tides.py)、[pool growth](../../tests/test_fish_pool_growth.py)。
- 原游戏入口为当前配置解析的 `engine.source_runtime.project_root`，当前指向 `E:/fish-oasis`。主要相关模块为 `simulation/Query.lua`、`simulation/Host.lua`、源鱼厅查询与生产规则、存档观察服务；协议与缓存隔离先例为源仓库的 `tests/simulation_host_test.lua` 和 `tests/simulation_cli_test.py`。实施前继续遵守源仓库及更深目录的适用指引。
- 本地发布按[问题跟踪约定](../../docs/agents/issue-tracker.md)完成，使用规范标签 `ready-for-agent`。实施与追加减半目标对应 `issues/01` 至 `issues/05`。

### 风险与后续

主要正确性风险是缓存遗漏依赖、共享可变表、用全局 revision 导致缓存每秒失效，以及复用旧快照掩盖源状态更新。实施应优先消除有实测证据的重复工作，避免无收益的缓存扩张。

如果前两项通过正确性验证但性能收益仍不足，应记录剩余热点并另行提出协议或推进优化范围，不将本规格自动扩展为大规模重构。内部只读投影调整可能落在游戏源仓库；这不授权改变游戏规则或削弱生产存档隔离。

发布遵守现有执行工具包 ADR：本地验证完成与分发仓库更新是独立工作。本规格不声称交付包已提速。
