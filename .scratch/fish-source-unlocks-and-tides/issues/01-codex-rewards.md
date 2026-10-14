# 01: 单鱼图鉴奖励闭环

**What to build:** 玩家捕获普通鱼后可按鱼种与变异历史图鉴领取一次金币或材料，正式模拟会主动领取并在报告中独立展示收入。

**Blocked by:** None (can start immediately)

Status: claimed

本票执行《Fish 同源模拟：图鉴奖励、寻宝兽开放与鱼潮》规格；范围与边界以父规格为准。实现前在独立工作树确认基于当前集成分支，使用 tdd 技能；测试边界已获用户确认，无需再次询问。

- [x] 沿用源图鉴目录和领取服务，排除关闭条目和神兽；重复捕获、出售、重生均不重置历史或奖励身份。
- [x] 会话公开查询与命令接入 IGESS：默认按稳定奖励 ID 领取，每次 1 秒，解锁和领取时点分别记录。
- [x] 源 BigNumber 金币/材料奖励及历史补领正确；失败不标已领，同请求与新请求重试不重复入账。
- [x] 收入观察和正式报告区分图鉴一次性奖励、鱼厅转账和持续生产，系统开放统计不混入逐鱼领取。
- [x] 测试经已确认的会话接口和正式运行边界，包含跨进程 checkpoint、防重、非法依赖和大金额；先红后绿。
- [x] 能力声明、输入/代码摘要和运行包依赖随新增操作更新；生产导表只读。
- [x] 提交前合并集成分支，记录两个仓库的提交和测试证据；不改无关生产行为。

## Comments


### 实施与验证（ticket 01，待集成关闭）

- 配对工作树从两个仓库 `feature/fish-source-unlocks-and-tides` 建立，分支均为 `work/fish-ticket-01`。
- 源端新增 `query_codex` / `claim_fish_reward`；查询按源目录和公开领取资格过滤，奖励调用现有 CollectionService，保持 BigNumber 回执、历史身份与请求防重。默认 Query 同时附带 codex 投影；projection cache 只跟随历史解锁／领取事实失效。
- IGESS 在空闲决策点优先按稳定 rewardId 领取，耗时一秒；图鉴解锁观察与实际领取分别记录，观察不混入接受命令或系统里程碑。金币与材料奖励各自累计并持久化，正式报告累计图单列一次性奖励，加工材料排除卖鱼及图鉴材料。
- TDD 红阶段：Lua 宿主测试因缺 QueryCodex 失败；正式 90 秒场景因没有 claim_fish_reward 失败。实现后均通过。
- Lua 宿主新增测试通过；源 CLI 新增 3 项通过，覆盖历史补领无需先查询、大于浮点精度金额、材料奖励、跨进程 checkpoint、同请求回放与新请求防重、未解锁失败、关闭条目排除、出售／重生保留、非法奖励与缺依赖拒绝。
- 既有 simulation_host_test 与 codex_fish_reward_recovery_test 通过，后者包含预提交失败回滚及保存／通知故障后防重（预期注入错误日志保留）。
- IGESS 新增 2 项通过：正式运行与报告／checkpoint，一套源码与隔离 Lua 运行包真实会话的捕获、查询和领奖等价。
- IGESS 收入／source 报告／通用报告／打包依赖／工具包回归共 43 passed、2 skipped；跳过项是既有环境相关测试，本票新增隔离包测试实际通过。
- 保留测试边界：现有会话 CLI 和正式运行；未启动 Editor／DS，未改生产导表，未发布运行包。完整 1／7／30 天交付属于 ticket 07。

### 集成复验

- 已合并 ticket 03 的最新集成分支：IGESS `49026b7`，fish-oasis `55d1c2fe`；保留双方能力、观察与报告钩子。单鱼和枪奖励统一按数字稳定 ID 排队，领奖之后再装备。
- 枪正式回归增加两类有效历史 fixture：单鱼奖励已领（领枪后 1 秒装备）和真实待领混合队列（每条单鱼奖励延后装备 1 秒，ID 顺序及真实回执核对）。两类均通过，未隐藏领取队列耗时。
- 集成发现宿主输入摘要未涵盖 `tbgun.json`、`tbcodexgunreward.json`；新增 CLI checkpoint 用例先复现错误接受变更快照，再补齐依赖清单后通过。图鉴侧 `tbcodexprogressreward.json` 同样纳入实际依赖。
- 源 CLI 最终 6 passed（含重复捕获、两个新枪表变更恢复拒绝）；源 simulation_codex_test、simulation_guns_test、simulation_host_test 均通过。IGESS 新增图鉴正式/隔离包测试 2 passed，图鉴枪组合正式/恢复测试 3 passed。
- 源提交：`409001c4`（单鱼闭环）、`a667f27d`（合并 03）、`a4d29694`（恢复输入校验）；IGESS 功能提交 `9ba05da`，合并 `87f1abe`，本条证据与组合测试随后提交。最终关闭由集成合并者处理。
