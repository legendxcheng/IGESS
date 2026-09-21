# Fish 经济模型迁移 Handoff

更新时间：2026-09-21

项目范围：`projects/fish` 与 Fish 领域模拟代码

当前唯一进度源：[`RoadMap.md`](RoadMap.md)

## 当前结论

已支持生产杠铃 `timeCost=0.5`。用户选择保留每段 60 秒锻炼行为，按单次耗时
与单次力量累计收益，每段对应 120 次；全局调度和 checkpoint 仍使用整数秒。
时间字段读取保留毫秒精度。322 项组合回归及当前生产 1d 正式验证通过，
来源、边界与报告见 [半秒杠铃验证](../../.scratch/fish-barbell-subsecond/verification.md)。

普通鱼卖出材料已进入正式模拟，沿用当前金币升级。两个画像保留上阵鱼与品质前 X，
每累计在线五分钟整理一次、耗时三秒；重生和立即突破先执行，其他普通行为后执行。
不返升级金币、不乘加工或画像倍率；临近下线顺延，周期与冻结批次支持存档恢复。
当前 smoke/1d/7d/30d 基线见 [卖鱼材料基线](reports/fish-sale-material-baseline.md)，
测试、账本核验与已知边界见 [出售验证](../../.scratch/fish-sale-material/verification.md)。
上一份金币升级报告保留为历史参考。

普通鱼金币升级、前 X 品质与上阵交集策略、杠铃攒钱估计已迁入正式模拟。
默认与付费画像都按最低等级培养交集鱼，单次一级、三秒、权重 1；未上阵鱼不追赶，
选定鱼不可支付时不转投。神兽按生产分类隔离，存档含神兽时明确拒绝模拟。
具体策略见 [README.md](README.md)，确认规格见
[spec.md](../../.scratch/fish-coin-upgrade/spec.md)。

当前资源流：

| 行为 | 消耗 | 权威字段 |
| --- | --- | --- |
| 普通鱼升级 | 金币 | `P0 × 1.5^(L-1)`，P0 含变异 |
| 摸鱼厅升级 | 材料 | `FishHallUpgrade.upgradePrice` |
| 鱼雷购买 | 材料 | `Torpedo.price` |
| 杠铃合成 | 金钱 | `Barbell.price` |
| 垃圾佬突破 | 材料 | `TrashManRealm.materialRequireToNextRealm` |

当前永久倍率：

- 力量重生完成第 `n` 次后读取
  `StrengthRebirth[id=n].materialOutputMultiplier`，只提高垃圾加工材料产出。
- 垃圾佬转世完成第 `n` 次后读取
  `TrashManRebirth[id=n].fishHallOutputMultiplier`，只提高摸鱼厅金钱产出。
- 两类表均保持 `completedCount=0` 使用表外默认 `1×` 的一基映射。

## 境界推进与策略边界

正式运行严格使用同批次
`E:\fish-oasis\igess_export\python\schema.py` 和 `json`。当前生成契约及 JSON
中的推进字段是 `breakthroughSecondsToNextRealm`；IGESS 不回退读取旧字段。
`E:\fish-oasis` 内仍有文字 GDD/领域 Lua 使用
`cultivationSecondsToNextRealm`，这是外部源一致性问题，不应在 IGESS 中用兼容
分支掩盖。

存档仍只保存：

- `realmId`、`highestRealmId`、`trainingProgressSeconds`；
- `breakthrough.active / targetRealmId / progressSeconds`。

突破材料在显式资助命令开始时原子扣除一次，不存在累计境界材料进度。
历史境界追赶和已资助突破均按未缩放在线墙钟推进，可在一次结算中跨越多个
境界；离线时暂停，垃圾加工仍继续。画像收益倍率只改变入账，不改变推进秒数。

玩家策略与状态机分离：

- `immediate`：可支付时只保留资助突破候选；生产默认使用此策略。
- `weighted_delay`：资助命令与其他候选一起参与权重选择。
- `preserve_material`：当前不把资助命令放入候选池。

## 验证证据

当前 smoke、1d、7d、30d 正式运行、出售账本与连带成长结论见
[卖鱼材料基线](reports/fish-sale-material-baseline.md)。四次运行使用同一生产快照与模型摘要，
保留完整来源哈希。单鱼升级及出售不计入系统永久进展。

卖鱼版本全量回归 1452 passed、8 skipped、16 deselected；随后扩展的出售专用测试 27 passed。
恢复、账本、正式工作流及类型检查记录见
[verification.md](../../.scratch/fish-sale-material/verification.md)。
当前唯一进度与下一步仍以 [RoadMap.md](RoadMap.md) 为准。

`model status` 的十 tick 通用探针尚不支持 Fish，仍报 `smoke_failed`；正式
`model simulate` 的引擎派发、登记、标准产物与报告均正常。

历史 2026-08-02 结果及旧字段迁移记录保留在 RoadMap，不能用其差异单独归因金币升级。
