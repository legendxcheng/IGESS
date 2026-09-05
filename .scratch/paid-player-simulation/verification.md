# 付费模拟首版验证

日期：2026-09-05。

## 已交付

- `payments.py`：独立商品和购买计划、严格字段校验、重复 YAML key 拒绝、精确花费、永久与限时倍率、输入归因。
- Generic tick/analytic 与 Fish 加权行为循环消费同一购买计划。Fish 在购买／到期边界结算旧产出，保留进行中的行为和 checkpoint 恢复语义。
- `WorkflowService.run_paid_experiment` 及 `igess paid-run`：一次准备输入，多方案正式运行，单画像和种子配对，标准历史／报告／失败状态。
- 中文离线对照报告、购买账本、资源曲线、Fish 期末状态、成长空窗、节点墙钟／在线时间差；未达成不按零计算，跳过低档鱼雷时按达到至少目标档位计算。
- 通用与 Fish 示例 YAML、`docs/paid-player-simulation.md` 和 README 入口。

## 自动验证

1. 首轮既有相关回归与付费测试：51 passed。
2. 默认全仓回归：1409 passed、2 failed、6 skipped、16 deselected，耗时 445.86 秒。两处失败都是 CLI 帮助测试的固定命令清单尚未包含 `paid-run`。
3. 已更新完整命令清单和新命令关键参数帮助覆盖。最终 `tests/test_payments.py tests/test_cli_help.py tests/test_cli_diagnostics.py`：70 passed，含 28 项付费专项测试。后续增加的测试覆盖离线生效、进行中训练倍率、生产报告/checkpoint 产物、报告失败、鱼雷跳档、金额精度、重复 YAML key、零购买等价。
4. `node --check src/igess/reporting/assets/paid-report.js` 通过。生成报告使用本地脚本和 ECharts；未依赖 CDN。
5. 修改文件的 `git diff --check` 通过。Fish 原有 RoadMap、投掷测试和其他工作区变更未覆盖。

完整回归中的两项失败在定向复核中已通过；没有把修复后的定向复核描述为再次完整运行全仓测试。默认标记排除的 16 项外部数据测试不计入通过数。

## 实际运行

通用示例：`.tmp/paid-generic-first/index.html`，三方案全部成功。

Fish 示例：`.tmp/paid-fish-example/index.html`，消费本机 Fish 生产快照，但商品明确标记为 example。`day_1_growth`、`week_1_growth`、`month_1_growth` × `free`、`starter_only`、`permanent_and_boost`，九次正式运行全部成功。输入摘要、逐方案运行 ID、完整购买计划、种子和报告路径保存在 `paid_comparison.json`。

报告字段与跳档比较修正后，已从这九次运行的原始 events 重建汇总，不重跑模拟。不能把这些商品价格或结果当成正式付费商品的平衡结论，也不能据单种子推断付费人群分布。

浏览器工具因本地 `file:` URL 策略拒绝预览，未通过其他浏览器或地址绕过。已完成脚本语法、报告结构、账本、节点和产物检查，但未完成浏览器视觉验收。
