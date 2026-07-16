# IGESS Agent 使用指南

这份文档面向“调用 IGESS 做数值模拟和调参分析的 Agent”，不是面向开发
IGESS 源码的 Agent。仓库根目录是 IGESS 工具本体；具体游戏项目应放在独立
项目目录中，避免把工具代码、样例数据和真实项目输出混在一起。

## 首要工作流：一条规则，一次反馈

IGESS 的首要用户熟悉 Python，并由 Agent 协作完成模型。这里不设计面向
非技术用户的大表单；Agent 一次协助填写一条规则，把这一条规则写成可审计的
YAML 或 JSON change，调用 IGESS 验证并提交，再根据 `status` 与本次模拟证据
决定下一条。完整节奏是：

1. Agent 与用户确认当前只要补哪一条数值规则；
2. Agent 生成一个只含一个实体的 change，并带上刚读取的模型摘要；
3. `model apply` 在候选副本中映射、导表、lint、构建；模型一旦可运行，还会
   自动执行 10 个 tick 的 smoke；
4. Agent 展示状态、缺项、警告和本次 smoke 证据，再进入下一条规则；
5. 全部规则完成并达到 `ready` 后，才把同一个可追溯模型交给正式场景模拟和
   正式调参。

### 可复制的 PowerShell / CLI

以下命令与 `igess model <command> --help` 一致。`init` 只运行一次；后续循环
通常是 `status -> apply -> status`，模型达到 smoke 条件时 `apply` 自带一次
自动 smoke。显式 `simulate` 始终记为 formal run，即使场景名叫 `smoke`。

```powershell
.\.venv\Scripts\python.exe -m igess.cli model init --out projects/my-game --id my_game
.\.venv\Scripts\python.exe -m igess.cli model status --project projects/my-game --json
.\.venv\Scripts\python.exe -m igess.cli model apply --project projects/my-game --change changes/resource.yaml --json
.\.venv\Scripts\python.exe -m igess.cli model simulate --project projects/my-game --scenario smoke --json
```

也可以通过标准输入提交一条 change：

```powershell
Get-Content -Raw changes/resource.yaml | .\.venv\Scripts\python.exe -m igess.cli model apply --project projects/my-game --stdin --format yaml --json
```

文件输入只接受 `.yaml`、`.yml`、`.json`；标准输入的 `--format` 只接受
`yaml` 或 `json`。不加 `--json` 时输出简洁的人类可读结果。

### 一条 change 的准确格式

下面是一个完整的“只新增或更新 `resource:gold`”change。`fields` 里不能再放
`id`，也不能把多个实体拼成列表。先从 `model status --json` 读取
`result.model_digest`，原样填入 `if_model_digest`；下面的摘要只是格式示例。

<!-- exact-one-change -->
```yaml
version: 1
operation: upsert
entity: resource
id: gold
fields:
  name: Gold
  dimension: currency
if_model_digest: sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
```

`if_model_digest` 可以省略，但 Agent 协作时推荐保留，以免基于旧状态覆盖另一
次修改。新实体必须给出该实体的全部必填字段；已有实体允许只写要改的字段，
IGESS 会与当前规则合并后再验证。

### 稳定的 JSON 响应包络

所有 `--json` 响应都是一行 JSON，固定外层字段为
`schema_version`、`command`、`ok`、`code`、`message`、`details`、`result`。
下面是格式完整的 `model status` 示例；实际摘要、计数和 run id 以命令输出为准。

<!-- exact-json-envelope -->
```json
{
  "schema_version": 1,
  "command": "model.status",
  "ok": true,
  "code": "status",
  "message": "Model is runnable",
  "details": {},
  "result": {
    "state": "runnable",
    "model_digest": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    "structural_valid": true,
    "smoke_eligible": true,
    "entity_counts": {},
    "available_scenarios": ["smoke"],
    "missing_requirements": [],
    "warnings": [],
    "latest_smoke_run_id": "20260716T120000000000Z-smoke-change-1"
  }
}
```

程序判断成功与否应读取 `ok` 和进程退出码，分支应读取 `code`，不要解析
`message` 文案。`details` 放错误、恢复警告等诊断，`result` 放成功产物或失败
时仍可安全返回的结构化结果。

### 状态如何逐步变化

| 状态 | 含义 | Agent 下一步 |
| --- | --- | --- |
| `failed` | 当前源结构无效，不能作为候选模型 | 修复所列错误，不做数值结论 |
| `incomplete` | 已有规则有效，但还缺可执行链或必要引用 | 每次补一条 `missing_requirements` 指向的规则 |
| `runnable` | `smoke` 可执行，但尚无非 smoke 的正式场景 | 检查自动 smoke，再补正式场景或剩余规则 |
| `ready` | smoke 与至少一个正式场景都可执行 | 冻结当前摘要，进入正式模拟与调参 |

状态不要求机械地只向右移动：删除引用或写入无效内容会失败；增加正式场景可
让 `runnable` 变为 `ready`。每次都以响应里的 `state`、
`missing_requirements`、`warnings` 和 `model_digest` 为准。

### 自动 smoke 与显式模拟

只要应用后的候选模型 `smoke_eligible=true`，成功的 `model apply` 会在同一个
事务中自动 smoke：固定运行 10 个 tick，验证至少有资源、购买、解锁或转生等
可观察状态变化，并把关联 run id 写入 change record。尚不可运行时，apply 仍
可成功提交单条有效规则，`result.smoke.status` 为 `not_run`，然后由 Agent 按
缺项继续补规则。

自动 smoke 是一条规则后的快速反馈，不是平衡性结论。手动执行
`model simulate` 会从锁定的 source snapshot 临时导出并生成标准 output/report，
统一登记为 `kind=formal`；它不改正式源表，也不会冒充 apply 的自动 smoke。

### Source of truth、并发与失败恢复

`economy.yaml` 与 `Datas/*.xlsx` 是正式 source of truth；`luban_exports/` 是从
它们生成的运行时副本，不应手工编辑。一个 change 的成功记录位于
`changes/*.json`，失败审计位于 `changes/failed/*.json`，run 与报告位于
`runs/<run_id>/`。

若 `if_model_digest` 与当前摘要不同，apply 返回 `code=stale_model`，不修改正式
源；Agent 应重新运行 status、读取当前规则，再生成新的单条 proposal。映射、
导表、lint、build 或自动 smoke 在提交前失败时，事务回滚，正式源与导出保持
原样，并尽力写入 `changes/failed`。进程在提交中断后，下一个 model 命令会在
项目锁内先做崩溃恢复。恢复警告的位置按命令区分：

- `model status`: `result.warnings`；
- `model apply` / `model simulate`: `details.warnings`。

Agent 应把对应位置的恢复信息展示给用户，而不是擅自删除 `.igess` 的 journal
或备份。

### Dashboard 的边界

Dashboard 不填写或修改规则。它观察当前 model status、摘要、缺项、警告、
最近 change、自动 smoke 和统一 run history，并提供受控的 smoke/formal/advice
运行入口。规则的生成与提交仍由 Agent 使用 `model apply` 完成，避免浏览器表单
绕过 one-change、摘要检查和审计协议。

### 从建模切换到正式调参

达到 `ready` 后，先记录 `model_digest`，用 `model simulate` 运行非 smoke 的
正式场景，保留其 `run_status.json`、`output/run_manifest.json` 和报告；三者应
归属于同一个 source digest。随后可把这些 formal runs 交给 `compare`、
`scan`、`gate`、`advise` 等既有分析能力。任何参数修改仍回到“一条 change ->
自动 smoke -> 新 formal run”的可归因循环，不直接改生成的 JSON。

### 旧命令与外部数据测试

旧命令保持兼容：`export-tables`、`lint`、`run`、`report`、`dashboard`、
`compare`、`scan`、`gate`、`doctor`、`explain`、`advise`、`review-run`、
`yaml-plan`、`yaml-apply`、`review-proposal`、`verify-edits` 继续可用。它们适合
已有项目的批量/正式分析；新的 `igess model` 是 Agent 逐条建模的首要入口，
不是对旧脚本的破坏性替换。

默认测试不读取 `E:\stone-oasis`，因此可在任何干净环境运行。只有明确验证
Stone 工作簿快照时才执行：

```powershell
.\.venv\Scripts\python.exe -m pytest -m external_data tests/test_stone_role_level.py tests/test_stone_realm_progression.py
```

## 既有批量与分析工作流

下面各节保留旧命令的完整操作手册，供已经具备整套 YAML/Luban 数据的项目
做正式模拟、报告、扫描和验证。

## 推荐工作区结构

推荐在 IGESS 根目录下建立 `projects/`，每个游戏一个子目录：

```text
E:\IGESS\
  src/                         # IGESS 工具源码
  tests/                       # IGESS 工具测试
  docs/                        # IGESS 文档
  examples/                    # 官方样例
  data-tables/                 # 官方样例 Luban 源表
  projects/
    game_a/
      economy.yaml             # 该游戏的经济模型配置
      Datas/                   # 该游戏的 Luban 源表，可选
      luban_exports/           # 该游戏导出的运行时 JSON 表
      runs/                    # 单次模拟输出
      reports/                 # 静态报告
      compare/                 # 对比报告
      scans/                   # 参数扫描输出
      advice/                  # Agent Analyst 建议
      verify/                  # 人工改表后的验证输出
    game_b/
      ...
```

`projects/<project_id>/` 是 Agent 的主要工作区。不要把多个游戏项目的运行
产物都写到根目录 `.tmp/`，除非只是临时试跑官方样例。

## Agent 的职责边界

Agent 可以主动做：

- 为一个游戏项目导出 Luban 源表到 JSON；
- 执行 `lint`，在模拟前发现配置、公式、id 引用和表结构问题；
- 运行场景模拟并生成 JSON、CSV、Markdown 证据；
- 生成静态 Web 报告、对比报告、参数扫描和回归门禁结果；
- 运行 Agent Analyst，给出基于证据的调参建议；
- 在用户明确同意后应用 YAML-only 计划；
- 在策划手动改表后，验证当前表格是否匹配建议。

Agent 不应该默认做：

- 静默修改 `Datas/*.xlsx` 或项目正式 Luban 源表；
- 将 IGESS 根目录当作某个游戏项目目录；
- 混用不同游戏项目的 `economy.yaml`、表导出和运行产物；
- 在 `lint` 或 `doctor` 失败后继续给调参结论；
- 未经用户确认就执行 `yaml-apply --approve`。

## 新建一个模拟项目

如果用户说“为某个游戏建立模拟项目”，推荐创建：

```text
projects/<project_id>/
  economy.yaml
  Datas/
  luban_exports/
  runs/
  reports/
  compare/
  scans/
  advice/
  verify/
```

可以用内置模板快速生成一个起点：

```powershell
.\.venv\Scripts\python -m igess.cli init --out projects\<project_id>
```

如果项目已有真实 Luban 管线，让用户提供该项目的导出目录，并把它作为
`--tables`。如果只有 Luban 源表，则把源表目录作为 `--datas`，先导出 JSON。

## 每个项目的推荐变量

Agent 开始操作前，先确定这些路径：

```text
PROJECT      = projects/<project_id>
CONFIG       = projects/<project_id>/economy.yaml
DATAS        = projects/<project_id>/Datas
TABLES       = projects/<project_id>/luban_exports
RUN          = projects/<project_id>/runs/<run_id>
REPORT       = projects/<project_id>/reports/<run_id>
ADVICE       = projects/<project_id>/advice/<run_id>
```

`<run_id>` 建议使用可读名称，例如 `day1_baseline`、`day1_candidate_20260628`、
`scan_growth_114_118`。

## 大数与 SimNumber

增量游戏中的资源、消耗、产出、战力、经验、倍率等大数，必须按 IGESS 自带
的 `SimNumber` 数值语义处理。项目配置中应使用：

```yaml
model:
  number_backend: bignum_log
```

IGESS 会把表格和 YAML 里的经济数值解析为 `igess.numbers.SimNumber`。Agent
在建模、调参、写建议或扩展脚本时，应遵守这些规则：

- 不要把游戏经济大数转成普通 `float`、JavaScript `number` 或 Excel 的近似
  浮点语义后再下结论；
- 大数建议用字符串或科学计数法保存，例如 `"1e18"`、`"1e1000000"`；
- Python 侧需要计算经济数值时，使用 `SimNumber.parse(value)`、
  `SimNumber.zero()` 和 `SimNumber.one()`；
- 比较、乘除、幂运算和展示应走 `SimNumber`，最终展示使用
  `to_decimal_string()` 或 IGESS 生成的报告产物；
- 图表或外部展示需要降采样成浮点时，只能用于可视化，不应反过来作为调参
  判断的精确依据。

如果 `lint` 报 `number_backend` 不支持，先把模型改回 `bignum_log`，再继续
模拟。

## 标准模拟流程

对一个项目给结论前，至少执行导表、检查、模拟、报告四步：

```powershell
.\.venv\Scripts\python -m igess.cli export-tables --datas projects\<project_id>\Datas --out projects\<project_id>\luban_exports
.\.venv\Scripts\python -m igess.cli lint --config projects\<project_id>\economy.yaml --tables projects\<project_id>\luban_exports
.\.venv\Scripts\python -m igess.cli run --config projects\<project_id>\economy.yaml --tables projects\<project_id>\luban_exports --scenario day_1_progression --out projects\<project_id>\runs\day1_baseline
.\.venv\Scripts\python -m igess.cli report --run projects\<project_id>\runs\day1_baseline --out projects\<project_id>\reports\day1_baseline
```

如果项目没有 `Datas/`，但已经有外部 Luban 导出的 JSON 表，则跳过
`export-tables`，直接用该 JSON 目录作为 `--tables`。

关键输出：

- `runs/<run_id>/run_manifest.json`
- `runs/<run_id>/timeline.json`
- `runs/<run_id>/events.json`
- `runs/<run_id>/analysis.json`
- `runs/<run_id>/analysis.md`
- `runs/<run_id>/payback.csv`
- `reports/<run_id>/index.html`

Agent 回复用户时，应引用这些产物路径，并把结论绑定到具体证据，例如瓶颈
区间、回本时间、购买次数、解锁时间、资源曲线或回归门禁结果。

## 诊断流程

当路径、表导出或配置可能有问题时，先运行：

```powershell
.\.venv\Scripts\python -m igess.cli doctor --project projects\<project_id> --config economy.yaml --tables luban_exports
```

当用户问“为什么发生了某个事件”或需要追溯来源时：

```powershell
.\.venv\Scripts\python -m igess.cli explain --run projects\<project_id>\runs\<run_id> --event 0
```

`doctor` 或 `lint` 失败时，应先修复输入或向用户报告阻塞点，不要继续模拟。

## 对比、扫描和回归门禁

对比两个运行：

```powershell
.\.venv\Scripts\python -m igess.cli compare --base projects\<project_id>\runs\baseline --candidate projects\<project_id>\runs\candidate --out projects\<project_id>\compare\baseline_vs_candidate
```

扫描一个数值参数区间：

```powershell
.\.venv\Scripts\python -m igess.cli scan --config projects\<project_id>\economy.yaml --tables projects\<project_id>\luban_exports --scenario day_1_progression --param generators.fisherman.cost_growth=1.14..1.18:0.01 --out projects\<project_id>\scans\fisherman_growth
```

检查回归门禁：

```powershell
.\.venv\Scripts\python -m igess.cli gate --base projects\<project_id>\runs\baseline --candidate projects\<project_id>\runs\candidate --config projects\<project_id>\economy.yaml --out projects\<project_id>\compare\baseline_vs_candidate_gate
```

`gate` 返回退出码 `1` 表示门禁失败，不等于工具崩溃。Agent 应读取
`gate_results.md` 和 `gate_results.json` 后解释失败项。

## Agent Analyst 工作流

当用户希望 Agent 主动分析并提出调参建议：

```powershell
.\.venv\Scripts\python -m igess.cli advise --config projects\<project_id>\economy.yaml --tables projects\<project_id>\luban_exports --scenario day_1_progression --out projects\<project_id>\advice\day1
```

如果已有基线：

```powershell
.\.venv\Scripts\python -m igess.cli advise --config projects\<project_id>\economy.yaml --tables projects\<project_id>\luban_exports --scenario day_1_progression --baseline projects\<project_id>\runs\baseline --out projects\<project_id>\advice\candidate
```

重点阅读：

- `advice/<run_id>/advice.md`
- `advice/<run_id>/advice.json`
- `advice/<run_id>/run/`
- `advice/<run_id>/report/index.html`
- 可选的 `advice/<run_id>/compare/index.html`
- 可选的 `advice/<run_id>/gate/gate_results.json`

`advice` 里的表格建议是 human-only。Agent 可以总结建议、解释证据、准备验证，
但不应默认直接修改 Excel/Luban 源表。

## YAML 计划

当用户要求补充回归门禁或调整 YAML 配置时，先生成计划：

```powershell
.\.venv\Scripts\python -m igess.cli yaml-plan --config projects\<project_id>\economy.yaml --intent "Add early regression gates" --out projects\<project_id>\advice\yaml_plan
```

只有在用户明确批准这个计划后，才执行：

```powershell
.\.venv\Scripts\python -m igess.cli yaml-apply --config projects\<project_id>\economy.yaml --plan projects\<project_id>\advice\yaml_plan\yaml_plan.json --approve --tables projects\<project_id>\luban_exports
```

`yaml-apply` 会在配置旁边生成 `.bak`，并在应用后 lint 失败时恢复配置。

## 人工改表后的验证

当策划根据建议手动改完源表后，先审阅建议：

```powershell
.\.venv\Scripts\python -m igess.cli review-proposal --proposal projects\<project_id>\advice\day1\advice.json --out projects\<project_id>\verify\proposal_review
```

如果已经重新导出了 JSON 表：

```powershell
.\.venv\Scripts\python -m igess.cli verify-edits --config projects\<project_id>\economy.yaml --tables projects\<project_id>\luban_exports --proposal projects\<project_id>\advice\day1\advice.json --scenario day_1_progression --out projects\<project_id>\verify\day1
```

如果需要从 `Datas/` 临时导出后验证：

```powershell
.\.venv\Scripts\python -m igess.cli verify-edits --config projects\<project_id>\economy.yaml --datas projects\<project_id>\Datas --proposal projects\<project_id>\advice\day1\advice.json --scenario day_1_progression --out projects\<project_id>\verify\day1
```

验证结果：

- `passed`：当前表值匹配明确建议；
- `needs_review`：建议是描述性区间或人工判断项；
- `failed`：表值缺失、不匹配，或基线门禁失败。

Agent 应把 `verification_report.md` 作为主要交付证据。

## Dashboard

需要交互式查看时，可为某个项目启动本地 Dashboard：

```powershell
.\.venv\Scripts\python -m igess.cli dashboard --project projects\<project_id> --config economy.yaml --tables luban_exports --host 127.0.0.1 --port 8765
```

打开：

```text
http://127.0.0.1:8765/
```

如果多个项目并行打开 Dashboard，为每个项目使用不同端口。

## Agent 交付清单

每次完成一次模拟、分析或验证后，Agent 应向用户说明：

- 使用的是哪个 `projects/<project_id>/`；
- 运行了哪些命令，以及是否通过；
- 关键产物路径；
- 主要发现和证据；
- 涉及大数判断时，是否保持了 `SimNumber` / `bignum_log` 语义；
- 是否存在 `lint`、`doctor`、`gate` 或 `verify-edits` 失败；
- 哪些建议仍需策划人工改表；
- 是否有 YAML 计划等待用户批准；
- 哪些验证没有运行，以及原因。

如果修改的是 IGESS 工具源码或文档本身，还应运行：

```powershell
.\.venv\Scripts\python -m pytest
```
