# 神兽纯产出缓存验证

2026-11-04。用户在月报耗时诊断后授权缓存优化。仅调整纯数值复用与同次决策报价查询；生产表、公式、行动顺序、耗时、随机及结算保持原逻辑。

## 修改

- 源 `FishProductionPolicy.Multiplier`：每个规则行保存最后一次合法数量／基础倍率／同种额外倍率对应的精确倍率，返回独立大数。
- 源 `FishBeastRateCache`：每个规则行保存最后一个参照产出乘积；依赖参照及倍率的完整 `_sign/_coeff/_exp`，不保留输入对象。规则行用弱键，空间受存活规则行数约束；不随玩家数、历史或时间累积。
- 源 `FishEconomyRules.CalculateLevelRate`：原参数、实例和参照验证后查询缓存；参照选择、普通鱼等级／变异／部署、动态公共倍率与结算不缓存。
- IGESS `_ProfileRun._choose`：上阵查询已返回且未产生动作时，卖鱼复用该只读结果；跨决策不复用。
- 已更新源模拟说明、项目 README/RoadMap、fish_sim 及代码导航。源缓存提交为 `f3d9fc37`；IGESS 报价复用、文档和验证记录一同提交。未推送、未发布 GameBalancer。

## 身份和测量条件

[基线身份](baseline.json)为原月报使用的 `da1cf3657e70aeacb4bd5e57eb122d6896b31911b0db43498a6e8e740d766e5f`；[候选身份](candidate.json)为 `7462e4207f0acdeac37caeb4ea39cb4ecd3ae7626038d953c9228b3e31fa34a2`。导表均为 `0043d3122cf66e373380597cdd607ab30a2c0b1582b4fc92fadbf0a14d2e632b`。

本轮测试基于当时包含既有大 R 等未提交功能的工作区；分仓提交只包含缓存优化差异，其他未提交功能继续保留，提交 HEAD 不等同于本地冻结工作区的全部内容。

源码、Python 适配器、配置与导表分别冻结在 `.tmp/fish-whale-rate-cache-20261104/`。正式比较使用同一 `smoke_whale` 场景副本，将该副本时长设为两小时；真实源导表及所有策略不改。调用既有 `AuthoringService.simulate` 正式入口，包含输入冻结、模拟、产物、报告和登记。未启动新的整月模拟。

正式测量关闭逐次诊断记录，基线／候选串行；顺序 B/C、C/B、B/C，固定逻辑 CPU 2（affinity mask=4，子 Lua 进程继承）。Python、系统、顺序及原始回执见 [order.json](order.json)。

| 组 | 基线秒 | 候选秒 |
| --- | ---: | ---: |
| 1 | 27.7913 | 24.7083 |
| 2 | 28.5912 | 24.8413 |
| 3 | 28.4549 | 24.8558 |
| 中位数 | 28.4549 | 24.8413 |

耗时减少 **12.6993%**。普通短场景单对为 5.9584 → 5.9728 秒，约 0.014 秒差异；不支持据此判断性能回退或提升。完整数据及各对等价结果见 [paired-summary.json](paired-summary.json)。

## 等价和正确性

- 单独带逐次观察记录的两小时差分：1,540 次完整查询 DTO 的哈希与查询选项／时点逐项一致；timeline、events、成长、行为 JSON 逐字节一致，最终 Query 相同，checkpoint 行为和源有序历史相同。
- 三组正式配对及普通短场景均通过上述核心产物、最终 Query 与 checkpoint 比较；另验 analysis JSON/Markdown、timeline/events CSV、payback CSV 字节相同。只归一化模型／源码／适配器身份与项目输入路径，不排序事件或回执。
- 独立复制的最终钱包被篡改时，比较器拒绝。见 [differential.json](differential.json)。诊断耗时不作为正式成绩。
- Python 定向回归 **38 passed、0 skipped**，包含大 R、卖鱼、正式运行、鱼潮弹药、连续／截断／真实跨进程恢复、导表变化拒绝。命令和结果见 [python-tests.json](python-tests.json)。
- 源专项 `fish_beast_rate_cache_test.lua` 通过：冷／热结果污染，256 位及极限指数大数、完整参照低位与指数变化、数量／配置变更、非法输入、跨规则隔离，以及等级／变异／部署变化。
- 源 production calculator、精确数学、SnapshotScope、鱼潮、幸运值专项通过。选取的 8 项源测试中 6 项通过；`divine_beast_production_test.lua:53` 和 `rebirth_production_integration_test.lua:145` 在冻结基线同样失败，未修改既有断言。见 [source-tests.json](source-tests.json) 与 [baseline-test-failures.json](baseline-test-failures.json)。不是源全套通过声明。

## 月末鱼群诊断与限制

[late-microbench.json](late-microbench.json) 使用既有报表重建的月末鱼 ID／等级／部署（孵化鱼重量使用替代值），其余系统采用新建存档默认值；同一 CPU、每版三次内部测量，无正式月模拟。大 R 生产快照中位 CPU 成本为 3.76 → 1.63 毫秒，约减少 56.6%；完整查询 5.475 → 3.600 毫秒；单秒推进 26.30 → 25.10 毫秒。不能将纯计算收益直接当作整体推进或整月收益。

整月端到端耗时尚未重测；上述正式收益只对本轮冻结的两小时场景成立。源码身份已变，旧 checkpoint 仍受兼容校验，不放宽跨版本恢复。没有 UE／DS／真机或执行工具包发布验收。

[scope-audit.json](scope-audit.json) 核对原已存在源文件只修改两处规则和模拟 README；新文件为缓存及专项测试。生产导表摘要未变，原工作区其他改动保留。
