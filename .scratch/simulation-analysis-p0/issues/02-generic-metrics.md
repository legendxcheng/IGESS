# 02: 指标目录与 Generic 指标提取

**What to build:** 通过 metrics describe/extract 查询公共指标及证据。 遵循父规格“IGESS P0：运行查询、领域指标与目标对照接口”。

**Blocked by:** 01

**Status:** ready-for-agent

**Implementation:** completed

- [x] 版本化指标目录可按引擎扩展，未知引擎不回退
- [x] 五类 Generic 指标及画像选择可用，金额精度不丢失
- [x] 读取一致快照；缺失、零、不适用和未达到分开
- [x] CLI 与服务测试覆盖错误参数及超过 80 位的值


## Comments

- 2026-10-30：实施完成，验收范围与未解决的全套既有失败见 [验收记录](../verification.md)。
