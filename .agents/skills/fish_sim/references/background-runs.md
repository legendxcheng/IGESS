# 独立 CLI 后台跑测（显式选择）

默认使用 [已运行的 IGESS 服务](dashboard-runs.md)。本说明仅用于用户明确选择独立 CLI 的任务；该任务不会进入 Dashboard 的当前任务面板。

适用于 Windows 本机交互桌面。在 IGESS 根目录，用已安装项目依赖的 Python 执行；预检沿用平台接口与 fish_sim。本脚本只包装公共 CLI，不改场景、输入或运行登记规则。

```powershell
.\.tmp\py311-venv\Scripts\python.exe .agents/skills/fish_sim/scripts/run_background.py --scenario week_1_growth
```

按用户要求替换场景。支持 `--project`、`--runs-root`、`--resume-run-id`、`--checkpoint-in`、`--until-seconds`；续跑参数互斥及兼容检查仍由 CLI 执行。使用其他已安装项目依赖的 Python 环境时替换解释器路径。

脚本创建唯一任务目录，默认在 `.scratch/fish-background/`，最多等待五秒启动回执后返回。后台 worker 与模拟进程不依赖 Agent 继续调用工具；不自动重试，不自动分析或打开报告。后台进程启动不显示控制台，命令结束时才显示通知对话框。

| 文件 | 用途 |
| --- | --- |
| `job.json` | 原始命令、工作目录、场景 |
| `status.json` | worker／CLI PID、运行阶段、退出码，以及 CLI 返回的运行 ID 和产物路径 |
| `response.json` | CLI 原始标准输出，运行中可能为空，结束后按 JSON 包络核验 |
| `stderr.log` / `worker.log` | CLI 错误／worker 启动与异常诊断 |

`running` 仅表示 CLI 已启动；`command_succeeded` 要求退出码为 0 且包络 `ok=true`，不替代正式运行与产物验证；`command_failed` 包括非零退出、错误包络和无法解析的响应。`startup_unconfirmed` 表示启动未确认，先检查现有任务，避免重复提交。任务目录 ID 不是 IGESS run ID；正式 ID 从 CLI 响应取得。

完成状态先落盘，再弹出“可以唤醒 Agent 了，请回复：分析这次跑测”，附场景和任务目录。通知等待用户关闭，因此 worker PID 仍存在不表示模拟未完成；`notification=pending` 也可能表示弹窗正在等待关闭，关闭后记录 `dismissed`，通知调用异常记录 `failed`。这条提示仅发到本机桌面，不向聊天、邮件或其他服务发送消息。

Agent 的启动交接示例：

> `week_1_growth` 已在后台启动。任务目录：……；状态文件：……。命令结束后会弹出 Windows 提示，成功或失败都会通知。收到提示后回复“分析这次跑测”，我再核验结果并继续分析。

交接后结束回合。用户唤醒时，从该目录恢复上下文，按 fish_sim 核验并继续。若机器重启或进程被外部终止，可能遗留 `running` 而没有通知；此时结合进程、日志和平台登记判断，保留证据，不把遗留状态当作仍在正常运行，也不自动重跑。无交互桌面或通知未实际验证时说明限制，不承诺用户已收到提示。
