# Fish 源码模拟同步检查

检查时间：2026-10-23。修正结论：GameBalancer 已接入源码模拟；本地直接连接游戏 master 的 IGESS 路径缺少宿主集成。两条路径的版本不同，不能把后者的失败推断为员工未使用源码模拟。

## 补充核实：GameBalancer 已发布并验证源码模拟

用户指出员工已经使用 GameBalancer 调数值后，进一步检查了实际交付仓库、打包运行时和本机发布验收记录：

- `E:/GameBalancer/operator-manifest.json`：版本 `0.5.18`，`engine_id=fish_source`；发布提交 `62c3aa5b8ead76f4dead6887da5dcc36f388567b`。
- `bundle/economy.yaml`：源码根指向随包 `bundle/fish-runtime`，数值根为用户选择的 JSON 目录。它不读取当前 `E:/fish-oasis/master` 的 Lua 文件。
- `bundle/fish-runtime/runtime.json`：由 10 月 14 日源码提交 `2dc68743cab787f922705c042229e1d257d8db70` 对应源树构建，源哈希 `33b5f9d5b66e1da56280079890aa75780b1051bc1740411c83b17591c392bd2c`；包含 Codex、Eggs、Guns、Tides 模块。
- 本次直接执行随包 lua55.exe + runtime.luac 查询能力：之前本地 master 缺少的八个操作和三个能力版本全部存在。
- 本机历史 `20261014T095621949896Z-smoke/run_status.json` 实际为 `formal / success`、`engine_id=fish_source`。运行清单中的 `packaged_source_code_sha256` 与当前交付包吻合。
- 发布验收记录：`E:/IGESS/.tmp/gamebalancer-0.5.18-evidence/release.md`，记录 304 项验证通过及真实工作台 smoke 成功。

因此员工“已经使用 GameBalancer 调数值”的说法与本次证据不冲突。尚未取得员工电脑的工具版本、所选 JSON 和具体运行清单，不能把本机发布 smoke 当成员工的调优记录。

仍存在的同步问题是 **10 月 14 日冻结的运行时代码与今天游戏 master 的业务规则有差异**。例如当前 `ThrowOutcomeResolver.lua` 已增加“抽中未开放垃圾时回退至开放的 ID 1 垃圾”的处理，而发布基准源码没有该段。更新 JSON 本身不会更新打包的 Lua 规则。

后续应以员工实际使用的 GameBalancer 版本及输入清单为起点，核对游戏规则变更并更新源码运行包；不能将员工已有结果一概判为无效，也不能假定交付包会实时跟随游戏源码。

下文是此前对“本机 IGESS 直接加载当前游戏 master”及本机导表的检查，其失败范围仅限该路径。

用户确认后续只使用 `projects/fish_source` 的游戏 Lua 源码模拟；旧 `projects/fish` Python 业务模型不再使用，也不作为比较基线。本次 status、smoke 和能力查询均使用源码后端。

## 当前连接

- IGESS 配置：`projects/fish_source/economy.yaml`，`engine_id=fish_source`。
- 游戏源码：`E:/fish-oasis`，当前分支 `master`，HEAD `321fb66e2359ef3629411dc5b17be48c9edb2bca`。
- 模拟输入：`E:/fish-oasis/igess_export/json`。
- Lua 实测版本：5.5；协议版本：2。
- 本次核对本地工作区，没有核验远端、部署版本或实际编辑器运行。

## 阻塞：源码宿主集成不在当前游戏分支

10 月 14 日验收记录指向的游戏合并提交 `2dc68743cab787f922705c042229e1d257d8db70` 仍在 `feature/fish-source-unlocks-and-tides`，当前 `master` 不包含该提交。两者共同祖先为 `199c8abe6730cf0f681cc9a78743af52e70f192f`。

当前游戏分支不存在此前集成增加的四个文件：`simulation/Codex.lua`、`Eggs.lua`、`Guns.lua`、`Tides.lua`；Host、SnapshotTables、CLI 的对应接入也未包含在当前分支中。这里是两条分支的差异，不能据此说这些模块曾从 master 删除。

实测能力查询缺少八个操作：

`claim_fish_reward`、`claim_gun_reward`、`complete_tide`、`equip_gun`、`grant_random_egg`、`query_codex`、`settle_eggs`、`start_tide`。

另外未声明 IGESS 要求的 `tideScheduleVersion=1`、`naturalLandingVersion=1`、`inventoryProjectionVersion=1`。

验证结果：

1. `igess model status --project projects/fish_source --json`：失败，`smoke_failed`，发生在 build 阶段。
2. `igess model simulate --project projects/fish_source --scenario smoke --json`：失败，`fish_source_capability_missing`，发生在 prepare 阶段；返回上述八个操作和三个能力版本，不曾完成模拟或生成成功报告。
3. smoke 诊断：`projects/fish_source/.igess/diagnostics/attempt-9839e064dbeb4af5a5dbb78f1392efba.json`。

## 数据：游戏 Lua 与模拟 JSON 一致，但两者落后于 Excel

通过游戏现有 Luban 配置把当前 Excel **仅导出到本检查目录**，没有运行会覆盖生产目录的 fishexport.bat，也没有修改生产 Excel、JSON 或 Lua。

临时导出通过生成的 Python schema 校验：28 张表、1,881 行。对比按表的真实主键进行，保留 BigNumber 的字符串系数和 scale，忽略 Lua nil 与 JSON null 的表示差异。

| 比较 | 结果 |
| --- | --- |
| 当前生产 JSON 与游戏生成 Lua | 28 张表内容一致 |
| 当前生产 JSON 与当前 Excel 临时导出 | 26 张一致，2 张有差异 |
| 游戏生成 Lua 与当前 Excel 临时导出 | 同样只有这 2 张有差异 |

差异明细：

- `tbtrash`：40 条记录的 `Denominator` 均有变化，共 52 个底层 digits/scale 字段差异。例如 ID 1 的系数由 2 变为 3。概率阈值的改变会影响废料抽取与材料成长，正式调优前应由策划确认并导出。
- `tbitemgm`：ID `8310009` 的 `description`，现有导出为“获得双倍变异鱼运气特权”，当前 Excel 导出为“我十几年”。这是文本差异，需要策划确认是否为误改。

以上旧值指当前游戏与模拟实际消费的导出值，新值指当前 Excel 临时导出值；没有将临时导出替换为正式输入。

## 同源模拟的范围

源码后端直接运行游戏业务服务，但依然需要宿主适配和玩家行为策略。近期游戏增加的月/周/终身卡、在线循环奖励和资源包使用等，不能仅因直接加载源码就视为已进入调优行为循环；当前 IGESS 默认行为配置没有这些操作。

已有验收范围为普通成长、图鉴、枪、自然落点、寻宝兽、鱼蛋和鱼潮。鱼潮仍使用已声明的近似：固定 5 蛋、120 秒、6 次源换弹；不模拟实际命中或多人竞争。付费画像中的假设倍率被源码后端拒绝，不能作为真实付费链模拟。

因此接入缺失接口后，仍需根据本轮调优范围核验新增经济系统的覆盖。10 月 14 日的既有报告只描述当时输入，不作为当前源码/导表版本的比较基线。

## 建议处理顺序

1. 将已经验收的源码宿主集成迁入当前游戏分支，结合近期业务服务变化解决兼容问题；不把源码路径切回旧功能分支来冒充当前游戏。
2. 策划确认垃圾概率和道具描述的 Excel 改动，再通过正式流程导出，保持游戏 Lua 与模拟 JSON 同步。
3. 通过源码后端 status、smoke、关键链路回归后建立当前版本的 1 天基线；确认后再跑 7 天和 30 天。
4. 若本轮包含付费/活动收益，先补明确的源码操作与玩家策略，再建立对应基线。

本次仅完成同步检查，未实施迁移或数值修改，未跑长期模拟，未做编辑器/DS 验证。

## 证据

- [完整机器核对结果](audit.json)
- [model status 结果](model-status.json)
- [可重跑核对脚本](audit.py)
- Excel 临时导出：`fresh-json/`（仅本机保留，不纳入 Git；逐字段差异已记录在 audit.json）。
- 历史验收依据：`../../.scratch/fish-source-unlocks-and-tides/verification.md`。

当前源码 SHA256：`75dff59b3d0721bfb787dcecd7ba03b8ae5f87df6bc05c999e58c778f8e3b374`。

当前生产 JSON SHA256：`5d88fffd0727d1f5b5010162e9aa72c49348c1a31dcf20f6d4476c2a803b9922`。
