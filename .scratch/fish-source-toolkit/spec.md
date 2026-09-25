# GameBalancer 同源 Lua 交付

Status: resolved

2026-09-25：用户明确选择将同源 Lua 后端接入 GameBalancer 后发布，目标版本 0.5.15；已关闭工作台，并授权提交及推送源码与分发仓库。

将 `projects/fish_source` 通过正式导出器交付为可离线、脱离源码仓库运行的工作台。Lua 业务保持唯一来源，使用 strip 后的 Lua 5.5 字节码及固定 Windows x64 Lua 解释器；不交付 Lua 源码、生产数值表、测试或开发文件。选定 JSON 是唯一数值输入，绝对只读。继续沿用 Python 3.11 sourceless 交付、发布白名单、路径泄露检查、正式运行历史及跨工具版本禁止比较。

验收：导出包在独立目录、PATH 无 Lua 的情况下可运行同源 smoke，与源码运行核心产物等价；checkpoint 可恢复；包内不得有 .py/.pyi/.lua/source map。通过 Fish/toolkit 回归及真实工作台表单 smoke，报告 HTTP 200、127.0.0.1 监听、生产输入哈希/时间戳不变。复核后提交并推送，确认分发 HEAD 与 origin/master 一致且工作区干净。

此前“首版不包含正式同源分发”的范围由本次明确授权扩展；无需 DS/PIE，不修改生产数值、旧 Python 规则或无关资源。
