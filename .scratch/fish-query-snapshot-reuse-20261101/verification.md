# 单次完整查询快照复用：最终验证

日期：2026-11-01。技术实施与本规格范围内的验证完成；用户确认本轮结束并授权 Git 提交，不继续追加性能优化。

## 结果

最终代码的三组无探针 Week1 串行配对均更快，业务结果全部一致。两侧耗时中位数 **214.847 → 207.341 秒，减少 3.49%**；每组减少比例的中位数为 3.16%，两种统计不混用。Day1 配对 **19.714 → 18.876 秒，减少 4.25%**。

完整逐次观察、核心业务产物、checkpoint 历史、真实跨进程恢复和专项隔离检查通过。IGESS 定向回归为 **14 通过、1 失败**；唯一失败已在冻结基线上重现，未修改旧期望或生产表制造全绿。

## 实际改动与边界

- `SnapshotScope` 由 Host 通过现有 ArchiveService 注入接入摸鱼厅、库存、杠铃、神器、寻宝兽、重生、离线奖励、枪与图鉴；在单次完整 Query 内复用一份独立存档快照。
- 按会话和 coroutine 隔离，嵌套查询独立，正常结束和异常退出均清理。动作报价、独立查询和写操作保持原服务路径；临时状态不进 checkpoint。
- 枪查询会删除 combat 投影中的私有 acquisitions，单独复制此分支，保护共享快照和私有恢复字段。
- 不同服务的 ID、规则和时间校验选项不同，因此全部原校验保留，没有合并不等价验证，也未全局替换 ArchiveService 或 Schema。
- 新增测试发现部分源构造器通过 rawget 检查 RunTransaction；最终适配器构造时即提供该原始方法字段，消除对服务构造顺序的隐含依赖。五类服务直接接入的拒绝差分用例通过。

交付为五个模拟 Lua 模块、一个专项测试及说明文档。未改变玩法服务、数值表、玩家策略、随机链、推进算法、Python 业务逻辑或协议；用户已授权提交至两个开发仓库；未推送或发布 GameBalancer。保留原工作区的 Query、README、源表等无关修改。

源实现已提交至 fish-oasis：`521e062020253b2e949016a618e2bb49b7f7761b`。该提交仅包含本轮性能改动；受测输入仍以冻结工作区摘要为准。

## 冻结输入和测量条件

- 基线源码：`b3f24e2937a9c70d9ea3e0bfe8ea7dd5a17bd1ac2bddd6db4568da9fdaebc41d`。
- 最终源码及实际工作区：`599f503ffbc9c225ebeff2afd029046fc7b2eb5d1aadc35f41a60a8945333438`。
- 两侧导表：`d8ef862c80d2b7654636370b823dce7430902555b2d03dadb7eb35d662dc2d53`。
- Windows、Python 3.11.9（既有 py311-venv）、Lua 5.5.0。实际准备完成后才开始测量，源码、导表、项目配置和 Python 源码均冻结。
- Week1 为 604800 秒，seed 20260626、默认策略、每天 7200 秒活跃、在线 300 秒采样、tick / equivalent_batch_v1。
- 正式 CLI `model simulate --json`，从启动至所有所需产物完成计墙钟；关闭诊断、cProfile 和逐次 trace。
- 固定性能核心 mask 65535，所有正式对照串行，无其他 Lua 进程重叠。仍有 Cocos 与浏览器背景 CPU 负载，不能保证每次运行都获得同一百分比。

输入身份见 [identity.json](identity.json)，最终工作区与冻结副本复核见 [final-live-verification.json](final-live-verification.json)。冻结目录为 IGESS 的 `.tmp/fish-query-snapshot-reuse-20261101/`。

## 最终版本无探针对照

| 配对 | 实际次序 | 基线秒 | 最终版秒 | 耗时减少 |
|---|---|---:|---:|---:|
| 1 | 基线→最终版 | 206.022 | 199.519 | 3.16% |
| 2 | 最终版→基线 | 216.025 | 207.341 | 4.02% |
| 3 | 基线→最终版 | 214.847 | 210.339 | 2.10% |

基线范围 206.022–216.025 秒，最终版范围 199.519–210.339 秒。三组均改善，幅度为 2.10%–4.02%；这是小幅收益，未追逐翻倍或 60 秒目标。

完整统计见 [delivered-summary.json](delivered-summary.json)，原始比较见 [delivered-comparisons.json](delivered-comparisons.json)，实际次序与进程检查见 [delivered-order.json](delivered-order.json)。[run_delivered.py](run_delivered.py) 执行本批测量；收据存在时拒绝覆盖。

第一版候选先完成四组对照，随后在新增测试中暴露依赖构造问题。修复后对最终字节重新执行上述三组和首日配对，旧候选数据不混入最终收益。历史记录、原始失败及统计保留于 [verification-v1.md](verification-v1.md)、[summary.json](summary.json) 和对应收据。

## 调用归因

正式测速结束后，另起独立 CLI 进程计数，每次仍原样执行源方法：

| 新会话完整查询 | 基线快照次数 | 最终版快照次数 | 两侧校验次数 |
|---|---:|---:|---:|
| 第一次 | 16 | 1 | 均为 11 |
| 第二次 | 9 | 1 | 均为 5 |

省去的是重复整档复制，校验仍执行。此例是空库存的新会话，不代表全部状态恰好调用相同次数，也不是业务测试阈值。诊断包装只在临时 CLI 中使用，未进入交付模块。见 [delivered-snapshot-counts.json](delivered-snapshot-counts.json) 和 [count_snapshots.lua](count_snapshots.lua)。

## 正确性证据

- 三组 Week1 和一组 Day1 的 timeline、events、source_progression、source_behavior 核心字节全部一致。
- checkpoint 解压后仅归一化 model_digest 和 session.codeDigest，其余业务字段与完整有序操作历史一致。manifest 仅归一化 model_digest、source_runtime.code_sha256、timings_seconds，其余输入与业务元数据一致。
- 修改 next_throw_id 的负对照被比较器正确拒绝，不排序事件、不忽略业务对象。
- 公开 runs show/artifacts JSON 检查最终计时批的八次正式运行均成功、身份完整、覆盖完整、登记产物全部存在，源码与导表摘要正确。结构化响应按运行 ID 保存在本目录。
- 原观察时点的完整 DTO 和查询选项逐次一致：Day1 **1397 次**、Week1 **11228 次**，最终完整状态一致。见 [Day1 差分](delivered-trace-day_1_growth-comparison.json)、[Week1 差分](delivered-trace-week_1_growth-comparison.json)。trace 耗时未计入性能统计；复用的是同一冻结基线的原始 trace。
- 真实跨进程恢复与同版本连续执行的完整状态和有序历史一致，跨版本业务状态与基线一致；没有放宽源码身份拒绝规则。见 [恢复结果](delivered-recovery-result.json)。
- 专项测试通过：200 鱼完整库存、调用方深层修改、前后帧和多会话隔离、查询选项、失败后继续操作、嵌套和 coroutine 隔离、异常对象保留，以及五类服务共 15 项非法存档拒绝／顺序差分。
- 库存、图鉴专项和幸运值 **221 项精确差分**通过；最终正式 smoke 成功。见 [源测试结果](delivered-source-test-results.json)、[smoke 收据](delivered-smoke-final-smoke.json)。

## 已有失败与范围限制

IGESS 定向回归运行 current_rules、joint、toolkit 三组既有套件，结果为 **14 passed, 1 failed**。失败是 joint 的 `test_free_codex_gun_recurring_tide_hatching_and_asset_reconciliation`：预期捕获 103:1、实际 101:1。对本轮冻结基线单独复跑后同样在第 205 行失败，不能归因于本优化。见 [最终回归日志](delivered-igess-regression.log)、[基线复现](baseline-joint-failure.log)。执行工具包测试仅在临时目录构建与验证，没有发布。

源 `simulation_host_test` 第 163 行、`simulation_guns_test` 第 80 行的失败，在冻结基线和最终版均重现；见 [最终版已知失败](delivered-known-failures.json) 及本目录的基线日志。未修改这些断言或生产数值。

没有运行整个仓库测试套件；UE、DS、多人和真机不在本任务验收范围。已同步源模拟 README、fish_sim 指引和代码导航、Fish 项目 README / RoadMap；规格父文件保持不变，实施票记录完成证据。用户已确认本轮结束并授权提交，性能优化停止于当前版本。
