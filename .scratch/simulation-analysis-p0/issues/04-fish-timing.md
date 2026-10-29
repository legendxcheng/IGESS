# 04: Fish 在线空档与关键节点查询

**What to build:** 查询在线首尾等待、相邻间隔及关键节点观察时间。 遵循父规格“IGESS P0：运行查询、领域指标与目标对照接口”。

**Blocked by:** 03

**Status:** ready-for-agent

**Implementation:** completed

- [x] 区分墙钟与累计在线时间，本段与生命周期
- [x] 无事件及单事件边界正确，排除离线时长
- [x] 不从采样补造节点，截断和缺少起始基线不伪报完整
- [x] 服务与 CLI 测试验证手算时间结果


## Comments

- 2026-10-30：实施完成，验收范围与未解决的全套既有失败见 [验收记录](../verification.md)。
