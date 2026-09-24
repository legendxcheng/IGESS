# Fish 复用源 Lua 运行时：外部能力与边界研究

日期：2026-09-24。范围：一手资料、源码只读和 Oasis Cloud 只读诊断；未启动 PIE、DS 或修改游戏。此文件为并行研究稿，供主报告合并。

## 判断

**值得把 Fish 的业务执行逐步迁移到源 Lua 模块，但暂不应把“完整 Oasis DS 可独立、加速、自动运行”作为已确认前提。** 目前证据最充分的路径是：IGESS 负责策略、批量实验和报告；独立 Lua 宿主直接加载 Fish 的生产模块；在时钟、随机、存档和引擎边界注入适配；少量真实 DS 场景作为一致性验收。该判断为下面事实的工程推论，不是平台已经提供的现成功能。

这实现的是“业务源码同源”；只有真实 Oasis 宿主、服务器入口、引擎对象、网络、存储等也参与，才能称为“完整真实服务器运行”。即使如此，结果仍限定于输入版本、随机条件、操作序列、时间推进和场景覆盖，不能把“100%真实”作为无条件承诺。[S1][S2][S5][L1][L2]

## 已确认事实

| 事实 | 证据 | 含义与边界 |
|---|---|---|
| Lua 官方支持独立解释器，也支持宿主调用 Lua、读取变量和注册宿主函数。 | [S1] | 直接执行生产 Lua 在语言层成立；不会自动带入 UE/Oasis 原生 API。 |
| Lupa 是 Python 嵌入 Lua/LuaJIT 的项目，提供独立 LuaRuntime；当前项目文档提供显式选择 Lua 版本的方式，并支持多个运行时的线程使用。 | [S2] | IGESS 可通过进程内调用接 Lua，接口不必是 HTTP；需要锁定实现与版本，不能依赖默认选择最新版本。也可选独立 Lua 进程和批量 IPC，以简化全局状态隔离。 |
| Epic 的通用 UE dedicated server 无本地玩家且不渲染画面；该官方教程要求引擎源码构建和支持多人客户端/服务器的 C++ 项目。 | [S3] | UE 有该能力；这不是 Oasis 编辑器允许用户构建、分发、无账号运行 DS 的证据。 |
| UE 命令行参考把 `-Deterministic` 定义为 `-UseFixedTimeStep -FixedSeed`；`FixedSeed` 指向 `FRandomStream`。 | [S4] | 固定时间步和固定引擎随机源不等于控制 Lua `math.random`、`os.time`、服务端存档或异步返回顺序；也不能自动证明运行吞吐。 |
| Oasis Cloud 对本工程的只读检查识别到 `proj/Script`、数据表目录、编辑器缓存工具，并将其归为 generic-peaceugc 高置信。 | [C1] | 确认是 Peace UGC Lua 工程；未暴露或证实独立 DS 构建/批跑能力。 |
| Cloud 运行时指导明确区分本地 Lua 与 UE userdata/代理、引擎桥接、RPC/Tick 回调和模块缓存。 | [C2] | 本地 Lua 测试是业务证据，不能替代 DS 引擎集成证据。 |
| 源项目已有直接 `require` 生产 Application/Domain 的纯 Lua 测试；barbell 测试具有内存归档和 `now` 注入。 | [L1] | 无需从零切开整个游戏，已有很好的接入切口；测试专用 fixture/ResetForTests 不应未经梳理直接成为正式宿主协议。 |
| 源项目 RandomService 支持 `ctx.rng`，默认则 `math.randomseed(os.time())`；ServerThrowSeedProvider 默认混用 `os.time/os.clock`，同时有测试依赖注入。 | [L2][L3] | 重放必须控制随机与种子入口。只给 IGESS 设置 Python seed，或给 UE 设置 FixedSeed，都不足以控制这些源 Lua 路径。 |
| 源 TorpedoFlightSimulator 是 Lua 模块，提供固定步积分和 `Advance(state, deltaTimeSeconds, maxSubsteps)`。 | [L4] | 至少该数值子系统可以源码复用和受控推进；不可外推全部游戏循环已经可加速。 |

## Lua 版本与数值一致性

当前项目文档使用 `lua55` 执行本地测试，**这不证明发布 DS 使用 Lua 5.5**。本次只读源码检索没有取得 DS `_VERSION`、JIT 标识、构建配置或官方运行时版本。宿主选择必须把 DS 的 Lua/LuaJIT 实现、版本、数值类型配置作为验收项。[L5]

Lua 5.3 文档说明 `math.random` 接入底层 C 随机函数；Lua 5.4 文档说明其使用 xoshiro256**。因此“相同 seed”不能跨版本被当作同一序列的保证。建议在可注入路径用同一项目 RNG 算法、记录随机输入或完整随机流，并独立检验边界取整、大数 DTO 和表遍历顺序。该建议是基于版本差异和现有注入接口的推论。[S1][S5][L2][L3]

## 三条可行路径

| 路径 | 得到的真实性 | 成本/限制 | 建议 |
|---|---|---|---|
| IGESS → 独立 Lua 宿主 → Fish Application/Domain | 同一生产规则与状态变更；时钟、存储、玩家/引擎对象由适配器提供 | 仍须维护边界与操作脚本；不能验证所有引擎语义 | 优先做一条端到端原型，观察适配是否保持很薄。 |
| IGESS → 官方本地/测试 DS → 玩家命令入口 | 可覆盖权威校验、生命周期和真实引擎服务 | 自动启动、无头、时钟加速、账号/场景隔离和吞吐均待证；真实客户端可能仍有必要 | 先当集成验收后端；只有官方能力与性能得到验证，才考虑批量主后端。 |
| 同源 Lua 负责大批量 + DS 负责少量差分验收 | 兼顾吞吐与引擎回归证据 | 需同一命令契约、事件日志和状态快照比较 | 当前证据下最稳妥的长期结构。 |

接口需要承载合法操作与状态观察，例如初始化玩家、提交升级/投掷/出售/领奖命令、推进时间、等待异步完成、导出领域状态/事件。让 Lua 执行余额校验、扣款、奖励和提交；若 IGESS 先算完结果再写服务器状态，仍会保留原来的双份规则问题。这是架构建议，不是现有功能陈述。

## 必须保留为未知的问题

1. Oasis 是否向本项目提供可独立启动、可本地/CI 批量运行的正式 DS 宿主，以及对应版本、许可和分发边界。本次指导检索 `headless`、`命令行` 未命中相关能力；“未取得证据”不等于“不支持”。[C3]
2. 该宿主是否允许受支持的程序接口驱动玩家身份和命令，并观察存档、权威状态和异步结算；编辑器 MCP 可用不能直接推导游戏业务 RPC 可从 IGESS 调用。
3. 是否支持受控虚拟时钟、跳时和高倍速，同时保持计时器、生产结算、离线收益、每日重置和网络超时等语义；固定帧步长不是对此的证明。[S4][L2][L3]
4. 完整工程初始化涉及多少 UE/UGC 依赖，以及能否全部停留在薄适配器层；若适配器开始重写库存、经济、奖励等业务，应回到源工程抽离共同内核。
5. 真实 DS 与 Lua 宿主的单次启动、千操作吞吐、长时运行内存和并行上限。此次没有性能实验，不能提供确定工期或速度承诺。

本次 `oasis_status` 只读返回 Cloud/Worker/runtime 正常，但 `officialEditorMcp.available=false`、HTTP 503，因此未能取得当前官方编辑器会话中的 VM 或 DS 能力证据。另一次精确章节检索发生 Cloud HTTP transport 错误；此前成功的 search、preflight 与 project inspection 仍是本稿引用依据。没有为研究启动编辑器或要求用户改变环境。

## 对 IGESS 现有交付要求的影响

IGESS ADR 0001/0002 要求执行工具包源码隔离、独立分发、本地离线运行以及固定 localhost 工作台。直接将游戏 `.lua` 源文件随工具包交付，会引入新的源码披露问题；远程 DS 则会改变离线约束。开发环境可先用源目录原型，正式交付必须决定是否采用本地编译/字节码产物、隔离的内部执行服务或明确修订交付 ADR，不能默认绕过现有要求。[L6][L7]

## 建议原型验收（待实施）

选择完整经济链条：初始化 → 练力量/购入道具 → 投掷结算 → 入包/上阵 → 生产 → 升级/出售 → 退出重进。使用真实生产模块、表快照和固定随机输入。只适配时钟、存储、最小玩家上下文和不影响数值的展示出口；未识别引擎调用应失败，而不是默认返回成功。比较每条命令的返回码、余额、库存、等级、生产累计与最终归档；记录生产源码提交、表哈希、VM版本、操作和随机记录。先用真实 DS 校准这一条，再决定扩大范围。此处是研究结论形成的建议，尚未执行。

## 来源

- [S1] Lua 官方，[Lua 5.3 Reference Manual](https://www.lua.org/manual/5.3/manual.html)，Introduction、C API、math.random、math.randomseed。
- [S2] Lupa 作者仓库，[README](https://github.com/scoder/lupa)，Major features、Which Lua version、Threading。2026-09-24 查询；使用显式运行时版本，避免默认版本随依赖更新变化。
- [S3] Epic 官方，[Setting Up Dedicated Servers](https://dev.epicgames.com/documentation/unreal-engine/setting-up-dedicated-servers-in-unreal-engine)。当前页面为 UE 5.8；仅作为通用 UE 能力证据。
- [S4] Epic 官方，[Command-Line Arguments Reference](https://dev.epicgames.com/documentation/en-us/unreal-engine/unreal-engine-command-line-arguments-reference)，Deterministic、FixedSeed、UseFixedTimeStep。仅作为通用 UE 参数定义证据。
- [S5] Lua 官方，[Lua 5.4 math.random](https://www.lua.org/manual/5.4/manual.html#pdf-math.random)。
- [C1] 2026-09-24 `mcp__oasis_cloud__inspect_project({projectRoot:"E:\\fish-oasis"})`，只读 MCP 返回；不是公开文档 URL。
- [C2] 2026-09-24 `get_oasis_guidance` diagnostic preflight，catalog generation `gcat-93f07306be63bc15422bf9d76c4d6b49317f96e5a5b4609510ae0af5698a0d10`，逻辑章节 `oasis-best-practice:cloud-project-docs-docs-guide-lua-runtime-debugging-02-lua-vs-runtime-worlds-md`、`...05-cache-restart-and-testing-md`。Cloud 所有知识；属于受控工具返回的一手项目实践，**不是腾讯官方 DS 产品支持声明**。preflight 未指定官方操作，`guidanceRef:null`，未授权或执行编辑器操作。
- [C3] 同日 Cloud search，topics 为 `lua-runtime-debugging/editor-runtime-debugging/gameplay-lua-best-practice`，terms 包括服务器、DS、命令行、headless、独立；返回 `unmatchedTerms:["命令行","headless"]`，其余命中内容不构成独立 DS 能力说明。
- [L1] [barbell_progression_service_test.lua](/E:/fish-oasis/tests/barbell_progression_service_test.lua:87)，harness、归档/生产服务、时钟注入。纯 Lua 测试载入正式 Application 模块。
- [L2] [RandomService.lua](/E:/fish-oasis/proj/Script/Core/RandomService.lua:7)，EnsureSeed、RollInt、RollOpenClosed01。
- [L3] [ServerThrowSeedProvider.lua](/E:/fish-oasis/proj/Script/Core/ServerThrowSeedProvider.lua:24)，initializePrivateState、Next、依赖注入。
- [L4] [TorpedoFlightSimulator.lua](/E:/fish-oasis/proj/Script/Domain/Torpedo/TorpedoFlightSimulator.lua:180)，integrateFixedStep、Advance。
- [L5] [torpedo-flight-code-walkthrough.md](/E:/fish-oasis/docs/torpedo-flight-code-walkthrough.md:399)，本地回归命令使用 lua55；[AGENTS.md](/E:/fish-oasis/AGENTS.md) 要求只能由人启动或重启 PIE。
- [L6] [ADR 0001](/E:/IGESS/docs/adr/0001-distribute-execution-toolkit-from-separate-repository.md)。
- [L7] [ADR 0002](/E:/IGESS/docs/adr/0002-distribute-igess-without-python-source-files.md)。
