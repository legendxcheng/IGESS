# Fish 数值优化 Handoff

更新时间：2026-07-25

项目范围：`projects/fish` 与 Fish 领域模拟代码

当前唯一进度源：[`RoadMap.md`](RoadMap.md)

> 本文是下一轮“专门优化数值”的接手快照，集中记录产品目标、指标口径、
> 当前生产基线和实施顺序。进度状态仍以 `RoadMap.md` 为准。
>
> 当前工作区包含尚未提交的 Fish 长时模拟、性能优化、测试和文档改动。
> 接手时先执行 `git status`，不要清理或覆盖不属于自己的改动。

## 0. 2026-07-25 双 Luck 纯价格平衡更新

人类已确认：`FishLuck` 与 `TrashLuck` 应保持绝对值大致同步，并明确拒绝
“历史最高力量门槛”。本轮已经按纯价格方案完成实现和正式重跑：

- 新增 `purchase_torpedo` 互斥前台行为，生产权重 `100`、时长 `1s`、
  目标策略 `highest_affordable`。
- 购买判定只读取未拥有、比当前装备强、金钱可支付三个条件；不读取当前力量
  或历史最高力量。
- 成功购买原子扣除金钱、加入拥有列表并自动装备，输出
  `torpedo_purchased` 事件及价格、现金、power、TrashLuck
  before/after/delta。
- 事件自动进入 `luck_progression` 与 `behavior_progression` 两份一等报表。
- 2～11 号鱼雷价格已经在权威生产表
  `E:\fish-oasis\igess_export\json\tbtorpedo.json` 调整；12 号以后未改。

最新正式基线：

- 24h：`20260725T040202603439Z-day_1_growth`
- 7d：`20260725T040259487026Z-week_1_growth`
- 模型摘要：
  `sha256:66017a648f3ccce9ddb100a6e14e6dd54c0ee9e85177172e6859195c9ea42674`
- 结果说明：[`reports/torpedo-price-balance.md`](reports/torpedo-price-balance.md)
- HTML：
  [`runs/20260725T040259487026Z-week_1_growth/report/index.html`](runs/20260725T040259487026Z-week_1_growth/report/index.html)

7 天结果：

- 8 次鱼雷购买分别落在第 1 天三次，以及第 2、3、4、5、7 天各一次；没有
  同秒或紧邻连续跳档，首日三次购买分别间隔 `1,159s / 4,883s`。
- 每日 `FishLuckPeak / TrashLuckPeak` 的最大相对误差为 `14.83%`；
  第 6、7 天误差仅 `0.72% / 0.11%`。
- 系统级永久进展由旧基线 7 次增加到 15 次，最大累计在线空窗由
  `23,044s` 降至 `14,330s`，尾部空窗由 `21,529s` 降至 `7,199s`。
- 残余误差主要来自鱼雷 power 映射档位本身较粗；纯价格只能移动触发时点，
  无法在 `13→19.0209`、`20→28.7493` 之间生成新的 TrashLuck。

当前验证：

```text
Fish 全量回归        118 passed, 3 deselected
igess model status   Model is ready
24h / 7d 正式 run    passed
购买事件字段审计      8/8 complete
```

下一轮优先验证 10、11 号鱼雷的长期价格时点，并决定是否接受中段约 15% 的
档位误差；不要重新加入力量门槛。

## 0.1 2026-07-25 报表交付更新（调价前历史）

本文原定的最小交付已经完成：

- 正式 Fish run 输出 `luck_progression.json/csv`。
- 正式 Fish run 输出 `behavior_progression.json/csv`。
- 两组报表均已登记 `run_manifest.json` 并进入静态 HTML。
- 投掷事件记录最佳鱼厅 CPS before/after/delta、阵容是否改变和是否属于永久
  进展；单鱼升级仍明确排除。
- Strength 曲线使用存档四位有效数字规范化后的结算值，最终值与 checkpoint
  一致。
- 新增确定性、口径和 7 天基线测试。

当时报表基线（已由上面的调价基线取代）：

- 24h：`20260725T021336992137Z-day_1_growth`
- 7d：`20260725T021442047474Z-week_1_growth`
- 说明：[`reports/progression-report-baseline.md`](reports/progression-report-baseline.md)
- HTML：
  [`runs/20260725T021442047474Z-week_1_growth/report/index.html`](runs/20260725T021442047474Z-week_1_growth/report/index.html)

7d 新报表同时给出两层口径：

- 全部永久进展 94 次，其中 87 次是实际提高最佳鱼厅 CPS 的捕获；最大间隔
  `6256s`，尾部空窗 `3477s`。
- 排除最佳鱼厅捕获后的系统级进展仍为 7 次；最大间隔 `23044s`
  （`6h24m04s`），尾部空窗 `21529s`，7 个完整在线场次中有 5 个没有系统
  进展。
- FishLuck 最终/峰值 `29.965664`；TrashLuck 在 50,400 秒累计在线时间内
  始终为 `3`。

两份报表已经进入本轮调价实用阶段；当前仍待将指标接入
`compare / gate / scan`。

## 1. 下一轮目标

下一轮不再优先扩展通用经济报表，而是围绕两类直接影响留存的 Fish 指标开展
数值优化：

1. **长期提升行为的间隔和密度**
   - 前期持续给玩家可感知的成长反馈，避免长时间没有提升。
   - 后期允许间隔适度放宽，但必须保持最低提升密度。
   - 不允许用高频但临时的操作掩盖长期成长不足。
2. **核心成长感**
   - 以 `FishLuck` 和 `TrashLuck` 的当前值、峰值和增长速度作为核心进展指标。
   - 显式识别 Luck 停滞、重生回落、恢复时间和下一档位等待时间。

这两个报表应成为 Fish 在 IGESS 中最优先的一等报表，并最终进入
`report / compare / gate / scan` 工作流。

## 2. 已确认的指标口径

### 2.1 长期提升行为

主留存指标只统计永久或跨鱼保留、能改变后续能力上限的成长：

- 获得更高档杠铃。
- 摸鱼厅升级。
- 鱼雷购买或升级。
- 垃圾佬境界突破。
- 力量重生和垃圾佬转世获得永久倍率。
- 永久系统、能力或策略解锁。
- 捕获后确实提高最佳鱼厅阵容或长期 CPS 的鱼。

下列行为**不得**计入长期提升密度：

- 单鱼升级。
- 普通投掷。
- 没有提高最佳阵容、Luck 或永久能力的重复奖励。
- 单纯资源消费。
- 临时 Buff 和其他会自然失效的强化。

### 2.2 鱼升级的最终口径

人类已于 2026-07-25 明确：

> 鱼升级不是“提升行为”。它是单鱼临时强化，换一条鱼后新鱼从 1 级开始。

因此鱼升级只能进入以下辅助统计：

- 临时强化次数与材料消耗。
- 强化持续到换鱼的有效时间。
- 临时强化在被替换前带来的收益。
- 临时强化的资源回收率。
- 玩家操作负荷。

不要再把鱼升级次数、鱼升级间隔或由其形成的高频操作解释为长期成长密度。

### 2.3 连续能力成长

力量训练会持续提高 `FishLuck`，但它不是一串离散的永久提升事件。应当：

- 在 Luck 成长曲线中记录；
- 在长期提升间隔中只记录真正的档位、解锁或永久能力变化；
- 同时展示当前值、历史峰值和重生造成的回落。

### 2.4 时间口径

玩家体验的操作间隔使用**累计在线时间**，不使用包含每天 22 小时离线的墙钟
时间。当前默认画像每天在线 7200 秒。

报告可以附带墙钟时间，但不能用它计算玩家在线期间的提升密度。

## 3. 当前 IGESS 演算链路

当前正式模拟确实通过 IGESS 工作流运行：

```text
projects/fish/economy.yaml
-> IGESS 模型加载与校验
-> EngineRegistry 选择 engine_id=fish
-> FishEngineAdapter / FishBehaviorSimulator
-> 确定性行为、RNG、在线/离线和生产结算
-> SimulationResult / checkpoint
-> OutputWriter / RunRegistry / 静态 HTML 报告
```

Fish 的领域数值由 Fish 专用引擎演算；IGESS 负责模型入口、场景、运行登记、
确定性、标准产物、checkpoint 和报告管线。不要把 `engine_id=fish` 误解为
绕开 IGESS。

当前通用 `analysis.md` 仍主要识别 generator/purchase/prestige，因此其中的
`Purchase events: 0` 和空 `payback.csv` 不表示 Fish 没有发生行为。Fish 的
真实行为在 `events.csv/json`，最终状态在 `final_checkpoint.json`。

## 4. 当前生产调价基线

场景：

- 24h：`20260725T040202603439Z-day_1_growth`
- 7d：`20260725T040259487026Z-week_1_growth`

模型摘要：

```text
sha256:66017a648f3ccce9ddb100a6e14e6dd54c0ee9e85177172e6859195c9ea42674
```

数据：

- `production_data=true`
- 数据根：`E:\fish-oasis\igess_export\json`
- 加载器：`E:\fish-oasis\igess_export\python\schema.py`
- 12 张生产表、340 行；每个输入文件及加载器哈希已写入 run manifest。

基线报告：

- [`reports/torpedo-price-balance.md`](reports/torpedo-price-balance.md)
- [`reports/rebirth-long-term-baseline.md`](reports/rebirth-long-term-baseline.md)
- [`runs/20260725T040259487026Z-week_1_growth/report/index.html`](runs/20260725T040259487026Z-week_1_growth/report/index.html)
- [`runs/20260725T040259487026Z-week_1_growth/output/run_manifest.json`](runs/20260725T040259487026Z-week_1_growth/output/run_manifest.json)
- [`runs/20260725T040259487026Z-week_1_growth/output/events.csv`](runs/20260725T040259487026Z-week_1_growth/output/events.csv)
- [`runs/20260725T040259487026Z-week_1_growth/output/luck_progression.csv`](runs/20260725T040259487026Z-week_1_growth/output/luck_progression.csv)
- [`runs/20260725T040259487026Z-week_1_growth/output/behavior_progression.csv`](runs/20260725T040259487026Z-week_1_growth/output/behavior_progression.csv)
- [`runs/20260725T040259487026Z-week_1_growth/output/final_checkpoint.json`](runs/20260725T040259487026Z-week_1_growth/output/final_checkpoint.json)

## 5. 调价前长期提升基线（历史对照）

本节保留用于比较。当前调价后正式 7 天结果已经变为：总永久进展 102 次，
其中系统级 15 次（含鱼雷 8 次）；系统级最大在线空窗 `14,330s`、尾部空窗
`7,199s`，只有 1 个完整在线场次没有系统进展。当前结论以第 0 节和
[`reports/torpedo-price-balance.md`](reports/torpedo-price-balance.md) 为准。

7 天场景共有 14 小时玩家在线时间。排除 2482 次单鱼升级后，只剩 7 次明确
长期提升：

| 墙钟时刻 | 累计在线时间 | 长期提升 | 距上次长期提升 |
| ---: | ---: | --- | ---: |
| 1s | 00:00:01 | 垃圾佬第一次转世 | 1s |
| 8s | 00:00:08 | 合成杠铃 1 | 7s |
| 994s | 00:16:34 | 第一次力量重生 | 16m26s |
| 1939s | 00:32:19 | 合成杠铃 2 | 15m45s |
| 5757s | 01:35:57 | 第二次力量重生 | 1h03m38s |
| 345601s | 08:00:01 | 合成杠铃 4 | 6h24m04s |
| 345671s | 08:01:11 | 第三次力量重生 | 1m10s |

最后一次长期提升发生后，到 14 小时在线结束还有约 `5h58m49s` 的尾部空窗。

第一次垃圾佬转世的要求为境界 0，本质上接近新档赠送。如果不把它视为玩家
挣到的成长，真正的长期提升只有 6 次。

阶段结论：

- 第 1 天前两小时：4 次玩家挣到的长期提升。
- 第 2～4 天：0 次。
- 第 5 天上线后：2 次。
- 第 6～7 天：0 次。
- 7 天内没有摸鱼厅升级、鱼雷升级或新境界突破。
- 当前最大完整在线成长空窗为 `6h24m04s`，尾部还有近 6 小时无长期提升。

这不满足“前期停不下来、后期适度放宽但密度不低”的目标。当前主要问题不是
玩家没有操作，而是大量操作没有转化为跨鱼保留的成长。

## 6. 双 Luck 成长基线

每个正式 `fish_throw_resolved` 事件包含 `input_strength`、`fish_luck` 和
`trash_luck`；`torpedo_purchased` 额外提供购买前后 Luck，报表可以完整重建
两条曲线。

当前每日峰值：

| 模拟日 | FishLuckPeak | TrashLuckPeak | Trash-Fish | 相对差 |
| ---: | ---: | ---: | ---: | ---: |
| 初始 | 3.0000 | 3.0000 | 0.0000 | 0.00% |
| 1 | 11.9194 | 12.5901 | +0.6707 | +5.63% |
| 2 | 15.0003 | 13.0000 | -2.0003 | -13.33% |
| 3 | 16.6237 | 19.0209 | +2.3972 | +14.42% |
| 4 | 18.2032 | 20.0000 | +1.7968 | +9.87% |
| 5 | 25.0374 | 28.7493 | +3.7119 | +14.83% |
| 6 | 28.5446 | 28.7493 | +0.2047 | +0.72% |
| 7 | 29.9657 | 30.0000 | +0.0343 | +0.11% |

解释：

- `FishLuck` 从 3 成长到约 30，力量重生仍会令当前值短暂回落；鱼雷永久
  保留，因此同步验收比较每日/历史峰值，不要求重生后的瞬时当前值相等。
- `TrashLuck` 已由 8 次纯价格购买从 3 推进到 30。
- 第 2、3、5 天约 13%～15% 的误差来自现有鱼雷 power 对应的离散
  TrashLuck 档位；继续只改价格只能改变跳档时点，不能生成中间 Luck。

## 7. 报表字段契约（已实现）

### 7.1 长期提升节奏报表

正式机器可读产物：

```text
behavior_progression.json
behavior_progression.csv
```

每条记录至少包含：

```text
scenario_id
profile_id
wall_time_seconds
active_time_seconds
stage_id
source_event_kind
progression_category
item_id
is_persistent
metric_before
metric_after
metric_delta
gap_from_previous_progression_seconds
```

汇总指标：

- 首次长期提升等待时间。
- 每在线小时长期提升次数。
- 间隔 P50/P75/P90/P95/最大值。
- 当前尾部空窗。
- 没有长期提升的完整在线场次。
- 按系统分类的次数和间隔。
- 单一系统占比和提升种类多样性。
- 获得提升机会与实际执行提升之间的等待时间。

投掷事件需要补充或派生：

- `fish_hall_cps_before`
- `fish_hall_cps_after`
- `fish_hall_cps_delta`
- `changed_best_hall_layout`
- `is_persistent_progression`

只有捕获结果实际提高最佳阵容或长期 CPS 时，才计入长期提升。

### 7.2 Luck 成长感报表

正式机器可读产物：

```text
luck_progression.json
luck_progression.csv
```

按固定累计在线时间采样，至少包含：

```text
active_time_seconds
wall_time_seconds
strength
torpedo_id
fish_luck_current
fish_luck_peak
trash_luck_current
trash_luck_peak
fish_luck_delta_per_active_hour
trash_luck_delta_per_active_hour
time_since_fish_luck_growth
time_since_trash_luck_growth
strength_rebirth_count
trash_man_rebirth_count
reset_or_milestone_marker
```

HTML 报告应显示：

- 当前值与历史峰值两条曲线。
- 重生、鱼雷升级和境界突破标记。
- Luck 增长率。
- 下一档位及 ETA。
- 最长无增长时间。
- 与鱼品质、垃圾品质和 CPS 的关联。

## 8. 数值优化顺序

不要立即扫描倍率。建议按以下顺序推进：

1. **实现并冻结指标口径**
   - 鱼升级从长期提升中排除。
   - 在线时间转换成为统一函数。
   - 长期提升事件与 Luck 固定时间采样可复现。
2. **补齐事件数据**
   - 标记捕获是否真正提高最佳阵容/CPS。
   - 为永久升级记录核心指标 before/after/delta。
3. **生成当前基线报表**
   - 将本文临时统计变成 IGESS 标准 JSON/CSV/HTML。
   - 对 24h/7d 基线建立快照测试。
4. **补齐阻塞核心成长的机制**
   - `[x]` 鱼雷购买已完成，`TrashLuck` 已按纯价格方案增长到 30。
   - 垃圾佬新境界突破，否则第二次转世长期不可达。
   - 检查摸鱼厅首级 5,000,000 材料是否导致不可接受的成长空窗。
5. **与人类确认数值目标**
   - 前 10/30/60 分钟长期提升间隔目标。
   - 中后期 P50/P90/最大空窗上限。
   - 每日最少长期提升次数。
   - FishLuck/TrashLuck 每小时成长和停滞上限。
6. **再进行参数扫描**
   - 使用同一 seed、同一玩家策略和同一生产数据。
   - 每次只改变可归因参数。
   - 用 `compare` 比较基线与候选。
7. **建立 gate**
   - 长期提升密度不得退化。
   - Luck 停滞时间不得超过已确认阈值。
   - 不能通过增加临时鱼升级次数通过长期成长 gate。

完整反事实重生回本仍然重要，但应排在上述留存核心报表之后。

## 9. 当前实现与性能状态

为让 24h/7d 正式场景可运行，当前工作区已经加入：

- 两类重生达到要求后硬最高优先级。
- 纯价格 `purchase_torpedo` 行为、自动装备和完整购买事件。
- `day_1_growth` 和 `week_1_growth` 正式场景。
- 独占可变状态结算路径，同时保留公共复制提交语义。
- 鱼厅收入缓存、精确增量 Top-N 和最低鱼升级价堆。
- 周场景普通事件紧凑明细，重生与鱼雷购买保留完整 trace。
- 流式 `events.json` 输出。
- 24,000 条鱼规模 checkpoint 支持。
- Fish Python 模块均不超过 600 物理行。

7d 当前规模：

```text
前台行为              50,400
总事件               100,822
手动投掷              24,029
鱼升级                 2,481  # 不属于长期提升
杠铃锻炼              23,875
杠铃合成                   3
鱼雷购买                   8
力量重生                   3
垃圾佬转世                 1
```

周事件产物较大：

```text
events.csv             约 61.1 MB
events.json            约 76.6 MB
final_checkpoint.json  约 4.2 MB
```

开发时优先筛选 `events.csv`，不要直接人工通读完整 JSON。

## 10. 当前验证状态

最近验证：

```text
Fish 全量回归                         118 passed, 3 deselected
igess model status                    Model is ready
24h / 7d 正式 run                     passed
鱼雷购买事件字段                      8/8 complete
git diff --check                      passed
```

正式 24h/7d 已核对：

- 24h 三次鱼雷购买时点为 `1095s / 2254s / 7137s`。
- 7d 共 8 次购买，全部进入永久养成报表且必需字段完整。
- 7d 最终 FishLuckPeak/TrashLuckPeak 为 `29.9657 / 30`。
- run manifest 模型摘要与第 4 节一致。

## 11. 常用命令

检查模型：

```powershell
.\.tmp\py311-venv\Scripts\igess.exe model status `
  --project projects\fish
```

重新运行正式场景：

```powershell
.\.tmp\py311-venv\Scripts\igess.exe model simulate `
  --project projects\fish `
  --scenario day_1_growth

.\.tmp\py311-venv\Scripts\igess.exe model simulate `
  --project projects\fish `
  --scenario week_1_growth
```

启动 IGESS Dashboard：

```powershell
.\.tmp\py311-venv\Scripts\igess.exe dashboard `
  --project projects\fish `
  --runs-root projects\fish\runs
```

查看重生事件：

```powershell
$events = Import-Csv `
  'projects\fish\runs\20260725T040259487026Z-week_1_growth\output\events.csv'

$events |
  Where-Object {
    $_.kind -in @(
      'strength_reborn',
      'torpedo_purchased',
      'trash_man_reborn'
    )
  } |
  Select-Object time_seconds, kind, item_id
```

运行 Fish 回归：

```powershell
$fishTests = @(
  Get-ChildItem tests\test_fish_*.py |
  ForEach-Object { $_.FullName }
)
.\.tmp\py311-venv\Scripts\python.exe -m pytest -q @fishTests
```

## 12. 接手时不要误做

- 不要把鱼升级计入长期提升行为。
- 不要用所有前台行为次数代表成长密度。
- 不要用包含 22 小时离线的墙钟间隔评价玩家在线体验。
- 不要把力量每秒增长伪装成每秒发生一次永久提升。
- 不要只画 FishLuck 单调历史峰值而隐藏重生后的当前值回落。
- 不要把调价前 `TrashLuck=3` 的旧 run 当成当前基线。
- 不要把通用 `Purchase events: 0` 解释为 Fish 没有发生经济行为。
- 不要为鱼雷购买重新增加当前力量或历史最高力量门槛。
- 不要在垃圾佬新境界突破缺失时宣称整条垃圾线已经完全验证。
- 不要通过提高临时鱼升级频率来修复长期成长空窗。
- 不要在 10、11 号长期时点和目标阈值确认前进行大规模参数扫描。
- 不要清理当前未提交工作区或删除失败 run；它们保留调试与性能证据。

## 13. 下一次会话的最小交付

以下最小交付已于 2026-07-25 完成：

1. `[x]` 从事件流生成长期提升记录，明确排除鱼升级。
2. `[x]` 生成按累计在线时间采样的 FishLuck/TrashLuck 成长表。
3. `[x]` 将两组指标写入标准 JSON/CSV，并接入静态 HTML 报告。
4. `[x]` 为当前 24h/7d 基线建立确定性测试。
5. `[x]` 用新报表复现本文的 `6h24m04s` 系统级最大成长空窗和
   `TrashLuck` 七天恒定为 3。

本轮已完成第一轮正式数值调优。下一位接手者应：

1. 增加超过 7 天的长期场景，验证 10、11 号鱼雷的 `300B / 600B` 价格。
2. 与人类确认是否接受第 2～5 天由 power 档位导致的约 15% 双 Luck 误差。
3. 若要进一步缩小误差，讨论调整鱼雷 power/Luck 档位；仅改价格已不能产生
   中间 TrashLuck。
4. 将双 Luck 差值与系统级永久进展空窗接入 `compare / gate / scan`。
