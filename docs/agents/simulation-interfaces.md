# IGESS 模拟执行接口

执行模拟和分析的 Agent 从这里选择接口。命令在 IGESS 根目录运行，使用 Python 3.11+ 及已安装的项目依赖；下文采用 `uv run igess`，已有虚拟环境也可用 `python -m igess.cli`。查看某项命令的完整参数使用 `--help`。

IGESS 提供执行、运行身份、产物查询、指标提取和目标对照。领域 Skill 提供游戏规则、玩家策略、指标的业务解释和调优流程。普通执行任务先使用这些接口；开发新能力时再读 [平台代码导航](../code_walkthrough.md)。本索引描述源码工作区的现有能力，执行工具包的交付范围另见 [工具包说明](../operator-toolkit.md)。

## 按任务选择接口

下表命令前缀均为 `uv run igess`，`<project>` 为模型项目目录，`<run_id>` 为登记 ID，`<output>` 为实际模拟产物目录。

| 任务 | 接口及必要参数 | 执行与写入 | 结果检查／详细协议 |
| --- | --- | --- | --- |
| 检查模型与可用场景 | `model status --project <project> --json` | 会执行就绪 probe；Fish 为十 tick，不登记正式运行 | `result.state`、`available_scenarios`、缺项和警告；[模型协议](../agent-operator-guide.md) |
| 新建正式运行 | `model simulate --project <project> --scenario <scenario> --json` | 执行模拟，登记运行并写产物、报告 | 返回的 `run_id`、`output_dir`、`report_index` 与终态；[正式运行](../formal-runs.md) |
| 从存档继续 | 上一命令加 `--resume-run-id <run_id>` 或 `--checkpoint-in <checkpoint>`（互斥）；Fish 可加 `--until-seconds <absolute_seconds>` | 创建新运行；ID 从成功历史解析，检查引擎与输入兼容性；自定义历史读写用 `--runs-root <项目历史目录>` | Fish 支持兼容的更长场景，包括 Week1 → Week2 → Week3 → Month1（四周），统计仅覆盖新增区间；[续跑契约](../../projects/fish_source/README.md#按周跑测与运行-id-接续) |
| 找到已有运行 | `runs list --project <project> --json` | 只读历史，不检查模型、不模拟 | 可按场景、引擎、状态筛选和分页；[运行分析接口](../analysis-api.md) |
| 查运行身份与产物 | `runs show` / `runs artifacts --project <project> --run-id <run_id> --json`（两个子命令均需这些参数） | 只读登记和冻结产物 | 登记状态、manifest、`identity_complete`、实际文件位置；[运行分析接口](../analysis-api.md) |
| 发现引擎指标 | `metrics describe --project <project> --engine-id <engine> --json` | 只读指标定义，不模拟 | 指标 ID、单位、维度、时间与范围；[指标协议](../analysis-api.md) |
| 提取已有指标 | `metrics extract --project <project> --run-id <run_id> --profile-id <profile> --metric-id <metric> --json` | 读取成功运行的冻结产物 | 先检查 `coverage`、`value_status`，再读值和证据；[指标协议](../analysis-api.md) |
| 对照目标 | `targets evaluate --project <project> --run-id <run_id> --target-file <targets.yaml> --json` | 默认只读；可用 `--out <new-directory>` 写评估文件 | 命令成功与 `evaluation_status` 分开；[目标协议](../analysis-api.md) |
| 重生成报告 | `report --run <output> --out <report-directory>` | 读已有产物，写静态报告；不模拟 | 只能更新展示，不能补采缺失数据；[报告说明](../code_walkthrough.md#82-输出与展示链) |
| 比较已有产物 | `compare --base <base-output> --candidate <candidate-output> --out <directory>` | 读取两个运行，写比较报告；不模拟 | 先核对输入身份与指标覆盖；[操作说明](../agent-operator-guide.md#对比扫描和回归门禁) |
| 检查既有回归门槛 | `gate --base <base-output> --candidate <candidate-output> --config <economy.yaml> --out <directory>` | 读取已有产物和门槛配置，写判定；不模拟 | 使用已配置且适用的门槛，退出码 1 可表示门槛未通过；不是 Fish 成长目标评估的替代入口 |

`model` 的上述 JSON 命令以及 `runs/metrics/targets` 使用 `schema_version/command/ok/code/message/details/result` 包络。判断工具执行读取退出码、`ok` 和 `code`；不要解析提示文案。`targets evaluate` 成功计算出“不达标”仍可退出 0，业务判断在结果中。`report/compare/gate` 沿用各自旧命令协议，不假定支持 `--json` 或同一包络。

查询指定 Dashboard 历史时，`runs/metrics/targets --runs-root` 应传该项目的实际历史根；多项目 Dashboard 的 `--runs-root` 则是各项目历史的父目录。默认查询规则及覆盖状态定义以 [运行分析接口](../analysis-api.md) 为准。

## 执行顺序与完成条件

### 用户要求分析已有结果

1. 用 `runs list` 定位用户指定运行，以 `runs show` 确认状态和输入身份，再用 `runs artifacts` 找实际产物。失败或运行中可查询诊断，不能按成功运行提指标。
2. 用 `metrics describe` 选择已提供的指标，再用 `metrics extract` 提取。先检查覆盖、本段／生命周期、墙钟／在线时间及未记录原因，保留精确数值字符串。
3. 有已确认的目标文件时用 `targets evaluate`。目标来源、版本、权重及日期范围必须明确，示例文件仅用于演示协议。
4. 交付运行 ID、产物位置、观察结果、偏差与证据，区分原因推断和调整建议。查询或目标对照不需要先运行 `model status`、导表或重新模拟。

### 用户委托新模拟或续跑

1. 从项目配置和领域文档确认引擎、实际输入、场景、画像与运行时依赖；需要就绪检查时用 `model status`。已有明确运行授权时直接执行其范围。
2. 调用 `model simulate`；仅在需要续跑时传 checkpoint，由引擎验证兼容性。命令响应中的路径作为产物入口，不拼接猜测运行目录。
3. 核对登记终态、manifest 身份和所需产物。报告失败仍是正式运行失败；保留的模拟产物可用于排查，不把它描述为完整成功。
4. 进入已有结果的分析流程。续跑的本段计数不能充当从新玩家起的累计计数。

## 引擎与职责边界

- Fish 使用 `projects/fish_source` 和 [fish_sim](../../.agents/skills/fish_sim/SKILL.md)。实际数值来自 `engine.source_runtime.data_root`；生产源表的修改和导出按该 Skill 的人类决策流程执行。`model apply` 的通用 authoring 工作簿不是 Fish 生产改表入口。
- Generic 的逐条建模使用 `model init/apply`，精确 change 与事务协议见 [Agent 使用指南](../agent-operator-guide.md)。旧 `run/scan/advise` 只支持 Generic；其中扫描和建议会执行模拟，不能用来只读分析 Fish 旧报告。
- `compare/gate` 保留既有产物口径，不自动证明两次运行可比，也不保证覆盖 Fish 的全部成长指标。Fish 目标对照优先使用已注册的 `metrics/targets`；跨运行归因需要核对场景、画像、策略、种子、源码／适配器和导表身份。
- `model watch` 会持续监听输入并触发正式模拟，适用于明确要求自动重跑的工作；它不属于运行查询。当前接口不提供自动调参、跨运行可比性判定或 `SettingValue.xlsx` 自动导入。
- 接口缺少需要的指标时，先报告缺失定义或采集证据。补充平台指标应接入 `MetricProvider`；执行 Agent 的一次性只读分析须注明临时口径，不冒充平台正式指标。修改生产表、游戏规则或发布 GameBalancer 均沿各自任务范围执行。

## 平台开发维护

Python 的已有分析公共入口是 `igess.analysis_api.AnalysisService`，完整调用和提供者协议见 [运行分析接口](../analysis-api.md#开发接入与验证)。正式模拟复用 `AuthoringService`／`FormalRunExecutor`，内部调用关系见 [代码导航](../code_walkthrough.md)。执行 Agent 通过 CLI 使用上述能力，无需直接组装内部执行器或解析网页取得指标。

新增或改变执行接口时，同步更新本索引、对应详细协议和根 [AGENTS.md](../../AGENTS.md) 的能力入口；领域 Skill 只补受影响的业务契约及链接。命令存在、引擎支持与交付包已发布分别核验，不相互替代。
