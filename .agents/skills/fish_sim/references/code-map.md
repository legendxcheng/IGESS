# Fish 代码导航

以下路径相对 IGESS 根目录，`<source>` 来自 `projects/fish_source/economy.yaml` 中的 `engine.source_runtime.project_root`。按任务只读相关行指向的模块；符号若已迁移，用 `rg` 追踪调用方并修正本导航。

## IGESS 模拟侧

| 要改什么 | 先看哪里／检索词 | 对应验证 |
| --- | --- | --- |
| 长跑后台交接、完成通知、人类唤醒后恢复 | Skill 的 `scripts/run_background.py`、`references/background-runs.md`；只包装公共 CLI，回执不替代正式运行验证 | `python -m pytest .agents/skills/fish_sim/scripts/test_run_background.py -q`（模拟 CLI 响应，不运行 Fish） |
| 场景时长、在线窗口、权重、行动耗时、采样 | `projects/fish_source/economy.yaml`：`scenarios`（Day1～Day6 为从零开始的累计场景）、`session_patterns`、`behavior_weights`、`behavior_durations`；命令见项目 README | `tests/test_fish_source_formal.py` |
| 引擎准备、能力检查、身份与策略 | `src/igess/fish_source_engine.py`：`FishSourceEngineAdapter.prepare`、`_REQUIRED_OPERATIONS`、`_integration_code_digest` | `tests/test_fish_source_current_rules.py`、`tests/test_fish_source_formal.py` |
| 玩家选行为、动作互斥、时间推进、截断恢复 | 同文件 `_ProfileRun`：`_choose`、`_act`、`execute`、`_advance_to`、`_continue_throw`、`_continue_tide`、`checkpoint` | `tests/test_fish_source_natural_landing.py`、`tests/test_fish_source_tides.py`、`tests/test_fish_source_joint.py` |
| 超过三十条按一级 CPS 卖背包鱼 | `fish_source_engine.py`：`_FISH_KEEP_COUNT`、`_choose`、清单 `fish_sell_policy`；源 `simulation/Query.lua` 的 `fishSales` 提供 `levelOneCps` 与 `materialAdded`，沿用源 `sell_fish` 和 `SourceIncome` | `tests/test_fish_source_sales.py`、`tests/test_fish_source_income.py` |
| 鱼厅金币全部领取、每槽耗时、批次恢复 | 同文件 `_next_collection`、`pending_collect_slots`、`last_collect`；`_act` 提交后移除槽位，`pending_action` 保留剩余耗时；清单 `collect_policy` | `tests/test_fish_source_collection.py`、`tests/test_fish_source_income.py` |
| Lua 启动、JSON 请求、冻结输入、摘要、replay | `src/igess/fish_source_runtime.py`：`FishSourceRuntime`、`request`、`_freeze_source`、`checkpoint`、`restore` | `tests/test_fish_source_formal.py`、`tests/test_fish_source_joint.py` |
| 图鉴领取、枪选择与里程碑 | `fish_source_engine.py` 的 `_choose`、`_observe_codex`；`src/igess/fish_source_guns.py` 的 `choose_gun_action`、`GunMilestones` | `tests/test_fish_source_codex.py`、`tests/test_fish_source_guns.py` |
| 蛋和鱼潮观察、去重、报告行 | `src/igess/fish_source_eggs.py`、`src/igess/fish_source_tides.py`；实际调度仍在 `_ProfileRun` | `tests/test_fish_source_eggs.py`、`tests/test_fish_source_tides.py` |
| 养成优先、25% 单场限额及近期成长预留 | `src/igess/fish_source_growth_policy.py`：`growth_options`、`GrowthTideBudget`；engine 的 `execute`、`tide_admission_policy`；checkpoint `growth_tide_budget` 保存有界收入历史；契约见项目 README | `tests/test_fish_growth_priority.py`、`tests/test_fish_source_tides.py`、`tests/test_fish_source_continuation.py` |
| 在线收入核算、消费回补、领取转账、退款 | `src/igess/fish_source_income.py`：`SourceIncome.observe`；`src/igess/fish_source_numbers.py`：`source_decimal` | `tests/test_fish_source_income.py`、`tests/test_fish_source_joint.py` |
| 成长和行为 JSON 产物 | `src/igess/fish_source_reports.py`：`write_source_progression_artifacts`、`project_source_behavior` | `tests/test_source_fish_reporting.py` |
| Web 报告指标及曲线 | `src/igess/reporting/source_fish.py`：`build_source_projection`；页面继续追踪 `view_model.py`、`static.py`、`assets/report.js`、`assets/report.css` | `tests/test_source_fish_reporting.py`、`tests/test_reporting_view_model.py` |
| 收集成长、双标签去重、旧报告首次覆盖 | `src/igess/reporting/source_collection.py`：`CollectionGrowth`；`fish_source_engine.py` 的 `collection_growth` 起始基线、`fish_source_runtime.py` 的冻结名称；源 archive 与 `GunMilestones` 负责续跑历史 | `tests/test_fish_collection_reporting.py`、`tests/test_fish_collection_formal.py` |
| 正式运行、历史终态、报告失败 | `src/igess/authoring/service.py` → `formal_run.py` → `engines.py`；开发工作流 `workflows.py`，历史 `run_registry.py` | `tests/test_formal_run.py`、`tests/test_run_registry.py` |
| 按天接续到更长场景、选择历史起点 | `fish_source_engine.py` 的 checkpoint 兼容校验与 `execution_window`；`workflows.py` 的 `checkpoint_for_run`；`dashboard.py` → `dashboard_tasks.py` → `dashboard_task_worker.py` | `tests/test_fish_source_continuation.py` |
| Dashboard 每任务加载源码、进程失败与子进程回收 | `src/igess/dashboard_tasks.py`、`dashboard_task_worker.py`、`dashboard_process_tree.py`；契约见 `docs/dashboard-task-processes.md` | `tests/test_dashboard_task_processes.py` |
| 编译交付运行包、依赖表、运行包身份 | `src/igess/fish_source_package.py`；平台打包 `operator_export.py`、`operator_runtime.py` | `tests/test_fish_source_package.py`、`tests/test_fish_source_toolkit.py` |

新增参与策略或状态语义的适配模块时，检查 `_integration_code_digest` 是否纳入它；不要只加 import 却让运行身份漏掉行为变化。`fish_source_eggs.py` 等观察模块并不负责发奖结算。

检索示例（PowerShell 下用 `rg -g`，不把通配符当成单个文件路径）：

```powershell
rg -n 'def _choose|def execute|def checkpoint' src/igess/fish_source_engine.py
rg -n 'claim_fish_reward|start_tide|selected_export_sha256' src/igess tests -g '*source*.py'
```

## 原游戏与 Lua 宿主

| 层次 | 路径 | 职责与用法 |
| --- | --- | --- |
| 协议 | `<source>/simulation/cli.lua` | 逐行 JSON 操作分派、会话与 replay 入口；新增公开操作同时核对 Python 能力检查 |
| 宿主 | `<source>/simulation/Host.lua`、`VirtualTimer.lua` | 虚拟时间、存档／设备替身、源服务组装、推进和恢复；跟随 require 定位服务 |
| 查询 | `<source>/simulation/Query.lua` | 会话投影、背包分页聚合、报价缓存；查询保持只读，不推进玩法 |
| 专项桥接 | `<source>/simulation/Codex.lua`、`Guns.lua`、`Eggs.lua`、`Tides.lua` | 将图鉴、枪、蛋和鱼潮操作接入源服务，不在 IGESS 重写这些结算 |
| 导表加载 | `<source>/simulation/SnapshotTables.lua` | 所选 JSON 按源生成 schema 加载；与 `<source>/igess_export/json` 及 `data_root` 对照 |
| 业务服务 | `<source>/proj/Script/Application/` | 优先检索 `FishThrowService`、`FishHallService`、`BarbellProgressionService`、`TorpedoProgressionService`、`TrashManProgressionService`、`RebirthService`；沿服务追踪实际子模块 |
| 纯规则与大数 | `<source>/proj/Script/Domain/`、`<source>/proj/Script/Core/BigNumber.lua` | 价格／成长／随机／飞行规则与精确金额；改游戏公式时在此追踪定义 |
| 寻宝兽突破成本校验 | `<source>/proj/Script/Domain/Trash/TrashEconomyRules.lua` 的 `normalizeRealmRows` | 相邻成本可下降或持平，非满级正数、满级零；回归为 `<source>/tests/trash_realm_price_cadence_test.lua`，综合规则测试为 `trash_economy_rules_test.lua` |
| 源协议回归 | `<source>/tests/` 中 `simulation_*` | Lua 宿主、CLI、恢复与待完成副作用；按源仓库说明执行 |

先确认源码和导表实际存在。缺少外部源码时仍可分析 IGESS 调用边界，但不能把接口推断当成已核实的源规则，也不能声称完成源集成验证。

## 进一步查证

- 玩法背景：`<source>/gdd/01-核心玩法概述.md`；随机算法 `05-核心随机算法.md`；重生 `04-重生机制.md`；玩法表现 `06-核心玩法表现设计.md`。
- 已接入机制与验收边界：`projects/fish_source/README.md`、`RoadMap.md` 及它们链接的 `.scratch/` 规格／验证记录。记录中的时间和指标只属于对应输入版本。
- 平台术语与交付约束：根目录 `CONTEXT.md`；涉及交付时读 `docs/adr/0001-distribute-execution-toolkit-from-separate-repository.md`、`0002-distribute-igess-without-python-source-files.md`。
- 新规格／票据按 `docs/agents/issue-tracker.md` 与 `triage-labels.md` 放入 `.scratch/`，按 `docs/agents/domain.md` 使用领域术语。


## 查询性能与等价验收

当前源码先核对 `<source>/simulation/README.md`。下列 2026-10-28 历史优化指针不保证仍在所选源树中；2026-11-01 已重新落实幸运值直接查询及本次 Query 内的快照复用，未重接历史增量观察或其他跨查询缓存。

- 当前快照复用：`<source>/simulation/SnapshotScope.lua` → `Host.lua` 的 ArchiveService 注入 → `Query.lua` 的完整查询作用域；`Guns.lua` 使用独立 combat 分支，`Codex.lua` 复用只读档案视图。写操作和独立查询仍转发原服务，各业务校验保留。回归为源 `tests/simulation_snapshot_scope_test.lua`，差分与串行配对工具在 `.scratch/fish-query-snapshot-reuse-20261101/`。

- `<source>/simulation/Query.lua`：会话鱼厅稳定投影缓存、单次拥有快照与完整 schema 校验；动态余额仍用 `FishHallSlotBalanceDraft.BuildQueryEntries`，失败回到原公开查询保留拒绝码。
- `<source>/proj/Script/Application/`：鱼厅、背包、枪、杠铃、神器、力量重生、离线收益、寻宝兽进阶的内部 `ProjectSnapshot`。原公开查询仍自行读取/校验；`simulation/Guns.lua` 接受同次快照。
- `PlayerInventoryService.ProjectFullSnapshot` → `PlayerInventory/QueryContract.BuildFullQuery` → `Domain/Fishing/FishInventoryQuery.BuildAll`：一次生成完整库存，公开分页不变；与 `FishEconomyRules.CalculateProductionSnapshot` 的重复鱼复用仅限单次计算，返回大数独立。
- `Application/FishThrowService.QueryLuck` → `Domain/Fishing/ThrowOutcomeResolver.QueryLuck`，与 `Resolve` 共用 `prepareLuck`。默认安全目录直接映射四个查询字段；显式 options、异常目录或数值边界回到完整 Resolve 保留错误。源专项回归为 `tests/throw_luck_query_test.lua`；本轮逐次观察差分、核心产物与串行配对证据在 `.scratch/fish-luck-query-20261101/`。
- `<source>/proj/Script/Core/BigNumber.lua`：精确分块整数算法；`simulation/Json.lua`：有界字段名缓存与等价 DTO 编码。精度、随机、排序和线协议均保持原契约。
- 源回归见 `simulation/README.md`；正式冻结/差分/串行配对工具见 `.scratch/fish-source-query-performance/` 的 `benchmark.py`、`compare.py`、`run_benchmarks.py`、`probe_arithmetic.py`。不增加观察或减少采样，完整最终 DTO 来自最后一次既有查询。


## 状态变化观察与冻结生产

- `src/igess/fish_source_runtime.py` 的 `observe`：能力协商、完整查询回退和观察错误；`fish_source_observation.py`：channel/token 基准、完整状态重建与返回对象隔离，参与适配器摘要。
- `<source>/simulation/Observation.lua`、`Query.lua` 的 `QueryChanges`：按部分返回变化，私有稳定投影复用；`Host.lua`/`cli.lua` 保证离线与鱼潮中可观察，观察操作不进入源历史。
- `<source>/proj/Script/Application/PlayerProductionRuntime.lua` 的 `BuildFrozenCalculator` → `Domain/Production/FishHallProductionCalculator.lua` 的 `BuildFrozenContribution` → `FrozenFishRateCache.lua`：冻结规则、会话独立的纯鱼厅产出复用；普通生产入口不启用此缓存。
- 回归入口：`tests/test_fish_source_observation.py` 与源 `tests/simulation_observation_changes_test.lua`；正式逐次观察差分和串行配对工具在 `.scratch/fish-state-and-advance-performance/`。既有准确/批量、满包孵化和跨进程恢复测试继续适用。


## 运行查询、指标和目标对照

已有运行分析先看 src/igess/analysis_api/service.py（AnalysisService）及 docs/analysis-api.md；Fish 指标在 fish_metrics.py 复用现有成长投影，目标协议在 targets.py。公共回归为 tests/test_analysis_api.py，使用冻结运行产物，不依赖长模拟。修改指标需同步定义版本、覆盖/证据口径及文档；不要在 CLI 复制领域计数。
