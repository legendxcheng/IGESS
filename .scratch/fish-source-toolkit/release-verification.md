# GameBalancer 0.5.15 发布验收

2026-09-25，按 publish-gamebalancer 技能完成，工作台由用户确认关闭。

- IGESS 构建源码：6ad8fbe04e93b7af3867adffb1043ba2297b186d（已推送 main），包含此前性能优化 e2b1885。
- Fish 源码：8d1410c515b8620d3cdc7e90ab5ba80bc4bc382e（已推送 master）。161 个被打包模块全部已跟踪且无工作区修改；未跟踪的 PlayerHUDService.lua 不在依赖闭包中，不交付。完整源树指纹用于记录构建环境，包含闭包外文件；交付文件另有逐文件哈希。
- GameBalancer：5c3f532c37ab5943e0213be48ab2b5f684c6536d（已推送 master）。本地 HEAD、origin/master、远端 refs/heads/master 一致；工作区干净。

## 验证结果

正式命令：`.codex/skills/publish-gamebalancer/scripts/prepare-release.ps1 -Version 0.5.15`。

- Fish、同源运行/工具包/报表、原工作台回归：244 passed，9 deselected，91.70s。另有发布前定向回归 30 passed。
- 新增三项交付测试覆盖：脱离源码目录且 PATH 无 Lua；checkpoint 跨进程恢复；一天核心产物逐字节等价；Lua 源码伪装字节码被拒绝。
- 真实工作台表单 E2E：`20260925T100959715085Z-smoke`，status=success，engine_id=fish_source。
- 工作台首页显示 0.5.15，仅监听 127.0.0.1；报告 HTTP 200，完成提示通过。
- 运行清单的输入指纹匹配生产 JSON，Lua 源码指纹匹配随包 manifest。
- 测试/导出前与 E2E 后的生产 JSON 文件列表、长度、SHA256、修改时间一致，生产目录绝对只读。
- 92 个交付文件严格匹配清单和逐文件 SHA256；零 .py/.pyi/.lua/source map/测试/源码绝对路径。Lua 解释器与 DLL 均为 Windows x64；161 个模块无 Script.Table 数值表，Lua 运行包五个文件共 1,185,815 字节。
- start.bat 保持已验证的 `--bundle "."`，无启动器回归；旧 schema.pyc 由正式导出器删除。

## 指纹

- Lua 完整源树：b39a7da4c6b8bb72e77cbfe9b658f10c486dde1a9dc8dc49cf89c0613160d600
- 选定 JSON：f16de5f913f7e66157455735d5763dfbf1da924d10c43afcf49374f23fe34b77

策划更新：关闭工作台，执行 git pull，再启动 start.bat。Lua 已随包附带，无需另装；旧历史保留，不允许跨工具版本比较，升级后重新运行场景。
