# Fish 完整查询的快照与校验复用

Status: ready-for-agent

日期：2026-11-01。

来源：QueryLuck 优化交付后的新一轮 Week1 性能诊断。用户确认“好的，请开始优化性能吧”，调用 `to-spec`，并确认沿用“完整查询结果差分、返回对象隔离和恢复验证、至少三组无探针 Week1 串行对照”的验收边界。本次产物为第一阶段实施规格；代码实现与收益验收尚未完成。

## Problem Statement

数值策划需要反复完成整周正式运行来检查成长节奏。已交付的幸运值查询优化减少了不必要的奖励求解，但完整状态查询仍反复复制同一存档、执行等价校验，增加每轮等待时间。

2026-11-01 冻结输入的最新诊断中，无探针 Week1 单次参考耗时 216.334 秒；带探针耗时 298.692 秒，11,228 次完整查询累计往返耗时 177.318 秒，占诊断总时间 59.36%。查询中共获取快照 103,666 次、校验 57,268 次，平均每次完整查询分别发生 9.23 次和 5.10 次；两组探针计时合计约 32.384 秒，快照计时已包含克隆。

无探针与带探针运行的核心业务产物、检查点业务内容及有序命令历史一致。这是定位重复工作的证据，不是可承诺节省 32 秒的依据。无探针参考运行启动时与准备收尾有短暂重叠，且当前导表与上一轮性能验收不同；必须重新建立本阶段正式性能对照。

## Solution

保持策划的运行入口、导表快照、玩家策略、采样与报告完全不变，减少单次完整查询内部的重复工作：在已证明同步只读的查询范围内，相关投影复用一份独立存档快照；只有针对相同快照、相同规则和相同校验选项的等价验证，才允许复用验证结果。

复用在本次查询结束后失效。下一次观察及每次写操作仍读取权威状态，并履行原有验证、错误与回滚契约。公开查询返回值保持独立，调用方修改结果不能影响存档、其他结果或其他会话。

第一阶段只实现这项优化，分别证明业务等价与整周收益。JSON 编码、普通鱼等级结果缓存及进一步幸运值映射优化保留为后续独立候选，不混入本阶段收益。

## User Stories

1. As a balance designer, I want weekly formal runs to finish sooner, so that I can complete more tuning iterations.
2. As a balance designer, I want to keep the existing formal-run entry, so that the optimization requires no new operating steps.
3. As a balance designer, I want the selected export snapshot to remain read-only, so that performance work cannot change production values.
4. As a balance designer, I want the same player strategy and action durations, so that a faster run still represents the same player.
5. As a balance designer, I want unchanged online windows and sampling points, so that reports retain their current meaning and detail.
6. As a balance designer, I want identical seeded rewards and action order, so that tuning differences remain attributable to data changes.
7. As a balance designer, I want exact balances and unclaimed production preserved, so that faster observation cannot change spending or income.
8. As a balance designer, I want unchanged growth events and milestone times, so that historical analysis remains comparable.
9. As a simulation maintainer, I want related projections to reuse one independent snapshot within a read-only query, so that they avoid copying the same state repeatedly.
10. As a simulation maintainer, I want equivalent validation results reused only within that query, so that repeated checks cost less without accepting invalid states.
11. As a simulation maintainer, I want different rule identities and validation options kept separate, so that one service cannot reuse another service's incompatible validation.
12. As a simulation maintainer, I want all existing validation failures and their precedence preserved, so that optimization does not conceal the original diagnostic.
13. As a simulation maintainer, I want queries that cannot safely share state to keep their original path, so that partial optimization remains correct.
14. As a simulation maintainer, I want every returned DTO to remain independently owned, so that callers cannot corrupt authoritative or shared state.
15. As a simulation maintainer, I want earlier observations to remain unchanged after later actions, so that income differences and growth detection remain accurate.
16. As a simulation maintainer, I want separate sessions to keep separate observations and validation state, so that players cannot contaminate one another.
17. As a simulation maintainer, I want each query to respect its options, so that optional luck and other fields cannot leak between requests.
18. As a simulation maintainer, I want catches, sales, fish upgrades and deployment reflected immediately, so that inventory and production observations stay current.
19. As a simulation maintainer, I want purchases, reward claims, equipment, rebirths and unlocks reflected immediately, so that eligibility is never derived from a stale snapshot.
20. As a simulation maintainer, I want time, online status and timed effects refreshed at each observation, so that state reuse cannot freeze dynamic fields.
21. As a simulation maintainer, I want full-capacity inventories and hatching transitions preserved, so that later-page items and blocked rewards remain visible.
22. As a simulation maintainer, I want write transactions to retain their own validation and rollback behavior, so that read optimization cannot weaken writes.
23. As a simulation maintainer, I want query failures to release temporary reuse state, so that a subsequent request cannot inherit partial results.
24. As a simulation maintainer, I want nested or reentrant queries isolated or handled by the original path, so that overlapping observation lifetimes cannot share unsafe state.
25. As a simulation maintainer, I want read-only queries to leave command history and random state unchanged, so that recovery and deterministic execution remain reliable.
26. As a simulation maintainer, I want temporary observation state excluded from checkpoints, so that resumed runs reconstruct it from authoritative state.
27. As a simulation maintainer, I want resumed execution to match uninterrupted execution, so that users can safely continue long runs.
28. As a simulation maintainer, I want the real source runtime to be the main correctness test boundary, so that tests cover observable behavior rather than private cache design.
29. As a simulation maintainer, I want comparison tools to reject deliberately altered business data, so that a passing comparison is meaningful.
30. As a balance designer, I want repeatable whole-week timings against the current version, so that reported gains describe my actual workflow.
31. As a balance designer, I want short-run performance checked as well, so that weekly improvements do not slow daily iteration.
32. As a repository owner, I want unrelated edits and historical evidence preserved, so that this optimization cannot overwrite concurrent work.
33. As an execution-toolkit owner, I want implementation and toolkit publication treated separately, so that local performance work does not silently change distributed versions.

## Implementation Decisions

- **范围与层次。** 优化 Fish 同源 Lua 宿主的完整查询编排及其需要协作的源查询服务；IGESS 继续负责编排、策略意图、观察和报告，Lua 继续负责合法性与业务规则。不在 Python 复制公式或建立替代模拟器。
- **实际实现为准。** 入口为 Query / Host 聚合查询，关联 ArchiveService、ArchiveSchema 和摸鱼厅、杠铃、神器、寻宝兽、重生、离线奖励、枪、库存、图鉴投影。历史记录曾包含相似优化，但不能据此假设当前源码已具备相同能力。实施前核对实际调用链与并发改动。
- **共享内容与所有权。** 优先复用一次从权威存档生成的独立快照，只供同一同步只读聚合查询内部使用；不向内部投影提供权威可变存档，不让返回值引用之后还会被修改的共享对象。
- **接入方式。** 优先使用已有快照投影入口和服务依赖边界。确需扩展时，只增加受限的内部查询协作能力，保留原公开查询签名及默认行为。不得全局替换 ArchiveService 或 Schema 的行为，不新增供外部请求任意跳过校验的参数。
- **校验复用条件。** 复用前证明快照未变化、规则身份一致、所有影响验证的选项和上下文一致；保留服务专属校验。遇到无法证明等价的调用则执行原校验，不强求每次完整查询只有一次验证。
- **失败语义。** 保持首次失败的位置、拒绝码、原有异常传播和缺失字段行为；不能为提前缓存而改变验证顺序，也不能用旧成功值掩盖错误。
- **生命周期。** 本阶段不引入跨查询缓存。临时复用状态随查询成功或失败清理，不跨写命令、结算、回调、会话或恢复边界；嵌套查询采用隔离状态或原路径。
- **动态状态。** 钱包、未领取产出、时间、revision、系统资格、进度、随机结果和待完成行为保持实时语义；每次新查询重新观察权威状态。
- **写路径。** 不修改事务校验、回滚、幂等、回执身份、随机链、推进调度或收益计算精度。不改变查询与写操作的先后顺序。
- **兼容性。** 完整 Query DTO、查询选项、公共分页语义、现有能力协商、命令历史和 checkpoint 格式不变；保持默认 QueryLuck 的精简路径及其安全回退。
- **性能实验。** 使用本阶段冻结的当前版本作优化前基线，保持两侧同一数值输入、策略、种子、运行时及采样口径。先独立测试本候选；不把探针时间、调用次数降低或历史更慢版本当作收益验收。
- **采纳条件。** 业务等价是硬条件；正式配对需显示一致方向、且足以区别于运行波动的端到端耗时降低。未约定最低百分比、翻倍目标或 60 秒目标；若收益未得到证明，记录并放弃该候选，不靠扩大范围或减少业务工作量制造成绩。
- **文档维护。** 实现改变入口、契约或测试导航时，更新受影响的 fish_sim 指引、代码导航和源模拟说明；只修改相关内容，保留其他 Agent 的工作。

## Testing Decisions

### 已确认的测试边界

用户已确认沿用以下边界。主要正确性边界是现有的真实源运行时完整查询接口，性能边界是正式模拟 CLI。只在 JSON 序列化无法暴露 Lua 引用别名、或非法存档无法从正式入口构造时，使用已有 Host / 源服务测试边界补充用例；不创建大量私有缓存单元测试。

好的测试检验调用方可观察的结果、错误、状态隔离及恢复行为，不断言某个私有键、函数拆分或恰好调用几次 GetSnapshot。调用统计可作为独立诊断，不作为业务测试契约；毫秒阈值不写入普通单元测试。

### 正确性与隔离

1. 在原观察时点，逐次比较优化前后完整逻辑 Query DTO 和查询选项，覆盖包含／不包含幸运值、空背包、满背包、后续页鱼实例、上下线及系统解锁状态。若运行时存在观察适配或变化传输，比较消费者实际收到的完整逻辑结果；不为测试引入新协议。
2. 深层修改返回结果中的钱包、库存、摸鱼厅、图鉴和其他嵌套内容，确认权威状态、下一次查询、先前查询结果及另一会话均不受影响。Lua Host 用例直接检查返回对象隔离，避免仅经 JSON 往返掩盖引用泄漏。
3. 在查询之间执行实际相关写操作和时间推进，验证变化立即可见；包括鱼升级／出售／上阵、奖励与购买、重生、孵化、计时效果变化及恢复。按实际触及服务选择覆盖，不扩展为无关玩法改造。
4. 对不同校验选项、规则身份、非法状态、多个同时无效字段以及中途投影失败，比较原路径的失败码、顺序和状态；失败之后继续查询不能复用残留成功结果。
5. 确认只读查询不增加写命令历史、不消耗奖励随机数、不改变 revision。检查显式 QueryLuck options 与异常规则仍保留原回退语义。
6. 分别在优化前和候选版本内做真实跨进程 checkpoint 恢复，与各自连续执行比较；再比较两侧业务状态与有序历史。保持跨代码身份恢复拒绝规则，不通过放宽校验来完成差分。

### 正式产物与计时

1. 实施前重新冻结源码、适配器、导表和项目配置，完成准备与摘要计算后才启动测速。保存命令、退出状态、运行 ID、清单、Lua/Python 版本、CPU 条件和原始时间。
2. 以正式 CLI 执行 smoke、Day1 和 Week1 所需验证；通过公开 runs 接口核对成功状态、覆盖区间、输入身份与产物完整性。就绪检查不能替代正式运行。
3. 比较 timeline、events、source_progression、source_behavior 核心业务字节，完整 Query DTO、最终 checkpoint 业务字段及有序操作／回执历史；按影响核对报告业务字段。只归一化明确列出的源码身份、路径、计时等非业务差异，不能排序事件或跳过整个业务对象。
4. 给比较器至少一个修改金额或 next_throw_id 的负例，确保检测到差异。
5. 正式计时关闭所有诊断探针和逐次 trace。至少三组同输入、同机器、同核心配置的无探针 Week1 串行配对，测量从正式入口开始至产物全部完成的墙钟时间，报告逐组值、中位数、范围和差值；出现明显顺序漂移时补充交错次序配对。
6. 测速期间避免与其他模拟并跑；发现竞争则记录并重测受影响配对，不自行终止其他 Agent 进程。补充 Day1 配对检查短场景是否回退。
7. 区分定向通过、未覆盖、环境跳过和基线已有失败；先在冻结基线确认既有失败，不能修改生产数值或旧期望来制造全绿。实际拟交付字节改变后，重新确认身份与相应验收。

### 既有测试先例

- IGESS `test_fish_source_observation` 展示真实运行时完整观察、返回结果修改与跨进程恢复的测试方式。按当前能力选取用例，不将历史增量协议用例存在视作当前实现已通过。
- 源 `simulation_inventory_projection_test` 展示 Host 级完整库存、后续页、返回对象修改、满背包孵化及出售后恢复场景。
- 源 `simulation_host_test`、`simulation_cli_test`、`player_archive_service_test` 与相关 Schema 测试提供现有服务和会话边界；源 `throw_luck_query_test` 保留已交付幸运值优化的错误与隔离契约。
- 上轮幸运值优化已有固定核心、串行整周配对与完整观察差分；最新热点诊断已有核心字节、checkpoint 历史、清单和负对照比较。复用方法与比较器时重新核对适用范围，不复用旧输入作为本轮基线。

## Out of Scope

- 本阶段不优化 JSON 编码、引入增量传输协议、增加跨查询的等级结果缓存，或重写力量幸运值映射；这些保留为后续分别验证的候选。
- 不修改数值表、SettingValue 目标、玩家策略、动作耗时、在线时长、采样频率、报告口径或种子来换取速度。
- 不重写 BigNumber、存档事务框架、调度器、随机算法或恢复机制，不迁移语言或 Lua 运行时。
- 不扩展退休的 Fish Python 模型，不追逐未确认的翻倍或整周 60 秒目标。
- 不自动发布 GameBalancer 或执行工具包、不提交或推送版本库、不关闭其他 Agent 的模拟进程。
- 本次规格发布不代表代码已实现、性能收益已验收，亦不代表 UE、DS、多人或真机验收。

## Further Notes

- 最新依据：[QueryLuck 优化后的 Week1 性能复测](../fish-post-luck-hotspots-20261101/verification.md)，包含输入摘要、两个运行 ID、原始计时、探针边界和一致性证据。
- 已交付前序：[幸运值按需查询验证](../fish-luck-query-20261101/verification.md)。其性能数字仅代表对应冻结输入，不作为本阶段直接分母。
- 工程约束：[数值模拟性能指南](../../docs/agents/simulation-performance.md)、[模拟接口目录](../../docs/agents/simulation-interfaces.md)、[Fish 项目说明](../../projects/fish_source/README.md)。历史“停止优化”的默认限制已由本次明确请求在上述范围内更新，不扩大为语言迁移或发布授权。
- 历史相似实现可作设计参考，但须检查当前源码的实际能力；不得整块覆盖旧优化代码或其他 Agent 的未提交变更。
- 项目领域词汇沿用“正式运行”“导表快照”“运行快照”“运行历史库”。本文的优化前版本仅用于开发性能对照，不改变调优工作台对数值分析“比较基线”的版本兼容规则。
- 分发及源码隔离 ADR 继续有效；本阶段只在开发仓库和本地诊断环境工作。

## Comments

- 2026-11-01：用户确认沿用完整查询差分、返回对象隔离、恢复验证和至少三组无探针 Week1 串行对照的验收边界。按 `to-spec` 发布，状态为 `ready-for-agent`。
