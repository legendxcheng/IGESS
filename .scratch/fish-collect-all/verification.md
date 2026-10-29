# 鱼厅金币全部领取策略

日期：2026-10-29。范围：IGESS 玩家策略，复用源 Lua `collect_slot`；生产表、源业务规则与 GameBalancer 发布均不在本次变更内。

## 缺陷与修复

原策略每次领取后重置全局间隔，稳定遍历反复命中持续产钱的首槽。正式入口三槽夹具复现：320 秒内只在第 1 秒和第 301 秒领取槽位 1，后两个槽位未领。

修复后批次按槽位编号固定本轮正余额、未被拒绝冷却阻塞的槽位，每槽源命令一次、占用 2 秒。默认周期 300 秒，从批次建立计时；本批完成前不补入新产出的槽位。新产出继续留在槽位，下轮领取。源拒绝记事件并消费该次尝试的 2 秒，剩余槽位继续；执行前已经清空、移除或阻塞的槽位直接跳过。

`pending_collect_slots` 保留未访问槽位；提交后移除当前槽，`pending_action` 独立保留耗时。运行截止不等于下线，恢复不会再次提交已访问槽位。实际下线／鱼潮前不足 2 秒时不开始该槽，待下一次在线／鱼潮结束继续。

正式三槽夹具预期两轮为 `(1秒, 槽1)、(3秒, 槽2)、(5秒, 槽3)` 和 `(301秒, 槽1)、(303秒, 槽2)、(305秒, 槽3)`。源码指纹变化沿用原拒绝旧 checkpoint 契约。

## 验证入口

```powershell
.tmp/py311-venv/Scripts/python.exe -m pytest tests/test_fish_source_collection.py -q -p no:cacheprovider
.tmp/py311-venv/Scripts/python.exe -m pytest tests/test_fish_source_formal.py tests/test_fish_source_tides.py tests/test_fish_source_joint.py tests/test_fish_source_natural_landing.py tests/test_fish_source_income.py -q -p no:cacheprovider
.tmp/py311-venv/Scripts/python.exe -m igess.cli model status --project projects/fish_source
.tmp/py311-venv/Scripts/python.exe -m igess.cli model simulate --project projects/fish_source --scenario smoke --json
```

定向测试覆盖两个正常周期、逐笔钱包与生产核算、7 个动作前／中／后截断点、源拒绝注入，以及实际下线／鱼潮后继续领取。恢复每次重建独立 Lua 进程，比较完整源 replay 历史、快照摘要、行为状态和最终采样。为逐字比较源历史，夹具每秒采样，使连续／分段运行的时间推进边界一致；初版较疏采样在截断点多出一次 `advance`，领取事件与业务终态一致，但不能宣称原始历史字节一致。

最终定向回归：**11 passed**，无跳过。证据夹具产物位于 `.tmp/collect-final/`。

已有正式入口、鱼潮、联合恢复、自然落点与收入回归：**52 passed**，无跳过，夹具产物位于 `.tmp/collect-regression/`。合计本次相关回归 **63 passed**；未执行整个仓库测试集。`git diff --check` 和受影响文档链接检查通过，README、RoadMap、`fish_sim` 及代码导航已同步。

## 当前生产输入 smoke

- 就绪检查：`Model is ready`。
- 正式运行：`projects/fish_source/runs/20261029T122050967671Z-smoke`，登记 `success`，标准产物、成长／行为产物、checkpoint 和 Web 报告齐全。
- Lua 源码：`16c3bdf9d6323f7b2a10e6848c1ffe6a8e7bf36abc2f6fd567658a77825d8f3c`。
- 所选导表：`a2827adb6a3c59edf51599189eb423fbfa245bb574cfdac9103c4bf6e9d106f2`。
- IGESS 适配器：`43550813faccbc7c69b5110b1711e229b0629d17cf4a9cb907dd5495d1222fc5`。

前两项与交接原运行 `20261029T115415596793Z-day_1_growth` 相同；适配器身份已变化。清单新增 `collect_policy=stable_slot_batch_v1`、`collect_slot_seconds=2`、`collect_interval_basis=batch_start`。旧报告保持原样，需要新建模拟观察新的养成节奏。

首日／整周数值调优长跑由用户执行；本次受控跨日测试每天仅在线 4 秒，用于验证下线边界。正式 smoke 成功不代表已验证新策略首日／整周经济表现，也不代表 GameBalancer 已更新。
