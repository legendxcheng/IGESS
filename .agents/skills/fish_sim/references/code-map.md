# Fish 代码导航

以下路径相对 IGESS 根目录，`<source>` 来自 `projects/fish_source/economy.yaml` 中的 `engine.source_runtime.project_root`。按任务只读相关行指向的模块；符号若已迁移，用 `rg` 追踪调用方并修正本导航。

## IGESS 模拟侧

| 要改什么 | 先看哪里／检索词 | 对应验证 |
| --- | --- | --- |
| 场景时长、在线窗口、权重、行动耗时、采样 | `projects/fish_source/economy.yaml`：`scenarios`、`session_patterns`、`behavior_weights`、`behavior_durations` | `tests/test_fish_source_formal.py` |
| 引擎准备、能力检查、身份与策略 | `src/igess/fish_source_engine.py`：`FishSourceEngineAdapter.prepare`、`_REQUIRED_OPERATIONS`、`_integration_code_digest` | `tests/test_fish_source_current_rules.py`、`tests/test_fish_source_formal.py` |
| 玩家选行为、动作互斥、时间推进、截断恢复 | 同文件 `_ProfileRun`：`_choose`、`_act`、`execute`、`_advance_to`、`_continue_throw`、`_continue_tide`、`checkpoint` | `tests/test_fish_source_natural_landing.py`、`tests/test_fish_source_tides.py`、`tests/test_fish_source_joint.py` |
| Lua 启动、JSON 请求、冻结输入、摘要、replay | `src/igess/fish_source_runtime.py`：`FishSourceRuntime`、`request`、`_freeze_source`、`checkpoint`、`restore` | `tests/test_fish_source_formal.py`、`tests/test_fish_source_joint.py` |
| 图鉴领取、枪选择与里程碑 | `fish_source_engine.py` 的 `_choose`、`_observe_codex`；`src/igess/fish_source_guns.py` 的 `choose_gun_action`、`GunMilestones` | `tests/test_fish_source_codex.py`、`tests/test_fish_source_guns.py` |
| 蛋和鱼潮观察、去重、报告行 | `src/igess/fish_source_eggs.py`、`src/igess/fish_source_tides.py`；实际调度仍在 `_ProfileRun` | `tests/test_fish_source_eggs.py`、`tests/test_fish_source_tides.py` |
| 在线收入核算、消费回补、领取转账、退款 | `src/igess/fish_source_income.py`：`SourceIncome.observe`；`src/igess/fish_source_numbers.py`：`source_decimal` | `tests/test_fish_source_income.py`、`tests/test_fish_source_joint.py` |
| 成长和行为 JSON 产物 | `src/igess/fish_source_reports.py`：`write_source_progression_artifacts`、`project_source_behavior` | `tests/test_source_fish_reporting.py` |
| Web 报告指标及曲线 | `src/igess/reporting/source_fish.py`：`build_source_projection`；页面继续追踪 `view_model.py`、`static.py`、`assets/report.js`、`assets/report.css` | `tests/test_source_fish_reporting.py`、`tests/test_reporting_view_model.py` |
| 收集成长、双标签去重、旧报告首次覆盖 | `src/igess/reporting/source_collection.py`：`CollectionGrowth`；`fish_source_engine.py` 的 `collection_growth` 起始基线、`fish_source_runtime.py` 的冻结名称；源 archive 与 `GunMilestones` 负责续跑历史 | `tests/test_fish_collection_reporting.py`、`tests/test_fish_collection_formal.py` |
| 正式运行、历史终态、报告失败 | `src/igess/authoring/service.py` → `formal_run.py` → `engines.py`；开发工作流 `workflows.py`，历史 `run_registry.py` | `tests/test_formal_run.py`、`tests/test_run_registry.py` |
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
| 源协议回归 | `<source>/tests/` 中 `simulation_*` | Lua 宿主、CLI、恢复与待完成副作用；按源仓库说明执行 |

先确认源码和导表实际存在。缺少外部源码时仍可分析 IGESS 调用边界，但不能把接口推断当成已核实的源规则，也不能声称完成源集成验证。

## 进一步查证

- 玩法背景：`<source>/gdd/01-核心玩法概述.md`；随机算法 `05-核心随机算法.md`；重生 `04-重生机制.md`；玩法表现 `06-核心玩法表现设计.md`。
- 已接入机制与验收边界：`projects/fish_source/README.md`、`RoadMap.md` 及它们链接的 `.scratch/` 规格／验证记录。记录中的时间和指标只属于对应输入版本。
- 平台术语与交付约束：根目录 `CONTEXT.md`；涉及交付时读 `docs/adr/0001-distribute-execution-toolkit-from-separate-repository.md`、`0002-distribute-igess-without-python-source-files.md`。
- 新规格／票据按 `docs/agents/issue-tracker.md` 与 `triage-labels.md` 放入 `.scratch/`，按 `docs/agents/domain.md` 使用领域术语。
