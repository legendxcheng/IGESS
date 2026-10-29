# P0 实施与验收记录

日期：2026-10-30。实施范围为本目录规格的 7 张票；主要验收边界仍是冻结运行产物上的 AnalysisService 与 CLI JSON 入口。

## 交付

- `runs list/show/artifacts`：项目历史筛选、稳定分页、运行身份与产物查询。
- `metrics describe/extract`：可扩展提供者协议、Generic 五类指标，以及 Fish 成长计数、分类、日周统计、在线空档、节点时间与显式刺激分。
- `targets evaluate`：版本化 JSON/YAML 目标、精确比较与容差、覆盖优先判定、可追溯 JSON/Markdown 导出。
- [公共接口文档](../../docs/analysis-api.md)、[演示目标](../../examples/analysis/fish-targets-demo.yaml)、fish_sim 使用说明及代码导航。

实现不修改模拟、Lua、生产表、采样或 checkpoint；默认不写文件，只有显式导出会创建新的分析目录。演示目标不是用户批准的数值平衡规划。

## 验证结果

Python：`.tmp/py311-venv/Scripts/python.exe`（3.11.9）。

| 范围 | 命令 | 结果 |
| --- | --- | --- |
| 最终公共服务及 CLI | `python -m pytest tests/test_analysis_api.py tests/test_cli_help.py -q --tb=short` | **68 passed**，28.50 秒 |
| 最终新增模块类型检查 | `python -m pyright src/igess/analysis_api` | **0 errors, 0 warnings** |
| 实施阶段报告兼容与池回归 | `python -m pytest tests/test_analysis_api.py tests/test_cli_help.py tests/test_source_fish_reporting.py tests/test_fish_collection_reporting.py tests/test_fish_pool_growth.py -q --tb=short` | **85 passed, 2 failed**，65.63 秒；两项失败见下文 |
| 全套默认回归（一次） | `python -m pytest -q --tb=short` | **1714 passed, 4 failed, 8 skipped, 16 deselected**；计时 25598.80 秒 |

全套回归在最后一轮快照身份修复之前启动；最后修改后重新运行公共服务/CLI 和类型检查，没有再次执行整套。全套不是全绿。上述较早测试批次与最终批次的用例数量不同，不能相加作为总覆盖量。本地原始日志位于 `.tmp/p0-baseline/{analysis-final,full-suite,targeted-final,typecheck}.log`，不纳入提交。

全套失败及边界：

1. `test_source_query_defines_pool_boundary[51-2]`：实际池 1，期望池 2。
2. `test_source_query_defines_pool_boundary[2001-3]`：实际池 2，期望池 3。两项测试硬编码旧边界 50/2000；当前外部 `E:/fish-oasis/igess_export/json/tbfishrandompool.json` 前两池上限为 200/3000。
3. `test_free_codex_gun_recurring_tide_hatching_and_asset_reconciliation`：实际捕获键 `101:1`，用例期望 `103:1`。这是既有 Fish 实模拟链测试中的失败，本次未修复或宣称该链通过。
4. `test_change_transport_resynchronizes_and_never_replays_commands`：Lua 返回 `simulation_operation_unknown`；当前外部 `simulation/cli.lua` 未注册 `query_changes`。本次没有新增或修改 Lua 操作。

上述四项均在既有 Fish 源码/外部数据集成路径，未经过新分析服务；本次保留这些文件和数据。没有为了得到绿色结果修改断言或外部配置。

## 票据对应证据

公共测试为 `tests/test_analysis_api.py`，通过服务或 CLI 断言可观察结果：

| 票据 | 主要证据 |
| --- | --- |
| 01 | 运行查询/身份冲突、失败运行、注册表优先级、筛选、链接拒绝 |
| 02 | Generic 目录、精确金额、缺失与零、未知命名实体、输入变动与同字节替换 |
| 03 | 双标签计数、边界日部分覆盖、续跑，以及与现有静态报告的计数对照 |
| 04 | 离线排除、手算首尾等待、无/单事件、节点时间、100 条以上事件的尾部证据 |
| 05 | 四种比较、容差、目标错误、超 80 位偏差、命令成功与目标失败区分 |
| 06 | 原输入不变、拒绝覆盖/权威目录、目录替换竞态、JSON/Markdown 导出 |
| 07 | 显式标签/事件权重、部分期间、截止早于续跑起点、演示目标执行 |

## 双轴审查

**Standards**：按仓库规则与已确认边界审查。发现导出路径替换竞态，以及畸形嵌套元数据/配置可能产生未封装异常；已修复并经独立审查复核关闭。Windows 实测通过；POSIX 的目录句柄路径只有静态复核，未声称实机通过。

**Spec**：发现续跑起点之前的节点截止误判、单枪节点被无关鱼池覆盖阻塞、非法事件类型错误、超过 100 条事件时尾等待证据遗漏；均已修复并经独立复核关闭。最后新增同字节替换回归，运行文件和目标文件均以字节及文件身份复核，2 项定向测试通过。两轴均无尚未关闭的本次阻塞项。

## 工作区与交付限制

- 测试在已有未提交改动的工作区完成；保留原有修改，不将它们混入本次提交。`run_registry.py` 的新增耗时字段和 `reporting/source_fish.py` 的鱼池投影扩展属于原有改动，新接口复用当前工作区能力。旧注册表缺少耗时字段时返回空值；旧投影没有池覆盖时标为不完整，不补造事实。
- 因此，完整的鱼池指标验收包含当前工作区已有投影扩展；不能把本次独立提交当作这些既有扩展已经提交或发布的证据。
- `docs/code_walkthrough.md` 原先为未跟踪文档，保持原内容。新增公共文档提供模块导航，已更新操作指南和 fish_sim 的接口入口。
- 未发布 GameBalancer，未 push，也未开展数值调参、生产改表或新长程平衡模拟。
