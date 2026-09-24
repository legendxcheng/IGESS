# Fish 同源 Lua 数值执行器

Status: ready-for-agent

日期：2026-09-24。范围：Fish 源项目的模拟宿主，以及 IGESS 的后端接入与行为策略适配。本文依据已确认讨论形成；不依赖真实 DS、不要求具备引擎服务器源码。

## Problem Statement

数值策划希望模拟随游戏真实规则更新。当前 IGESS 读取生产导表快照，却以 Python 维护另一套 Fish 业务逻辑；Lua 中的规则变化需要再实现一次，新增系统不断扩大维护面，并可能产生无法从表哈希发现的行为偏差。

已发现的例子是鱼厅收入：游戏先进入槽位待领取余额，再经领取命令进入钱包，而 IGESS 直接增加可花费金钱。一键领取在游戏中还有特权条件。这些差异会影响购买时点，不能仅靠同步数值表解决。

用户没有完整 DS 引擎/平台服务器源码，也不希望为了数值模拟运行完整游戏服务器。目标是直接执行现有 Lua 业务，把主要新增维护工作转为具体操作及玩家行为策略，同时争取提高长周期模拟吞吐。

## Solution

在 Fish 源项目维护一个不依赖 DS 的同源 Lua 数值执行器：加载生产业务服务，通过虚拟时间、定时器、内存存档和最小玩家上下文承载其运行，对外提供操作、查询、时间推进、状态观察和恢复接口。

IGESS 启动该执行器，决定玩家何时上线、选择什么操作、何时继续决策，并消费权威回执和状态生成现有正式运行、调优报告与运行历史。业务校验、价格、扣款、奖励、成长和存档变更全部由原游戏服务执行。模拟宿主不复制生产 Lua，也不另写经济公式。

开发时可以加载源项目；每次正式运行冻结输入与代码身份。独立执行工具包将来消费由源项目构建的带版本运行包，不要求执行策划拥有游戏源码。正式分发实现不属于本次首版交付，但接口和输入边界必须兼容现有源码隔离、离线运行与导表快照要求。

“同源”指已覆盖业务执行同一份代码，不承诺完整引擎/网络真实性或真实玩家行为的百分之百预测。真实 DS 验证可以将来追加，不能作为本次开发、测试或验收的前置条件。

## User Stories

1. As a balance designer, I want simulations to execute the game's Lua rules, so that a rule change does not require a second Python implementation.
2. As a game developer, I want the simulation host to live with the game source, so that service changes and their adapters can be maintained together.
3. As an IGESS maintainer, I want a stable backend interface, so that IGESS does not depend on the game's private service construction details.
4. As a balance designer, I want to run simulations without a DS or editor, so that engine source and platform availability do not block my work.
5. As a balance designer, I want to retain player profiles and session schedules, so that I can compare different patterns of play.
6. As a balance designer, I want player policies to choose actions while Lua decides their results, so that predicted affordability cannot bypass actual rules.
7. As a balance designer, I want to query available actions and authoritative costs, so that decision policies do not duplicate economic formulas.
8. As a balance designer, I want fish income to accumulate and be collected as it does in the game, so that spendable money reflects actual collection actions.
9. As a balance designer, I want individual and privileged collection actions to obey game eligibility, so that free and privileged players are not treated as equivalent.
10. As a balance designer, I want fish deployment and rearrangement to use game commands, so that inventory and hall state remain valid.
11. As a balance designer, I want upgrades and sales to use production transactions, so that costs, restrictions and rewards follow the game.
12. As a balance designer, I want barbell purchase, equipment and exercise to use game services, so that strength growth includes actual timing and action restrictions.
13. As a balance designer, I want torpedo acquisition and selection to use game services, so that ownership and equipment rules are preserved.
14. As a balance designer, I want throws to follow the complete business lifecycle, so that preparation, landing, completion and expiry affect results correctly.
15. As a balance designer, I want material processing, breakthroughs and rebirths to execute source rules, so that progression systems remain synchronized.
16. As a balance designer, I want offline rewards to follow preparation and claiming rules, so that offline production is not prematurely spendable.
17. As a balance designer, I want virtual time to advance without real waiting, so that multi-day scenarios remain practical.
18. As a game developer, I want fractional exercise cycles and simultaneous events to have defined ordering, so that time acceleration does not change business results.
19. As a balance designer, I want repeatable random inputs and player decisions, so that repeated runs can explain changes.
20. As a balance designer, I want precise large-number values across the interface, so that high-level progression does not lose money or strength through floating-point conversion.
21. As a balance designer, I want interrupted runs to resume from supported checkpoints, so that commands and rewards are not repeated.
22. As an IGESS maintainer, I want separate runs to isolate state and caches, so that one player's experiment cannot contaminate another.
23. As a balance designer, I want simulations to use my selected read-only exported data, so that the report evaluates the tables I actually changed.
24. As a balance designer, I want code, data, runtime and policy fingerprints in each run, so that results can be traced to their exact inputs.
25. As a balance designer, I want unsupported actions and assumptions to be visible before a run, so that incomplete coverage is not mistaken for production behavior.
26. As a balance designer, I want standard timelines and growth reports from the new backend, so that I can continue the existing tuning workflow.
27. As a balance designer, I want generated, unclaimed and spendable income reported separately, so that I can understand liquidity bottlenecks.
28. As a balance designer, I want backend failures to produce diagnosable failed runs, so that partial execution is not reported as a successful simulation.
29. As a balance designer, I want old reports to remain readable, so that historical evidence is preserved during migration.
30. As a balance designer, I want fresh baselines when changing backends, so that rule corrections are not misattributed to table changes.
31. As an IGESS maintainer, I want representative performance measurements, so that throughput improvements are demonstrated rather than assumed from language choice.
32. As an execution planner, I want future packaged runs to remain local and offline, so that the new architecture does not require access to game source or remote services.
33. As a game developer, I want new operations to extend the host's capabilities without duplicating their rules, so that simulation maintenance grows mainly with player interaction coverage.
34. As a balance designer, I want hypothetical reward profiles labeled separately from real game privileges, so that experiments do not imply nonexistent production behavior.

## Implementation Decisions

1. **归属边界。** Fish 源项目拥有专用宿主、服务装配、操作映射、虚拟时间、定时器、存档适配和最小平台上下文；IGESS 拥有通用进程调用、玩家策略、实验调度、运行登记、结果转换和报告。不得将游戏内部初始化细节、存档字段补丁或经济计算迁回 IGESS。

2. **直接复用生产服务。** 优先调用已有 Application 层及其事务、会话和幂等语义，并自然复用 Domain 层。不得只调用公式函数后由模拟器自行发奖。必要的依赖接缝在原服务中正规化，游戏环境和模拟环境使用同一业务实现，不依赖永久堆积测试专用 hook。

3. **运行方式。** 首版以本机常驻 Lua 子进程作为默认宿主，每次正式运行创建隔离实例，通过有版本的请求/响应协议交互，日志与协议分流；不为每个动作重新启动解释器。优先采用标准输入输出上的 JSON Lines，预留批量请求。无需 HTTP、网络监听、DS、编辑器或游戏平台账号。

4. **解释器约束。** 固定经过项目行为验证的 Lua 实现、版本与启动配置；禁止隐式采用机器默认解释器版本。现有本机 Lua 5.5 测试证据只用于建立候选基准，不宣称已与真实 DS VM 相同。解释器选择和实际版本必须进入运行指纹；无需等待 DS 版本确认才能推进本次功能。

5. **一个主要业务边界。** 对外提供执行器会话接口，覆盖能力描述、创建会话、查询、执行命令、推进时间、读取事件、checkpoint/restore 和结束会话。协议包括版本、请求身份、操作名、状态 revision、成功/拒绝/故障结果、回执与事件游标。普通业务拒绝不能被混成进程故障；传输重试不得改变游戏命令的幂等语义。

6. **能力与动作清单。** 宿主公开支持操作、查询、状态格式、恢复边界与场景限制。操作映射直接委派给源服务；未知动作拒绝执行，未建模的引擎依赖不得默认返回成功。描述协议能力不等于再维护一套动作可用性规则；实际资格、报价和目标由原服务或同源规则查询提供。

7. **首版功能覆盖。** 分阶段覆盖现有普通鱼成长场景需要的初始化、上线/下线、投掷、鱼入库/摆放/取出/重排、鱼升级/出售、鱼厅扩容/逐槽领取、鱼雷购买/选择、杠铃合成/装备/开始与停止锻炼、材料分解、突破和两类重生、离线奖励准备与领取。源服务自然应用的规则不能因旧 Python 范围较窄而被关闭；未具备玩家策略的新系统须在场景覆盖说明中明确列出。

8. **操作流程。** 领取、摆鱼、装备、开始与停止锻炼都属于策略提交的显式意图，不由 Python 隐式改状态。投掷必须走准备、飞行/落点、完成及过期业务路径；依赖运动或位置的事实以显式场景输入提供，并经过原服务校验。首版不模拟真实世界碰撞或渲染。

9. **策略与业务时间分开。** IGESS 决定下一次玩家决策与意图提交时点，Lua 宿主拥有唯一权威虚拟时间轴并执行所有业务定时回调。玩家思考、操作和路径耗时属于明确记录的画像/场景假设；服务器命令即时完成与模拟玩家忙碌时长不可混为一谈。禁止把旧“每次只有一种前台行为”无条件写成新游戏权限规则。

10. **时间精度与顺序。** 使用足以表达毫秒周期的虚拟时间表示，分别保持源服务整数秒和毫秒时钟的量化语义。记录 epoch 与单调经过时间的映射。推进必须处理区间内全部业务到期事件和取消语义，相同时刻先完成已排队的到期事件，再受理该时刻新玩家操作，内部同刻事件采用稳定顺序并通过边界测试约束。发现原服务明确要求不同顺序时，应调整宿主契约并记录，不能悄悄跳过事件。

11. **先准确，再加速。** 首先建立完整事件推进模式。仅在可观察状态、回执、事件及随机消耗等价得到验证后，才合并结算区间、批量调用或减少采样。不得以收益倍率模拟时间加速，不得跳过领取/突破/特权到期等影响决策的边界。

12. **随机与数值。** 游戏随机和玩家策略随机分离；游戏使用原项目 RNG 与受控 seed provider，记录可重放输入及必要游标。所有影响模拟的墙钟随机入口均需显式控制或拒绝该功能。金额、力量和高精度数据使用原 BigNumber DTO 或精确字符串传输，禁止经过 JSON 浮点金额重新编码；策略若需要成本或收益预测，使用同源查询。

13. **状态所有权。** 业务状态由 Lua 唯一写入。IGESS 接收查询与观察投影用于决策和展示，不能维护一份可独立结算的镜像玩家状态。初始存档由源 schema 创建/校验；旧 Python checkpoint 不自动冒充新格式或静默迁移。

14. **恢复与隔离。** checkpoint 包含业务存档、虚拟时间、pending 操作、定时任务语义、业务 RNG、幂等回执/事件游标，以及 IGESS 策略进度和 RNG。不能序列化的运行态须通过正式导出/重建接口处理。允许先声明只能在静止边界恢复，但不能将活动中 checkpoint 标记为支持；首版完整验收须覆盖其声明支持的动作边界和至少一个活动中长操作恢复。不同运行不得共享可变表、全局服务缓存或测试 fixture。

15. **导表快照与运行快照。** 正式输入继续是用户选择的只读导表快照，启动时冻结场景依赖形成运行快照。宿主通过生成加载器或生成绑定得到游戏表结构，不手写第二份业务字段解析规则，也不能静默改读源工程另一批 Lua 表。开发验证允许使用同批导出的 Lua 表，但须标记验证输入类型，不算完成正式 JSON 输入接入。运行中磁盘变化仅影响下次任务，依赖范围校验保持现有语义。

16. **代码身份。** 每次运行使用冻结或经校验不变的业务模块集合，记录代码内容摘要、构建/提交身份、协议、Lua VM、导表及生成加载器摘要、策略、初始状态、随机与假设。不得只记录 Git HEAD 而忽略实际工作区内容。运行中源代码变化不得影响已启动任务。

17. **IGESS 接入。** 新增同源 Lua 引擎适配器，沿用现有 DomainEngineAdapter、正式运行执行器、RunRegistry、标准产物与报告；从现有 Fish 行为模拟器拆出决策和执行职责，不改写通用模拟引擎。启动失败、协议错误、依赖缺失、宿主退出和报告失败均通过现有失败登记链保留证据，不回退到 Python 继续计算。

18. **观察与报告。** 事件来源必须是原服务实际提交的回执/状态变化，不能由 Python 重新算出“预期收益”。展示累计已产出、待领取和钱包可花费金额，保持材料/资源名称与上下文映射明确；IGESS 的材料余额对应游戏界面的资源，游戏材料物品是分解输入。保留 Strength、FishLuck、TrashLuck、成长节点、重生与永久进展指标；不支持的指标明确缺失，不能填零装作已观察。

19. **画像兼容。** 保留现有画像、在线安排及策略配置的可迁移部分。真实特权/buff 通过游戏服务提供的受控测试装配入口设置，不由 IGESS 直接倍增权威余额。无法对应真实游戏权益的收益倍率画像，只能作为显式假设实验，首版可以拒绝不支持的画像；不得悄悄忽略倍率或声称与真实付费一致。

20. **迁移与基线。** 先完成同源闭环，再完成正式场景，最后切换默认后端。旧 Python 引擎暂留作显式选择的历史诊断对照；已迁移业务停止扩充其镜像实现。旧报告继续可读，不自动删除历史。不同后端、规则包或工具包版本不得作为单因素数值改动的比较基线；新后端建立新的正式基线。

21. **性能目标。** 提升模拟吞吐是目标，不是语言选择带来的既成事实。分别测业务执行、IPC、事件整理、报表和总耗时，以及峰值内存、事件数、吞吐与冷启动。冻结同一输入后用既有 Python 后端提供参考数据，但已知业务语义不同的结果不能宣称严格同工作量。优化收益以新 Lua 后端准确模式与优化模式的等价工作量对比为主要依据；不通过降低规则覆盖或悄悄减少观察内容来宣称加速。

22. **交付约束。** 开发可加载源工程，未来执行工具包使用源项目构建的带版本运行包。维持本地离线、源码隔离、输入只读和输出进入运行历史库；不向执行策划直接分发可读游戏 Lua，不新增远程服务依赖。本次产物不标记为发布候选，也不修改分发仓库。生成运行包的最终打包技术与分发白名单扩展留给后续发布工作。

## Testing Decisions

主要测试接缝为**执行器会话接口**：以操作序列、时间、初始存档和随机输入驱动，断言外部回执、拒绝码、权威状态、事件和恢复结果。跨进程协议实现与同源规则尽量在这一条边界共同验证，避免为每个内部模块新增模拟器专用测试入口。IGESS 仅补现有正式运行工作流边界的集成验收。

测试边界已由用户明确确认：源项目执行器的统一会话接口，加上 IGESS 现有正式运行入口；不依赖 DS，也不为每个内部模块新增测试接口。

1. **复用既有证据。** 以现有杠铃养成服务、鱼厅服务和生产运行时测试中的内存存档、时钟注入和真实命令调用为先例。投掷、离线与概率解析测试目前有断言失败，先记录并确定原因，再建立基准；不能单纯修改期望值来让测试通过。已有领域算法测试继续归源项目维护。
2. **最小闭环。** 从源 schema 新档开始，通过显式测试初态/种子获得可用鱼，执行摆鱼、推进时间、查询槽位余额、逐槽领取、合成装备杠铃、开始停止锻炼。断言领取前不能使用待领取金钱，逐槽领取只入账一次，一键领取无特权被拒绝，来源状态与回执一致。
3. **完整成长操作。** 对首版清单覆盖成功、无目标、余额不足、拥有关系无效、满级、会话互斥和重复请求；检验鱼升级/出售、扩容、鱼雷、加工、突破和两类重生的可观察结果。测试使用源服务，不为适配层复写价格期望生成器。
4. **投掷生命周期。** 覆盖准备、锁定状态、飞行/落点输入、提前完成、重复完成、过期、退出与奖励只提交一次。源游戏校验拒绝不合法输入；仅跑随机解析器不算覆盖。
5. **在线/离线。** 覆盖上线初始化、离线准备/领取、重复领取、未领取再次进入以及锻炼停止；确认在线与离线收益进入正确容器，时间跳跃不能绕过业务流程。
6. **时间与随机。** 测完整/不完整的半秒周期、毫秒停止边界、同刻到期/命令、取消定时器、跨突破或倍率到期边界。相同条件重复运行得到相同规范化业务轨迹；策略随机不会扰动游戏随机流。分段推进与连续推进结果应一致。
7. **恢复。** 比较连续执行和 checkpoint 恢复的后续回执、状态、事件及 RNG；至少覆盖活动中的锻炼或投掷。重复奖励和事件游标漂移都算失败。不同代码/表/协议/策略指纹或不受支持的旧格式应明确拒绝恢复。
8. **隔离与数据。** 连续多轮与独立进程运行结果一致；一个进程的 fixture、缓存或失败不能影响另一个。大数往返保持精确；只修改非依赖表不阻塞，缺失必需字段产生定位清楚的业务诊断。启动后的文件变更不改变当前运行，下一轮可读取新快照。
9. **故障与协议。** 覆盖版本不支持、未知操作、无效请求、宿主崩溃、日志输出、重复请求和批次中业务拒绝；超时仅代表结果可能未知，重试使用原请求身份，不能自动生成新消费命令。正式运行失败保留已有产物。
10. **正式场景。** 通过既有工作流跑 smoke、1 天、7 天和 30 天场景，生成完整报告、manifest、checkpoint、核心成长及行为进展产物；每次所选画像必须受支持。报告缺失算正式运行失败，不能用纯内存结果代替。长场景允许使用明确记录的事件压缩策略，但不得遗漏业务结果和关键成长事件。
11. **差异分析。** 旧 Python 对照只用来定位规则差异，不能当作源 Lua 的正确性裁判。已知领取规则变化应在新基线中可解释；不以曲线接近作为同源实现验收标准。
12. **性能。** 在相同机器、固定输入和可比输出设置下记录各阶段性能，重复测量并报告中位数及波动。准确模式与优化模式必须先通过轨迹/恢复等价，再比较吞吐。完成 1/7/30 天正式场景并报告相对旧流程的成本；本规格不承诺未经测量的提速倍数，未提速须明确报告原因和瓶颈。

本次验收不要求真实 DS、PIE、RPC 网络连通或引擎源码。用原服务已有测试、确定性重放、完整命令链和正式运行集成证明所声明范围的正确性；对引擎语义不作超出证据的保证。

## Out of Scope

- 构建、运行或复刻完整 DS、UE/Oasis 引擎、网络复制和渲染。
- 必须人工启动 PIE 或取得真实 DS 结果才能继续的验收流程。
- 世界碰撞、真实移动路径、客户端表现、网络延迟与多人竞态的完整模拟。
- 真实支付、线上账号、平台存储和线上玩家数据访问。
- 全部新增游戏系统的自动策略生成；首版清单外功能可后续扩展。
- 在 IGESS 中继续复制游戏经济规则，或为适配方便改变生产业务结果。
- 修改生产数值表、改变游戏玩法设计、修复所有已有游戏测试和文档问题。
- 自动迁移旧 Python checkpoint，或强求新旧引擎保持相同成长曲线。
- 一次性重写通用 IGESS、提前建设多语言平台、分布式批跑或远程服务器集群。
- 发布 GameBalancer、提交/推送分发仓库、最终运行包打包实现，以及绕过现有交付 ADR。
- 无条件的“100% 真实玩家体验”或“Lua 必然比 Python 快”的承诺。

## Further Notes

### 已确认的用户决策

- 无需 DS，直接执行游戏 Lua 业务服务。
- 游戏专用宿主放在源项目，与游戏一起维护；IGESS 保留启动、调用、策略和报告。
- 业务实现只维护一份，新增模拟工作主要集中在操作类型与玩家策略。
- 性能提升是期望收益，按实测验证。
- 测试在统一会话接口与现有正式运行入口进行，不新增分散的内部测试接口。

### 建议实施顺序

1. 建立宿主与会话接口，完成鱼厅领取—杠铃锻炼闭环及可重放时间。
2. 完成投掷与离线链，梳理必要引擎输入、RNG 和活动中恢复。
3. 接入正式导表快照、IGESS 后端、首版动作策略和现有报告。
4. 验证 1/7/30 天、性能和失败保真，解释差异并建立新基线后切换默认后端。

真实 DS 差分测试在前期研究中是可选的强化证据。用户后续明确无法运行完整 DS，本规格已将其移出所有必需路径；不要从旧研究建议重新引入 DS 门槛。

### 参考与约束

- [研究报告](../../projects/fish/reports/source-runtime-refactor-research.md)：当前架构、源码差异和已有测试结果。
- [外部运行时研究](../fish-source-runtime-research/external-runtime-notes.md)：Lua 承载能力与引擎真实性边界。
- [IGESS 领域术语](../../CONTEXT.md)、[Fish 现有进度](../../projects/fish/RoadMap.md)。
- [ADR-0001](../../docs/adr/0001-distribute-execution-toolkit-from-separate-repository.md)、[ADR-0002](../../docs/adr/0002-distribute-igess-without-python-source-files.md)：离线、源码隔离、执行工具包与发布边界。
- [源项目](E:/fish-oasis/proj)、[现有服务测试](E:/fish-oasis/tests)。

实施状态（2026-09-24）：源会话与 IGESS 可选后端已接入，同一最终指纹的 1 天、7 天和 30 天正式场景均已成功，产物、Web 报告和最终 checkpoint 齐全。默认后端迁移、周期性中途 checkpoint 和整体性能优化尚未完成，实际边界及证据见 [实施验证](verification.md) 与 [实施票据](issues/04-long-run-migration-and-performance.md)。
