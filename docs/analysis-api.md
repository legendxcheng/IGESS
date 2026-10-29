# 运行分析接口（P0）

这些命令读取已登记运行，不执行模拟、模型检查或导表。JSON 响应沿用 `schema_version/command/ok/code/message/details/result`；成功评估出数值不达标仍返回退出码 0，目标判定在 `result.evaluation_status`。错误退出码 1，参数用法错误为 2。

## 运行查询

```powershell
uv run igess runs list --project projects/fish_source --status success --limit 10 --json
uv run igess runs show --project projects/fish_source --run-id <run_id> --json
uv run igess runs artifacts --project projects/fish_source --run-id <run_id> --json
```

list 支持 `--scenario-id/--engine-id/--status/--kind/--limit/--offset`。默认 kind=formal，`--kind all` 包含自动 smoke；limit 为 1–1000。按有效 started_at 降序、run_id 降序排序，无有效时间记录排在最后。同 ID 优先采用写入根。

默认读项目 runs 与兼容的 .igess/runs；`--runs-root` 指定该项目实际历史根（多项目 Dashboard 使用其项目子目录）。查询不创建目录。show 返回登记状态、输入 manifest 和 identity_complete；artifacts 区分 manifest 声明的模拟产物、注册表报告/状态及存在的开发诊断。失败或运行中可查询，但不能提指标或评估目标。

## 指标目录和提取

```powershell
uv run igess metrics describe --project projects/fish_source --engine-id fish_source --json
uv run igess metrics extract --project projects/fish_source --run-id <run_id> --profile-id default --metric-id growth.count --json
uv run igess metrics extract --project projects/fish_source --run-id <run_id> --profile-id default --metric-id growth.max_gap --time-basis online --json
```

`--dimensions` 是 JSON 对象，可指定 categories、day、week、through_day 或节点 identity，支持项以目录为准。PowerShell 传递复杂 JSON 时需遵守本机原生命令参数引用规则；复杂分析优先使用目标文件。

| 提供者 | 指标 | 选择器／口径 |
| --- | --- | --- |
| generic | resource.final | resource；最后采样余额，十进制字符串 |
| generic | purchase.count / prestige.count | 本段事件次数；purchase 可按 item（如 generator:mine）筛选 |
| generic | unlock.first_seconds | item；本段首次记录的墙钟秒 |
| generic | payback.seconds | item；保存的回本估计，缺失不填零 |
| fish_source | growth.count / growth.labels | 本段去重次数／分类标签次数，可选分类和自然日/周或截至日 |
| fish_source | growth.first_wait / max_interval / tail_wait / max_gap | online 时间基准；首次等待、相邻间隔、尾等待及三者最大值，可选分类 |
| fish_source | growth.node_seconds | identity；wall/online，segment/lifecycle；生命周期仅使用明确保存的首次记录或完整新玩家历史 |
| fish_source | growth.score | 显式 categories、scoring 和权重；刺激分与去重次数分开 |

所有指标包含定义版本、单位、画像、维度、time_basis、scope、coverage、reason 和 evidence。金额/小数为精确字符串，计数/秒数为整数。value_status 为 recorded、not_recorded、not_reached、not_applicable；非 recorded 不提供 value。部分覆盖可以有已观察值，但不能用来宣称整段目标通过。

自然日从场景秒 0 开始每 86400 秒分桶，周从第 1 日起每七日一组，左闭右开。恰好终点的事件属于后桶，后桶仍可能未完整覆盖。日/周与网页按在线场次组织的视图不是同一种分桶；成长事件身份和总数共用现有报告投影。首次变异有双标签，总数一次；在线空档排除离线时间。旧运行缺少基线或池事件时标明覆盖不足，不从当前表或曲线补造。

## 目标协议

```powershell
uv run igess targets evaluate --project projects/fish_source --run-id <run_id> --target-file examples/analysis/fish-targets-demo.yaml --json
uv run igess targets evaluate --project projects/fish_source --run-id <run_id> --target-file examples/analysis/fish-targets-demo.yaml --out .tmp/analysis-review-001 --json
```

示例仅演示协议，不是已批准的数值平衡目标。目标文件必须有 schema_version=1、target_set_id、字符串 version、来源说明 source 和非空 targets。每行须有唯一 target_id、metric_id、profile_id、dimensions、unit、time_basis、scope、aggregation=value、operator 和 value。值使用整数或精确小数字符串；支持 eq、gte、lte、between（两元素闭区间），可选非负绝对 tolerance，默认 0。YAML 小数保留文本精度，JSON 小数请写成字符串。

日期选择器 day、week、through_day 互斥且为正整数。through_day 表示从第 1 日累计到指定日结束，不把续跑片段当作完整累计。节点 identity 可使用已保存的 event_identity/item_id/metric_id；不会读取当前生产表判断一个尚未发生的配置身份。完整覆盖截止时仍未达到的节点可判 failed；未覆盖截止或缺少生命周期历史时为 not_evaluable。

刺激分必须选一种规则：scoring=per_label 时 weights 精确覆盖所选分类，双标签各计权重；scoring=per_event 时必须给 event_weight，每个所选独立事件只计一次。权重非负，两种规则不能混用。

每个目标输出 target、actual、delta、status、reason；between 的 delta 分上下界。总体优先 failed，其次 incomplete，其次 passed，全部不适用为 not_applicable。空目标、非法单位/选择器或重复 ID 是命令错误；缺失数据不会导致空集通过。

默认不写文件。`--out` 要求父目录已存在的新目录，输出 evaluation.json 与 evaluation.md，包含原始目标定义、规范化摘要、实际读取的运行产物摘要、指标版本及证据。不允许覆盖已有输出或写入运行历史、模型源目录、所选生产输入。文件通过绑定的目录句柄创建，路径被替换时不会转向其他目录写入。生成时间可变化，相同输入的业务结果确定。

## 开发接入与验证

Python 公共入口为 `igess.analysis_api.AnalysisService(project, runs_root=...)`，`execute("metrics.extract", ...)` 等操作返回 CommandResponse。`providers` 可注入按引擎 ID 注册的 MetricProvider；提供 describe/extract，声明 MetricDefinition，接收冻结的 ReportData 和 MetricQuery，返回带覆盖/证据的指标。未知引擎不回退 Generic。

服务读取一次运行快照，并在交付结果前复核实际读取文件的内容与文件身份；同字节替换、文件变化、身份冲突、越界路径和链接输入明确失败。目标文件采用同样复核。导出时只读取项目配置以保护外部输入目录，不加载生产数值。分析不改变 checkpoint、运行状态或耗时。

代码入口：`analysis_api/service.py`（公共流程）、`snapshot.py`（只读快照）、`metrics.py`（协议与 Generic）、`fish_metrics.py`（Fish 观察）、`targets.py`（目标验证/判断）、`export.py`（导出）、`cli.py`（参数传输）。测试通过公共服务和 CLI，使用冻结产物，不依赖 Lua 或当前生产表：

```powershell
uv run --extra dev python -m pytest tests/test_analysis_api.py tests/test_cli_help.py -q
```

P0 不改变旧 compare/gate/scan，不做跨运行可比性判定、自动调参、watch 修复、Excel 导入或 GameBalancer 发布。
