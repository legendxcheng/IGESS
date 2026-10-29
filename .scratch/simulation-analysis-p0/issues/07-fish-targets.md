# 07: Fish 成长目标与刺激分评估

**What to build:** 对 Fish 的日周成长、累计数量、节点和空档评估，并显式计算刺激分。 遵循父规格“IGESS P0：运行查询、领域指标与目标对照接口”。

**Blocked by:** 04, 05

**Status:** ready-for-agent

**Implementation:** completed

- [x] 完整/截断/续跑覆盖决定能否评估，未覆盖不当零
- [x] 按标签或按独立事件权重显式选择，精确计分
- [x] 提供演示目标并通过篡改目标和事件负例
- [x] 同步 fish_sim、代码导航及公共接口文档，报告完成范围


## Comments

- 2026-10-30：实施完成，验收范围与未解决的全套既有失败见 [验收记录](../verification.md)。
