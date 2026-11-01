# 01: 建立本轮冻结基线与比较工具

**What to build:** 固定当前输入，建立可验证完整查询、核心产物和恢复状态的性能比较基线。

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [x] 冻结源码、适配器、导表和项目配置，准备完成后才开始测量。
- [x] 比较器覆盖完整逻辑观察、核心业务字节及有序 checkpoint 历史，并拒绝篡改业务字段的负例。
- [x] 记录原始身份、运行条件和基线已有失败，保护无关工作区改动。

## Parent

[Fish 完整查询的快照与校验复用](../spec.md)。

## Execution

2026-11-01：技术实施与本票范围验证完成，用户已确认本轮结束并授权提交，不继续追加性能优化。完整证据见[最终验证](../verification.md)。最终 Lua 摘要 `599f503ffbc9c225ebeff2afd029046fc7b2eb5d1aadc35f41a60a8945333438`。
