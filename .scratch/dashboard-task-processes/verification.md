# Dashboard 独立任务进程验收

日期：2026-10-28。环境：Windows，仓库 `.venv` Python 3.13.11；基线提交 `272e9ba02bee5ebaa9af4b135256d16c07a10ac0`。

## 实现

模拟、分析和模型检查使用新解释器，当前 IGESS 源码直接编译加载。控制协议独立于日志，任务回执与实际登记终态交叉核验。运行崩溃仅处理该任务拥有的运行；已保存终态不会被通信故障覆盖。输出有界保存，任务结束及服务受控关闭时清理进程树、管道和临时目录。

保留后台立即受理、项目互斥、项目锁、CSRF、Host/Origin、历史管理与静态报告读取。工作区已有的 Fish、历史清理及报告 UI 修改未回退，也不归入本任务提交。`docs/code_walkthrough.md` 已同步执行链说明；该文件在本任务前为未跟踪的综合文档，继续保留在工作区。独立机制文档为 `docs/dashboard-task-processes.md`，Fish skill/code map 同步增加导航。

## 自动化

- TDD：新代码重载测试先观察到结果仍为 1 而非 2；进程崩溃测试先观察到遗留 running；后代回收测试先观察到子进程仍存活。逐项修复后通过。
- 真实进程验收 `tests/test_dashboard_task_processes.py`：**12 passed，70.98 秒**。从 HTTP 提交、轮询到真实产物；修改同尺寸同时间戳源码，下一次模拟／报告改变而旧报告不变，服务实例不变。
- 覆盖 authoring 与兼容配置、中文空格路径、自定义历史根、跨项目并发、刷新缓存、语法错误恢复、报告失败保留产物、启动失败、回执丢失、2 MB 输出不阻塞。启动／通信故障仅从 `launch_process` 边界注入。
- Windows 覆盖正常完成、异常退出及服务受控关闭时的后代回收；受控关闭检查工作进程、后代、管道、临时目录和失败终态。
- 工作区 Dashboard／历史清理／正式运行／CLI 组合回归：**119 passed，82.19 秒**（日志增强及最后两项进程测试前）。之后重跑真实进程测试及重启／正式运行回归：**12 passed** 和 **13 passed**。
- 为验证提交不依赖其他未提交修改，将实际暂存树导出至独立目录，运行新进程验收、Dashboard、项目切换、服务重启、正式运行和 CLI 回归：**96 passed，90.99 秒**。
- Python 编译检查与暂存差异空白检查通过。项目没有配置独立的类型检查器。
- 全量测试：**1657 passed、6 skipped、16 deselected、3 errors，1198.30 秒**。3 项错误均为 `test_fish_source_toolkit.py` 的共享 fixture 使用默认 Python 3.13，导出器要求 Python 3.11 x64。设置 `IGESS_BUILD_PYTHON=D:/Program Files/Python311/python.exe` 后仅重跑该文件：**3 passed，59.96 秒**；没有改动工具包或测试逻辑。日志位于 `.tmp/dashboard-task-baseline/full-pytest.log` 和 `toolkit-retry.log`。

## 实际 Fish / Lua

通过真实 Dashboard HTTP 入口运行 `projects/fish_source` 的 `smoke`；使用 `E:/fish-oasis` 源码和 `D:/Program Files (x86)/Lua/lua55.exe`。任务 success，耗时 7.5 秒。

运行 ID：`20261028T103419431127Z-smoke`。产物位于 `.tmp/dashboard-task-smoke/runs/p-a24e55fc69ca9f76/20261028T103419431127Z-smoke/`。已检查 run_status、manifest、timeline、final_checkpoint 和 HTML 报告；引擎为 `fish_source`。

模型身份：`sha256:541745bd0bfb70a8cb48ac68b075b3d8cdea8298943d37e23db1e1adcc8ac545`。本次没有编辑生产 Fish 公式、源码或导表，也没有发布 GameBalancer。

## 审查

- Standards：独立审查 0 项问题，依据任务开始时保存的差异基线隔离其他工作区修改。
- Spec：首次提出日志留存、受控关闭验收、通信故障注入边界三项 P2；全部修复。复核确认三项关闭，无其他明确规格问题。复核使用上述 Windows 测试证据，没有重复执行测试。

## 服务与浏览器

本机既有 `http://127.0.0.1:8771` 服务已通过带 CSRF 的重启接口完成首次升级；旧任务／模型检查空闲后才请求，服务实例变化且新任务说明出现。其他端口服务未主动重启。

浏览器起初被自动审批拦截；用户明确授权当前 Node REPL 浏览器客户端后，在原客户端路径上成功访问，没有改用其他控制路径。真实点击 Fish `Run smoke scenario (formal)`，页面即时显示 Running、耗时及禁用重复提交，随后自动显示 Success、`Simulation complete: smoke`、耗时 7.7 秒及报告入口；历史新增 `20261028T105605094566Z-smoke`。

实际打开本次报告，分别核对内嵌面板截图及独立标签页可访问内容：报告标题为“IGESS 调优报告 - 冒烟验证”，模拟时长 10 秒、完整投掷 1 次，运行总览和成长信息正常显示。内嵌面板 Loading 已清除，报告 URL 对应上述运行 ID。检查重启弹窗：明确普通模拟／报告代码更新无需重启，影响全项目的说明保留，初始焦点为 Cancel；点击 Cancel 关闭，未额外重启服务。浏览器截图保留于本次会话证据。
