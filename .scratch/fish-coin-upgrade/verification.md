# 金币升级实施验证

日期：2026-09-16。规格：[spec.md](spec.md)。
审查固定点：`10bd0587b7e35482a4a0f4b48d434189dc2e5291`，实施分支 `main`。

## 实施与自动化

- 首个切片先把升级命令测试改为金币成功/失败语义，观察旧材料实现失败，再改命令与结果对象使其通过。
- 策略通过现有行为适配入口验证：品质、实例、上阵交集、同品质投资保留、动态扩容、满级占位、不转投、严格等待边界及画像倍率。
- 正式 WorkflowService fixture 覆盖运行登记、报告、compact 金币账本与神兽排除。
- 复制/原地事务均验证升级中 checkpoint 恢复与连续运行的事件、状态等价。
- 含神兽 checkpoint 拒绝恢复并保留原始输入；神兽命令失败且不改状态。
- 全量默认测试：`1429 passed, 8 skipped, 16 deselected`（271.48 秒）。
- 全量后补充终局无杠铃门槛和神兽 checkpoint 边界，并验证杠铃跳过低速档与购买后目标推进；定向文件：`18 passed`。
- 外部生产生成对象对 JSON 的逐字段契约：`1 passed, 13 deselected`；移除了过时的固定行数与标量 Luck 端点断言，保留逐字段相等验证。
- 本次修改的九个核心 Python 文件 pyright：`0 errors, 0 warnings`。
- `node --check src/igess/reporting/assets/report.js` 与 `git diff --check` 通过。

## 正式生产运行

四阶段全部由既有 `igess model simulate --project projects/fish --scenario ... --json` 完成。
每个 manifest 登记的全部产物及报告存在，包含 checkpoint、Luck 和永久进展 JSON/CSV。
输入与精确 run 链接、金币消费及连带成长数据见
[正式基线](../../projects/fish/reports/coin-upgrade-baseline.md)。

晚补的无有效杠铃终局分支只移除不存在目标时的等待门槛；四次正式画像收益为正，
月末仍有更强杠铃可买，不改变本轮基线结果。

## 已知边界

`model status` 的十 tick 自动探针仍使用只支持通用模型的 Simulator，报 `smoke_failed`。
这是既有入口边界；Fish 正式模型运行、登记和报告均成功。本轮不扩展通用探针架构。
神兽、出售、同 RNG 反事实归因和执行工具包发布均不属于本轮实施范围。

## 审查

code-review 双轴审查完成：Standards 无硬性违规、1 项非阻塞模块边界建议；Spec 0 项发现。
完整独立审查报告与处理见 [review.md](review.md)。
