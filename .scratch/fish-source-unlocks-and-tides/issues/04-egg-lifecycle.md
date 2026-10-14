# 04: 可重放的鱼蛋入包与孵化闭环

**What to build:** 通过受控同源会话取得随机蛋，按源时间和容量孵化成鱼，进入既有图鉴与鱼厅经济；连续和恢复运行结果一致。

**Blocked by:** None (can start immediately)

Status: resolved

本票执行《Fish 同源模拟：图鉴奖励、寻宝兽开放与鱼潮》规格；范围与边界以父规格为准。实现前在独立工作树确认基于当前集成分支，使用 tdd 技能；测试边界已获用户确认，无需再次询问。

- [x] 首先处理必要的窄随机依赖注入，保留生产默认语义；抽蛋与每颗入包蛋的孵化种子均确定性、隔离且可重放。
- [x] 复用源随机、蛋库存和孵化服务，当前区域输入为 1；重复蛋配置合法但实例独立。
- [x] 以实际入包时刻确定 hatchAt，未到期不产鱼；蛋位和鱼包容量遵守源规则，阻塞后腾位可继续且不重抽。
- [x] 宿主提供操作/查询/推进，IGESS 观察蛋库存、入包及孵化来源；测试受控授蛋不变成正式玩家免费行为。
- [x] 孵化鱼进入源图鉴及已有经济链；单鱼奖励自动领取的组合验证留最终集成，不人为依赖 01。
- [x] 处理中间 admission、保存和通知回执；不能假定 sourceId 跨会话永久防重；逐颗发放可恢复。
- [x] 通过会话及正式运行边界验证真实 source 输出、跨进程 replay、源数据只读；快速模式遇孵化边界正确或回退。
- [x] 能力、摘要及运行包依赖更新；提交前合并集成分支并留下测试证据。

## Comments


## Implementation evidence

- Public source session: deterministic RollEgg area 1, injected per-instance RootSeed, stable request replay and real Grant/Settle; pending admission is returned as structured receipt. Production default still uses math.random.
- Source `simulation_eggs_test` validates exact deadline, duplicate operation, independent sessions and batch equivalence, hatch→hall income, 200-fish blocking and release, 200-egg capacity, offline login settlement, failed save/notice admission and hatch notice retry. Existing egg inventory, grant-capacity, hatch-service and simulation gun regressions pass.
- IGESS public runtime verifies checkpoint after 3/5 grants across fresh processes, exact final state and distinct hatch seeds. Formal 72-second smoke fixture verifies source hatch event at second30, report delivery, no automatic free grants, checkpoint event dedup and unchanged production JSON hashes. Compiled source runtime produces identical egg/fish state.
- Integration observation: inventory query `limit=50` is page size, while `total` reflects up to source fish capacity200. Existing ordinary-fish scheduler treats page length as full; coordinator notified for final integration review. This ticket honors source capacity in hatch and tests inventory.total.

- After merging current integration (01/02/03), combined IGESS egg/codex/natural-landing/gun/package suite: **17 passed in 96.89s**. Source host/codex/natural/gun and new egg lifecycle scripts pass. Both worktree tips include their current integration branch; status intentionally stays claimed until merger resolves.

## Answer

已合并确定性随机蛋入包、按源时序孵化、容量阻塞重试和正式报告；跨进程恢复与已有图鉴／枪／落点流程组合验证通过。

- 源项目集成合并：8e05cff3ee814f0d8865d14c0353b84a38098391。
- IGESS 集成合并：69044c1bbe780c17e435da5bad8e32b77ec0fc35。
- 集成后验证：鱼蛋生命周期、图鉴、自然落点、枪及宿主 Lua 五套通过；IGESS 蛋／图鉴／枪／落点／源报告组合 20 项通过（99.96 秒）。
- 按工具包文档使用 bun build 重新生成生产 report.min.js；通用及源报告回归 23 项通过，含未压缩和生产资产测试。
- 源生产默认随机语义保留，未改生产导表或原有无关未提交内容，未启动 Editor / DS。
