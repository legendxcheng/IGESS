# Fish 经济模型迁移 Handoff

更新时间：2026-08-02

项目范围：`projects/fish` 与 Fish 领域模拟代码

当前唯一进度源：[`RoadMap.md`](RoadMap.md)

## 当前结论

2026-08-02 的生产经济模型已经迁入 IGESS，并通过正式 smoke 与 1 天场景。
这次是对现有 Fish 模拟器的增量迁移，没有建立第二套模拟管线，也没有修改
人类维护的 Excel、Luban、生产 JSON 或生成 Lua。

当前资源流：

| 行为 | 消耗 | 权威字段 |
| --- | --- | --- |
| 鱼升级 | 材料 | 既有公式 |
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

- 正式 smoke：`20260802T020830293437Z-smoke`。
- 正式 1 天：`20260802T021144403218Z-day_1_growth`。
- 当前模型摘要：
  `sha256:82d5b37fd2ce1573ad45425b1722d57420c0bf9af835d23c303aaaa3350b6301`。
- 生产数据标记：`production_data=true`、`matches_production_data=true`，
  12 张表、340 行、无 override。
- 1 天期末：境界 4、杠铃 6、鱼雷 3、力量重生 3 次、垃圾佬转世 2 次。
- 旧对照：`20260727T050603893872Z-day_1_growth`，模型摘要
  `sha256:bb73e0247023e3a78e7f121ebd476294d0bd8af4d0dda78e5fa474b1cef2e9bb`，
  期末境界 6、杠铃 5、鱼雷 6、两类重生次数同为 `3 / 2`。

旧、新运行同时包含生产表与规则语义变化，不能把上述节奏差异归因给某一个
字段。事件账本可直接确认每次消费资源、余额前后值、字段来源和倍率来源。

自动化回归覆盖：

- 杠铃/鱼雷/突破的资源可支付判定、原子扣款和失败不改状态；
- 两类重生的旧倍率先结算、新倍率立即生效和保留/重置字段；
- 在线总时长一次结算与分段结算的推进等价；
- 奖励倍率不改变修炼/突破秒数；
- 离线暂停、加工不停、多境界跨越及 checkpoint 恢复；
- 三种突破画像策略只改变显式命令候选，不让状态机自动资助。

## 下一步

1. 用当前快照重跑 `week_1_growth` 与 `month_1_growth`，重新建立长期 KPI 和
   gate；旧版 `9 / 23 / 36` 不再代表当前模型。
2. 由 Fish 项目维护者统一 `cultivationSecondsToNextRealm` 与
   `breakthroughSecondsToNextRealm` 的 GDD、生成契约和游戏运行时命名，然后
   再决定 IGESS 是否需要同步改名。
3. 数值调整继续由人类修改并导出生产表；IGESS 只运行、比较和提出可归因建议。
