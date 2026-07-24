# IGESS Incremental Authoring Project

`economy.yaml` and `Datas/` describe this IGESS project's authoring shell and
the runtime input for a production-data active-throw smoke. They are not the
authority for Fish production values.
`luban_exports/` is generated from those local sources; do not edit generated
exports by hand.

Fish 的经济建模、RNG、玩家存档、专用模拟器接入与正式调参进度统一记录在 [RoadMap.md](RoadMap.md)。该文件是唯一进度源。

Fish 正式数值的唯一权威生产快照是 `E:\fish-oasis\igess_export`。正式表通过其中的 `python\schema.py` 加载同快照的 `json`；IGESS 只消费生成后的强类型表对象，并记录 JSON 与生成加载器哈希，不在本项目中维护手写业务字段解析器；机制测试可使用显式 fixture provider。

当前 `smoke` 会从生产 `tbtorpedo` 第一行初始化新档鱼雷，并用
`engine.active_throw.initial_strength` 初始化 `PlayerState` 力量。生产
`default` 玩家画像当前保留旧主动投掷循环；可选加权行为启用后，手动投掷完成时从 `PlayerState`
锁定力量和已选鱼雷，再调用 `resolve_throw()`。中奖鱼的 `tbfish.weight` 按整数
克写入鱼实例；鱼、废料、投掷统计和 `meta.revision` 在同一个状态迁移中
提交。运行会输出 `fish_throw_resolved` 标准事件并推进 checkpoint 的
`next_throw_id`，分段恢复不会重放已经结算的事件。每次投掷前先结算旧阵容
截至当前秒的金钱，新鱼入库后按
`baseMoneyPerSecond × 1.25^(level-1) × incomeMultiplier` 降序自动填满
鱼厅容量；同收益按 `instanceId` 升序决胜。鱼可用金钱升至最高 100 级，
从等级 `n` 升到 `n+1` 的价格为 `baseMoneyPerSecond × 1.5^(n-1)`，价格
不乘变异倍率；升级会按新收益重排阵容。timeline 输出当前金钱和鱼厅 CPS，
事件保存逐鱼公式 trace。

摸鱼厅使用生产 `tbfishhallupgrade` 的顺序行：当前 `upgradeLevel` 对应当前
容量和本次升级材料价格，存在下一行时才能升级；最后一行容量 30、
`upgradePrice=0` 是满级哨兵，不会产生免费升级。升级完成前先结算后台
金钱和材料，再原子扣除材料、提升等级和 `meta.revision`，容量立即生效，
并按 IGESS 的固定 `max_income` 模拟策略补齐/重排阵容。

杠铃使用生产 `tbbarbell`：`price` 严格消耗材料，
`strengthPerExercise / timeCost` 是装备后的在线每秒力量。当前生产 15 档
`timeCost` 均为 1 秒。只有正在装备的杠铃产出力量；库存 `count` 只表示持有
数量，不放大产出。合成会在结算旧装备截至当前秒的力量后，原子扣材料、增加
库存和 `meta.revision`，再按固定 `highest_strength_per_second` 策略自动装备
当前每秒力量最高的已拥有杠铃；领域层也保留显式换装命令。力量与鱼厅金钱、
垃圾佬材料使用同一生产结算锚点并进入 checkpoint。离线 50% 力量结算仍属于
Phase 8，当前实现仅覆盖在线时间。

力量重生使用生产 `tbstrengthrebirth` 的一基 ID：`completedCount=0` 时摸鱼厅
使用表外默认 `1×`，下一次重生读取 `id=completedCount+1` 的力量门槛，完成
第 `n` 次后使用 `id=n` 的摸鱼厅永久总倍率。重生命令先结算旧倍率截至当前秒
的全部后台产出，再只把当前力量归零；鱼、资源、鱼雷、杠铃、摸鱼厅和其他
永久进度均保留。

废料按 `trashId` 聚合，并由垃圾佬在后台自动加工。每份废料的
`baseDecomposeSeconds` 是基础工作量，每个真实秒按当前境界的
`decomposeSpeedMultiplier` 推进工作；材料按
`baseMaterialPerSecond × 已消费工作量 × 转世产出倍率` 连续增加。队列按
`trashId` 升序稳定处理，一次结算可以批量跨越多份废料；不足一秒的基础工作
进度保存在 checkpoint 的 `engine_runtime_state`，保证变速和分段恢复不丢失。
垃圾佬在在线时间内还会按当前境界的
`cultivationSecondsToNextRealm` 自动修炼，但首片只允许追赶至存档中的
`highestRealmId`。跨境界结算会先用旧境界速度处理到边界，再切换新速度；
前台行为中途 checkpoint 不会提前提交修炼。新境界瓶颈、资助突破和离线修炼
仍等待正式规则，不由模拟器猜测。

IGESS 另提供可选的玩家行为循环。玩家画像可以分别配置
`behavior_weights`、`behavior_durations` 和 `behavior_target_policies`；
Fish 当前前台行为为 `manual_throw`、`upgrade_fish`、
`upgrade_fish_hall`、`synthesize_barbell`、`strength_rebirth`、`idle`，
三类持续产出始终作为后台系统并行结算。
`upgrade_fish_hall` 是无目标行为，只在未满级且当前材料可支付时进入候选。
`synthesize_barbell` 必须显式使用 `random_affordable` 目标策略，并只从当前
未拥有且材料可支付的杠铃中选择，避免行为模拟反复合成不提高产出的副本。
`strength_rebirth` 也是无目标行为，只在当前力量达到下一张一基表行门槛时
进入候选。
行为选择、随机时长和目标选择使用独立稳定随机域，checkpoint 可保存进行中的
行为并在恢复时原样继续。生产画像的具体行为权重、持续时长和升级目标策略
尚未配置；机制测试使用显式 fixture，不能据此得出正式经济节奏结论。

IGESS 只模拟会影响数值体验的资源、概率、时间、产出、消耗、成长和策略。
图鉴等非数值子系统不进入模拟逻辑；为兼容正式存档而存在的对应字段只透传，
投掷结算不会读取或修改它们。

## Agent workflow

Work with an Agent to add one rule at a time. After every rule, inspect model status and any automatic smoke result before adding the next rule. Once the model is complete, run formal simulations and tune the same attributable source state.

## Commands

```powershell
igess model init --out projects/my-game
igess model status --project .
igess model apply --project . --change changes/next-rule.yaml
igess model simulate --project . --scenario smoke
```

## Artifacts

- `economy.yaml`: formal YAML rules and engine defaults.
- `Datas/`: formal Luban workbook rules.
- `luban_exports/`: generated runtime tables.
- `changes/`: attributable incremental change records and proposed changes.
- `runs/`: simulation run records and outputs.
- `reports/`: generated analysis reports.
