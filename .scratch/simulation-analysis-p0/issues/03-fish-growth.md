# 03: Fish 成长事件与日周统计

**What to build:** 通过指标入口取得 Fish 成长分类、去重总数和自然日/周计数。 遵循父规格“IGESS P0：运行查询、领域指标与目标对照接口”。

**Blocked by:** 02

**Status:** ready-for-agent

**Implementation:** completed

- [x] 复用现有领域投影，必要整理先于新增功能，旧报告语义不变
- [x] 双标签、同秒事件、首次鱼池与恢复历史正确
- [x] 分桶左闭右开，部分覆盖与缺失基线明确
- [x] 与现有报告对照验证，并同步指标使用说明


## Comments

- 2026-10-30：实施完成，验收范围与未解决的全套既有失败见 [验收记录](../verification.md)。
