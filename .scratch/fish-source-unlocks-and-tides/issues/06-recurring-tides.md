# 06: 连续鱼潮与每日在线安排

**What to build:** 正式成长策略按源鱼潮间隔持续参与，正确处理开场、在线窗口、动作边界、离线错过和运行恢复，逐场结果可解释。

**Blocked by:** 05

Status: resolved

本票执行《Fish 同源模拟：图鉴奖励、寻宝兽开放与鱼潮》规格；范围与边界以父规格为准。实现前在独立工作树确认基于当前集成分支，使用 tdd 技能；测试边界已获用户确认，无需再次询问。

- [x] 以固定且记录的房间原点按源绝对时间分槽，离线不冻结时钟、重连不重置、不补发，每场至多参与一次，仅开场边界入场。
- [x] 计划下线剩余不足 120 秒跳过；场景截断与 checkpoint 不等于玩家下线，可保留进行中的鱼潮。
- [x] 调度器避免普通动作非法跨开场；锻炼可源结算后停止，已提交投掷不可回滚，无法合法结束记录跳过。
- [x] 同秒按 spec 顺序推进后台/到期事务、结束已有动作、判定鱼潮、选择普通动作；下线边界不新开动作。
- [x] 参数、房间原点、落点/领取策略参与运行归因，能力缺失或非法配置在正式运行前诊断。
- [x] 报告逐场参与/跳过、原因、累计在线耗时、蛋数、孵化数、换弹费用；不同采样间隔不改变业务结果。
- [x] 跨日、119/120 秒、开场前后与多场 checkpoint 通过公开边界红绿验证；快速与逐秒推进等价。
- [x] 提交前合并集成分支，记录双仓提交和测试证据。

## Comments


### 实施证据（待 merger 复核后关闭）

- 双仓独立 worktree 基于集成分支 IGESS `03c03b5` / fish-oasis `801adee7`；实施前读取 implement-spec、tdd、父规格、ADR 与协调说明。提交前双仓 `git merge feature/fish-source-unlocks-and-tides` 均为 Already up to date。
- 代码提交：IGESS `46bc83f83deca70e1df012eb14621eaf4f85803c`；fish-oasis `6e5cd81d9ebb5c5cb7e79bc16fbaf3f29d49da56`。
- 红绿证据：正式短周期场景最初没有场次；已知30秒投掷被20秒开场截短；不同采样使图鉴孵化观察150/151秒漂移；非法小数周期运行成功；正式 until_seconds 尚无入口。对应测试先失败，逐项补齐后通过。
- 实现源周期绝对槽、固定room_origin、119/120秒下线、离线逐场跳过、合法60秒周期中的busy场、同秒结束再入场；普通动作/锻炼/落地后剩余占用均可恢复。移除临时单场调度入口。
- 正式入口扩展 `--until-seconds` → AuthoringService → PreparedRun/executor → source adapter；截止属于执行范围，不改变模型身份。非法范围/不支持后端清晰拒绝，恢复不能倒退。公开正式接口实际分段60→120→179→240→361，最终累计状态与连续一致，各段命令拼接与连续一致。
- 验证使用显式 `PYTHONPATH=<本worktree>/src`、`FISH_SOURCE_ROOT=<配对source>`。69个不重复Python回归用例已通过：首轮组合65通过、1个旧CLI帮助参数集合失败，更新参数契约后CLI全26通过；另2个普通投掷/锻炼真实恢复通过。最后缩小鱼潮checkpoint观察游标后，5个受影响的单场/多场/采样/短周期/多次恢复用例再次全通过。
- Source：`lua55 tests/simulation_tides_test.lua`、`lua55 tests/simulation_eggs_test.lua` 全通过；`pytest tests/simulation_cli_test.py` 9通过，含源周期改变的直接CLI checkpoint拒绝。`git diff --check` 通过。报告JS以正式bun命令重建。
- 当前生产导表的真实CLI证据：`projects/fish_source/runs/20261014T054939850067Z-smoke`（截止6秒），`20261014T054945676310Z-smoke`（同checkpoint继续到10秒），两次均生成成功状态、report/index.html、标准产物与final_checkpoint；相同模型指纹 `sha256:73f3afc16fdfd56d3005e13fbcff10d95e539f7197b7df47f23fb98e321b9e51`。不以此短跑宣称生产已开放鱼潮。
- 完整逐场事实保留在事件/报告，checkpoint鱼潮观察仅保留最近源场次游标，避免累计复制完整费用回执。报告增加开场墙钟、累计在线时点、入包及本段孵化数；恢复页明示本段与累计字段区别。
- 后续07边界：早期生命周期首次时点完整恢复展示（旧GunMilestones只保存seen）、从离线段恢复的报告在线区间核查，以及库存分页/大数/长场景基线；详见仓外 `E:/IGESS-worktrees/integration-notes/final-validation.md`。生产JSON、Excel及生成Lua数据未改，不启动Editor/DS，不发布。

## Answer

已集成源绝对周期鱼潮、每日在线边界与动作恢复；正式 API / CLI 分段截止贯穿执行链且不改变模型身份，报告区分本段事件与累计资产，临时单场配置已移除。

- 源项目集成合并：55aad123be4ae5d6303b6fe215d0fd628cc483e5。
- IGESS 集成合并：92a0008f74a39e4d91576e6c5a4ae474b2885d52。
- 集成后验证：simulation_tides_test、simulation_eggs_test 通过；源 CLI pytest 9 项通过，包含周期输入变化的恢复拒绝。
- Python 连续鱼潮、自然落点、formal_run、authoring_cli 组合 62 项通过（289.78 秒）；官方 bun build 重建生产 JS 无差异，通用及源报告 23 项通过。
- 无合并冲突，未改生产导表和原有无关状态；库存精度、历史正式 fixture 迁移与长期基线留 ticket 07 验证。
