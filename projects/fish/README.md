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
鱼厅容量；同收益按 `instanceId` 升序决胜。鱼可消耗材料升至最高 100 级，
从等级 `n` 升到 `n+1` 的价格为 `baseMoneyPerSecond × 1.5^(n-1)`，价格
不乘变异倍率；升级会按新收益重排阵容。timeline 输出当前金钱和鱼厅 CPS，
事件保存逐鱼公式 trace。

摸鱼厅使用生产 `tbfishhallupgrade` 的顺序行：当前 `upgradeLevel` 对应当前
容量和本次升级材料价格，存在下一行时才能升级；最后一行容量 30、
`upgradePrice=0` 是满级哨兵，不会产生免费升级。升级完成前先结算后台
金钱和材料，再原子扣除材料、提升等级和 `meta.revision`，容量立即生效，
并按 IGESS 的固定 `max_income` 模拟策略补齐/重排阵容。

杠铃使用生产 `tbbarbell`：`price` 严格消耗材料，
`strengthPerExercise / timeCost` 是主动锻炼时的在线每秒力量。当前生产 15 档
`timeCost` 均为 1 秒。只有当前前台行为为 `exercise_barbell` 时，正在装备的
杠铃才产出力量；库存 `count` 只表示持有数量，不放大产出。合成原子扣材料、
增加库存和 `meta.revision`，再按固定 `highest_strength_per_second` 策略自动
装备当前每秒力量最高的已拥有杠铃；合成、炸鱼等其他前台行为不同时产出力量，
领域层也保留显式换装命令。离线期间杠铃力量固定为零。

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
`cultivationSecondsToNextRealm` 修炼。转世后低于 `highestRealmId` 的境界免费
在线追赶；达到历史最高境界后，`fund_trash_man_breakthrough` 按当前境界行的
`moneyRequireToNextRealm` 扣金钱并开始付费突破。突破首版只累计在线时间，
离线暂停，闭关期间仍按旧境界速度加工废料；完成边界后才更新当前/历史最高
境界并启用新速度。前台行为中途 checkpoint 不会提前提交或重复扣款。生产
价格 1～59 号严格递增、60 号为 `0` 满档哨兵；分解倍率采用
`1 + 1.25 × (境界 ID - 1)`，用于补偿提价后较慢的境界节奏。

IGESS 另提供可选的玩家行为循环。玩家画像可以分别配置
`behavior_weights`、`behavior_durations` 和 `behavior_target_policies`；
Fish 当前前台行为为 `manual_throw`、`upgrade_fish`、
`upgrade_fish_hall`、`purchase_torpedo`、`synthesize_barbell`、
`exercise_barbell`、`fund_trash_man_breakthrough`、`strength_rebirth`、
`trash_man_rebirth`、`idle`。
其中 `fund_trash_man_breakthrough` 是固定 `1` 秒、权重 `100` 的无目标行为，
只在当前境界等于历史最高境界、没有进行中的突破且金钱足够时进入候选。
每次只允许一个前台行为；
摸鱼厅金钱和垃圾佬加工属于后台系统，杠铃锻炼不是后台系统。
`upgrade_fish_hall` 是无目标行为，只在未满级且当前材料可支付时进入候选。
生产 `upgrade_fish` 使用 `cheapest_below_material_tenth` 目标策略：从全部未满级
鱼中选择升级价格最低的一条，同价按 `instanceId` 升序决胜；只有该最低价格
严格低于当前材料的 `1/10` 时才进入候选。鱼升级价格从材料余额扣除。
`synthesize_barbell` 必须显式使用 `random_affordable` 目标策略，并只从当前
未拥有且材料可支付的杠铃中选择，避免行为模拟反复合成不提高产出的副本。
`purchase_torpedo` 必须使用 `highest_affordable`：只从未拥有、比当前装备
更强且金钱可支付的鱼雷中选择最高档，购买后自动装备。该行为不读取当前力量
或历史最高力量，成长时点完全由 `tbtorpedo.price` 控制。
`exercise_barbell` 仅在拥有有效已装备杠铃时进入候选，执行期间按装备速度
持续增加力量，并与炸鱼、升级、合成和重生互斥。
`strength_rebirth` 也是无目标行为，只在当前力量达到下一张一基表行门槛时
进入候选。
`trash_man_rebirth` 同样无目标；`0` 次使用表外 `1×`，第 `n` 次对应
`tbtrashmanrebirth.id=n`，只在当前境界达到下一行 `realmRequirement`
且没有进行中的突破时进入候选。完成后当前境界和本境界修炼进度回到初始值，
历史最高境界保留，新的材料总倍率立即生效。
行为选择、随机时长和目标选择使用独立稳定随机域，checkpoint 可保存进行中的
行为并在恢复时原样继续。默认画像的 `session_pattern.daily_online_seconds`
为 `7200`，即每天从模拟日开始连续在线 2 小时、随后离线 22 小时，到下一模拟日重新
上线。离线期间不调度前台行为，摸鱼厅金钱和废料加工按在线的 `50%` 结算，
杠铃力量为 `0%`，垃圾佬修炼不推进。默认 `manual_throw` 与
`exercise_barbell` 使用基准权重 `1`，低优先级 `upgrade_fish` 使用权重
`0.1`；`synthesize_barbell` 与 `upgrade_fish_hall` 使用高优先级权重
`100`；`purchase_torpedo` 同样使用权重 `100` 和固定 `1` 秒。两类重生也
配置为固定 `1` 秒行为；只要任一种达到下一档要求，候选池
就只保留当前可执行的重生，绝对优先于所有普通前台行为。若两种同时满足，则
稳定选择一种并在下一轮立即执行另一种。杠铃合成使用 `random_affordable`，鱼升级使用
`cheapest_below_material_tenth`；没有可执行目标时相应行为自动过滤。未拥有杠铃
时训练行为也会自动过滤。生产 `day_1_growth` 与 `week_1_growth` 已完成正式
24h/7d 基线；垃圾佬突破平衡后的系统级永久进展为 `9 / 23`，同生产输入的
30d 领域运行结果为 `36`，均通过 `8..12 / 16..24 / 32..48` gate。周场景
保留全部行为事件以及重生/鱼雷购买/境界突破的完整 trace，但对
其他普通行为使用 `compact_event_details` 去除重复的大公式明细。重生直接
产出与重置进度恢复结论见
[`reports/rebirth-long-term-baseline.md`](reports/rebirth-long-term-baseline.md)。
正式 Fish run 还会生成 `luck_progression.json/csv` 和
`behavior_progression.json/csv`：前者按累计在线时间采样 Strength、
FishLuck、TrashLuck 的当前值、历史峰值、变化速度、重生标记和停滞时间；
后者只统计跨鱼保留或抬高长期能力上限的永久进展，并明确排除单鱼升级和临时
效果。捕获只有在事件记录的最佳鱼厅 CPS 确实提高时才计入。静态 HTML 会显示
双 Luck/Strength 曲线、永久进展触发密度、归一化变化幅度和事件明细。最新
24h/7d 报表基线与结论见
[`reports/trash-man-breakthrough-balance.md`](reports/trash-man-breakthrough-balance.md)；
调价前报表基线保留在
[`reports/progression-report-baseline.md`](reports/progression-report-baseline.md)。
包含 FishLuck 机会成本的完整反事实经济回本仍需 Phase 9 的同 RNG 禁用重生分叉，
不能直接用永久产出立即生效替代。

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
igess model simulate --project projects/fish --scenario day_1_growth
igess model simulate --project projects/fish --scenario week_1_growth
igess model simulate --project projects/fish --scenario month_1_growth
```

## Artifacts

- `economy.yaml`: formal YAML rules and engine defaults.
- `Datas/`: formal Luban workbook rules.
- `luban_exports/`: generated runtime tables.
- `changes/`: attributable incremental change records and proposed changes.
- `runs/`: simulation run records and outputs.
- `reports/`: generated analysis reports.
- `runs/*/output/luck_progression.{json,csv}`: 核心强度与双 Luck 机器可读报表。
- `runs/*/output/behavior_progression.{json,csv}`: 永久养成事件与间隔报表。
