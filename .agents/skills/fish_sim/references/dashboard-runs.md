# 通过已运行的 IGESS 服务跑测

本机默认使用用户选定的主 Dashboard `http://127.0.0.1:8771`。提交脚本是现有 HTTP 接口的客户端，只使用 Python 标准库；模拟由服务自己的 Python 环境执行。它不会启动服务、重启实例或在客户端启动模拟。

## 提交与查询

从 IGESS 根目录运行：

```powershell
.\.tmp\py311-venv\Scripts\python.exe .agents/skills/fish_sim/scripts/run_dashboard.py submit --scenario week_1_growth
.\.tmp\py311-venv\Scripts\python.exe .agents/skills/fish_sim/scripts/run_dashboard.py status
```

选择其他实例加 `--server http://127.0.0.1:<端口>`；选择项目加 `--project <项目目录>`。项目必须是该实例已登记的标准 `economy.yaml` 项目，脚本按与 Dashboard 相同的配置路径身份选择项目路由，未知项目不会回退到首页默认项目。首次访问可能触发服务的模型检查，页面尚未准备好时先检查状态再提交。

续跑使用 `submit --scenario week_2_growth --resume-run-id <成功的Week1运行ID>`，历史起点必须来自该服务的项目历史库。源输入与场景兼容性继续由原引擎核验。`--checkpoint-in`、`--until-seconds`、客户端 `--runs-root` 暂不受 HTTP 表单支持，脚本直接拒绝这些参数；沿用服务启动时的历史根。需要这些能力时明确说明限制，由用户选择独立 CLI，不能忽略参数或悄悄转为从零开始。

提交通过项目正式运行表单的 CSRF token 与同源 Origin 校验，保留服务的项目互斥。只发送一次 POST，不自动重试。客户端回执默认写入 `.scratch/fish-dashboard/<提交标识>/submission.json`，可用 `--jobs-root` 改变回执存放位置；这个位置不改变服务的历史库。

| 回执状态 | 含义与处理 |
| --- | --- |
| `accepted`，`ok=true` | 服务返回接收确认；只完成启动交接，等待服务执行和结果核验 |
| `not_submitted` | 提交前失败，如服务不可达、项目不在目录、已有运行任务、场景／续跑起点不可用 |
| `rejected` | POST 被服务明确拒绝；检查网页、互斥或校验错误 |
| `submission_unknown` | POST 超时、连接中断或响应异常；任务可能已被服务接收，先查网页和历史，禁止直接重提 |

`submission.json` 在发送 POST 前落盘，包含实例身份、项目、场景、续跑 ID、提交时间和页面链接。它不是模拟结果，也不包含 CSRF token。`accepted` 的退出码为 0，其他提交状态退出码为 1。

## 完成与身份核验

交接 `dashboard_url` 和 `task_url`。网页显示运行中、耗时、成功／失败以及报告或诊断链接；不承诺精确百分比或剩余时间。默认没有 Windows 弹窗，也不会在 Agent 已结束回合后自动发送聊天消息。关闭网页不会取消任务；服务退出可能中断执行。

`status` 返回 `current_task`：`running` 为执行中，`success`／`failed` 为服务任务终态，`idle` 表示本服务会话尚无任务。状态查询成功的 `ok=true` 只表示 HTTP 查询成功。它不提交模拟；首次访问未初始化的项目仍可能触发 Dashboard 的模型检查。

`/task` 只保留当前任务，没有永久任务 ID；下一次提交会覆盖它。`instance_id` 变化表示服务已重启。用户唤醒时读取原提交回执，核对服务、场景、动作及历史。即使同场景也可能已被重跑，不能仅凭场景相同认定为原任务；存在覆盖或重启时，通过 `runs list` 的登记时间、场景与冻结身份定位原运行。有歧义时保留候选并说明，不能直接选择“最新一次”。

取得具体 `run_id` 后，使用 `igess runs show/artifacts --project projects/fish_source --run-id <ID> --json` 核对登记终态与产物。默认主 Dashboard 使用项目默认历史；自定义历史实例查询需额外传该项目实际 `--runs-root`（多项目服务历史父目录下的项目子目录）。之后按 fish_sim 核对 manifest、checkpoint、成长与行为文件；服务任务成功与业务目标达标分别判断。

## 独立 CLI

用户明确选择独立 CLI 时，使用 [旧后台脚本](background-runs.md)。它的本机弹窗、`status.json` 和 `response.json` 仅适用于该独立任务，不属于 Dashboard 当前任务。已有独立运行不能迁移成服务当前任务；本入口作用于后续新提交。
