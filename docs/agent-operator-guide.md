# IGESS Agent 使用指南

这份文档面向“调用 IGESS 做数值模拟和调参分析的 Agent”，不是面向开发
IGESS 源码的 Agent。仓库根目录是 IGESS 工具本体；具体游戏项目应放在独立
项目目录中，避免把工具代码、样例数据和真实项目输出混在一起。

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
