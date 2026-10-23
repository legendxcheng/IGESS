# Fish 源码模拟同步修复验证

日期：2026-10-23。状态：本机修复和 GameBalancer 0.5.19 交付验证完成，可使用当前游戏 Lua 规则及当前导表直接进行普通成长数值调优。本次按用户要求归档为本地 Git 提交，不推送远端。

## 修复

1. 保留当前 `E:/fish-oasis/master` 的全部业务更新，把之前仅在集成分支的 Codex、Guns、Eggs、Tides 宿主模块及 Host/CLI/SnapshotTables 接口迁入当前工作区。
2. 恢复源鱼蛋服务的可选确定性 RootSeed 注入及范围校验；默认游戏调用仍沿用原随机路径。
3. 修正宿主的神器购买候选：实际第四水域入水、寻宝兽解锁后才提供开放商品；关闭商品不进入候选，已经拥有的关闭商品仍能选择和投掷。报价缓存包含开放状态，避免解锁后沿用旧缓存。
4. 运行包从当前游戏源码生成，因此包含目前游戏的未开放材料回退、现有枪械装备和生产服务变更；没有退回 10 月 14 日游戏分支。
5. 在 IGESS README 与游戏 simulation README 中明确直接源码路径和冻结交付运行包的区别，避免再由一条路径的状态推断另一条路径。

用户此前确认只使用源码模拟；此次所有正式运行均为 `engine_id=fish_source`。IGESS 的 Python 调度、打包及报告代码不是旧 Python 经济模型，发布工具的通用回归中保留的旧模型单元测试不作为正式调优或比较基线。

## 已通过

- `model status --project projects/fish_source --json`：ready。
- IGESS 源码集成套件：57 passed，671.17 秒。覆盖正式运行、联合链路、鱼潮、枪、鱼蛋、图鉴及自然落点。
- 新增购买候选回归：1 passed；先复现未解锁时错误暴露 26 个候选，再验证修复、实际落点后的缓存刷新、选择及使用已有关闭神器。
- 游戏端七个 Lua 套件：图鉴、蛋、枪、库存分页、自然落点、鱼潮、满包阻塞蛋，全部通过。
- 游戏端三个公开 CLI 套件：24 passed，32.34 秒。
- 当前游戏 `throw_rules_contract_test.lua`、`torpedo_shop_visibility_test.lua`：通过。
- 当前生产 JSON 的文件名、SHA256、长度及修改时间在源码测试前后完全一致。

## 当前导表 1 天源码基线

- Run：`20261023T085205354150Z-day_1_growth`。
- 结果：formal / success；10 个 manifest 声明产物全部存在，网页和 checkpoint 已生成。
- [报告](../../projects/fish_source/runs/20261023T085205354150Z-day_1_growth/report/index.html)。
- 源代码摘要：`bdd62e9942cc8f8a46926a0d08c403d142d35e37f1606e9375cccb65ef2f28d9`。
- 导表摘要：`95f8e9ed15a259915bc3e9785930c2b5d660d55c9b79effc03b4003b277d4d0d`。
- 适配器总耗时约 20.76 秒，默认每天连续在线 7,200 秒。
- 首个正常图鉴完成：在线 3,098 秒；领枪：3,123 秒；装备：3,125 秒。此为当前输入的新基线，不与旧版本直接归因比较。

用户在检查与修复之间已更新生产导表；修复从 `production-before-repair.json` 记录的新快照起保持只读。此前审计的旧快照与本次快照不同，不能混为一次调参。

## GameBalancer 0.5.19

准备过程记录在 `prepare-release-0.5.19.log`。

- 完整发布回归：305 passed，9 deselected，752.86 秒。9 项为既有默认排除的旧 Python 后端外部数据测试。
- 本地 `E:/GameBalancer` 已生成 0.5.19，97 个交付文件；文件集合与 manifest 完全一致，逐文件 SHA256 一致，源码泄露检查通过。仅编译产物、Lua 运行包和版本清单改变；启动入口保持不变。
- `runtime.json.source_code_sha256` 与上面的当前游戏源码摘要一致。
- 真实工作台表单 smoke：`20261023T090740766609Z-smoke`，formal / success，报告 HTTP 200，`engine_id=fish_source`，工具版本 0.5.19。
- 真实工作台表单 1 天：`20261023T090829149077Z-day_1_growth`，formal / success，全程约 27 秒；timeline、events、source_progression、source_behavior 四份业务 JSON 与直接源码基线逐字节一致。报告、checkpoint、全部声明产物及输入指纹通过核验。
- 真实工作台表单 7 天：`20261023T090902644963Z-week_1_growth`，formal / success，全程 477.89 秒；报告 HTTP 200，checkpoint 与全部声明产物存在，源码/导表身份与 1 天相同，生产 JSON 未改动。
- 工作台保留运行于 `http://127.0.0.1:6248/`，确认仅监听回环地址。
- 浏览器工具拒绝自动打开该本地地址（未取得浏览器访问授权），未换用其他方式绕过；工作台表单验证通过本地 HTTP 流程执行，不能称为 Chrome 页面验收。
- 游戏源码修复提交：`01af823f691b7a2521fe37f311d879e54554c1ca`。IGESS 的回归/文档/证据与 GameBalancer 0.5.19 分别提交到对应仓库；未推送，不宣称员工已自动获得新版。
- 游戏原有生成表改动未纳入源码修复提交。运行包不含 `Script.Table` 数值模块；完整源树摘要包含本次构建时工作区生成表的字节，实际数值输入由单独记录的所选 JSON 摘要确定。不要将源码提交号单独当作完整运行输入身份。

本次未修改生产 Excel 或导表，未进行编辑器/DS/多人表现验证。普通成长画像仍沿用已有策略，鱼潮固定五蛋/120秒/六次换弹；没有新增付费卡购买、活动奖励领取等玩家行为。长期 30 天场景可用性需与此次实际运行覆盖分开说明。

## 直接使用

- 本次已启动工作台：[http://127.0.0.1:6248/](http://127.0.0.1:6248/)。该地址只对本机有效；进程退出后双击 `E:/GameBalancer/start.bat` 会启动新的本机地址。
- 本机导表目录：`E:/fish-oasis/igess_export/json`；执行策划可以在自己的电脑选择其正式导出的 JSON 目录。
- 选择 `day_1_growth` 做快速检查，选择 `week_1_growth` 做常规调优；更新数值并导出后，使用相同工具版本、场景和策略重跑比较。
- [已完成的 7 天报告](http://127.0.0.1:6248/reports/20261023T090902644963Z-week_1_growth/index.html)。
- 产物与核对结果：[workbench-results.json](workbench-results.json)、[candidate-audit-0.5.19.json](candidate-audit-0.5.19.json)。
- 原员工版本和历史结果均保留；0.5.19 尚未推送，员工不能通过 git pull 取得仅存在本机的提交。远端发布需另行授权。
