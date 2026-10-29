# 01: 运行历史与产物查询

**What to build:** 通过 runs list/show/artifacts 定位项目运行、输入身份与产物。 遵循父规格“IGESS P0：运行查询、领域指标与目标对照接口”。

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

**Implementation:** completed

- [x] 筛选、稳定分页、新旧根同 ID 去重及 formal 默认筛选可用
- [x] 查询 failed/running 不改变状态；未知 ID、冲突身份和缺失产物有结构化反馈
- [x] 路径与链接边界有效；查询不执行模拟、导表或就绪探测
- [x] 服务及 CLI 冻结产物测试通过，说明命令与只读边界


## Comments

- 2026-10-30：实施完成，验收范围与未解决的全套既有失败见 [验收记录](../verification.md)。
