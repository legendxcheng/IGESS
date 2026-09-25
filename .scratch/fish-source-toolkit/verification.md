# 同源 Lua 执行工具包验证

目标发布：GameBalancer 0.5.15。

## 实现与边界

- 导出器从 simulation.cli 的静态依赖闭包构建单一 Lua 5.5 stripped 字节码，不打包 Script.Table 数值表；随包交付 Windows x64 解释器、DLL 和 Lua MIT 许可证。
- 工作台只把用户选择的 JSON 快照传入同源运行会话。每次会话冻结字节码、解释器和输入；运行清单同时记录交付包指纹、源 Lua 指纹、输入指纹。
- 保留 Python 3.11 sourceless 交付及白名单/绝对路径泄露审计；发布脚本默认 projects/fish_source，保留 -Project fish 的旧后端选项。
- 正式发布前提交所有本次源码。既有 .scratch/formal-run-deepening/gamebalancer-impact.md、projects/fish_source/.igess/、uv.lock 与 Fish 无关资源不属于发布输入，保持原状。

## 已完成验证

- 同源工具包、正式运行、同源报表、工作台定向回归：30 passed，89.78s。

- test_fish_source_toolkit.py：3 passed，35.26s。独立目录、PATH 无 Lua 的编译包 smoke 成功；checkpoint 可跨进程恢复；一天模拟 timeline/events/source_progression/source_behavior 与源码运行逐字节一致；审计拒绝伪装成 .luac 的 Lua 源码。
- 新增打包模块、导出器、同源引擎和客户端 Ruff / Pyright（Python 3.11）通过。operator_runtime 原有两处 prepared 可能为 None 的静态类型报错未作无关修改；本次只增加同源运行配置分支。
- 正式 Fish/toolkit 全量回归和真实工作台 E2E 由 prepare-release.ps1 在发布前执行；结果另见 release-verification.md。
