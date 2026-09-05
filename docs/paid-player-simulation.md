# 付费玩家模拟

`paid-run` 将明确购买计划与零购买基线放在同一个来源模型下比较。商品和计划来自独立 YAML；它们作为实验输入参与归因，不修改原有画像、生产表或游戏存档。

## 运行

通用引擎演示：

```powershell
.\.venv\Scripts\python.exe -m igess.cli paid-run `
  --project examples/shelldiver_v0 `
  --experiment examples/paid/generic-example.yaml `
  --out .tmp/paid-generic
```

Fish 演示（需要本机已配置 `projects/fish/production_snapshot`）：

```powershell
.\.venv\Scripts\python.exe -m igess.cli paid-run `
  --project projects/fish `
  --experiment examples/paid/fish-example.yaml `
  --out .tmp/paid-fish
```

Fish 示例执行首日、首周、首月的三个方案，共九次正式运行。示例商品价格、赠送量和倍率仅用于验证机制，不是 Fish 正式商品或建议定价。修改实验文件中的 `scenarios` 可以仅运行首日。

`--out` 必须是新目录，避免把旧报告与新实验混合。正式运行登记到项目的运行历史库，汇总报告写到 `--out`。已有 authoring 项目采用恢复事务后的共享锁与临时导表；非 authoring 项目默认读取 `economy.yaml` 和 `luban_exports`，可通过 `--config`、`--tables` 指定相对项目的路径。一组实验只准备一次来源模型与 Fish 输入快照。

成功返回 `0`；输入无效或任一方案失败返回 `1`。模拟与标准报告生成继续经过 `FormalRunExecutor`。失败保留已生成产物，汇总不能标记为成功。

## 商品与计划

```yaml
schema_version: 1
data_status: example
source: "示例商品，非生产定价"
currency: TEST_CREDITS
profile: default
scenarios: [day_1_growth]
products:
  resource_pack:
    price: "6.00"
    grants: {money: "1000", material: "1000"}
  training_bonus:
    price: "3.00"
    multipliers: {barbell_strength: "2"}
    duration_seconds: 3600
plans:
  starter:
    purchases:
      - {at_seconds: 0, product_id: resource_pack}
  starter_and_training:
    purchases:
      - {at_seconds: 0, product_id: resource_pack}
      - {at_seconds: 1800, product_id: training_bonus, quantity: 1}
```

- `data_status` 必须是 `example` 或 `production`，`source` 必须说明来源。生产商品需要使用实际权益和价格，不能仅修改标签就把示例当成生产结论。
- 一组实验只有一个 `currency` 单位。`price` 是正数，建议用带引号的精确十进制；累计金额使用 Decimal。花费记录在独立账本，不扣游戏内资源，也不发生真实支付。
- `profile` 是所有方案共用的现有画像。程序自动添加保留名 `free`，表示该画像的零新增购买基线；原有收益倍率仍保留。因此对比普通免费玩家时，应选择没有既有付费加成的画像。
- `grants` 一次性赠送资源；`multipliers` 乘到既有画像的对应产出来源上。两者至少有一项。资源数量与倍率都必须是正数，未知资源或产出来源立即报错。
- `duration_seconds` 仅约束倍率，不撤回已赠送资源；省略表示永久倍率。
- `at_seconds` 是从新档开始计算的整数墙钟秒。相同时刻的购买保留 YAML 列表顺序；可以发生在离线期间，表示外部预定购买。仅允许在线购买的实际商品，应把购买计划排在在线时段。
- 倍率在 `[at_seconds, at_seconds + duration_seconds)` 生效。不同购买独立相乘，包括同商品重复购买。数量为 2 的 `2×` 商品会产生 `4×` 倍率，不表示续期；续期类商品需要按其实际规则另行建模。
- 同秒先结算旧收益并完成已有行为，再处理到期及购买，最后记录状态并选择下一行为。零秒购买在初始记录前发生。场景结束秒的购买也会记账；晚于结束秒的购买不执行、不计入花费。
- 支持 1～10 个场景、1～20 个自定义方案、最多 100 个商品、每方案最多 1000 笔购买；单笔数量最多 1000。Generic 的购买与到期时点必须对齐 `model.tick_seconds`。

## 引擎权益范围

Generic 支持模型中的资源赠送，以及已声明 `source_types` 的收益倍率。Fish 支持当前加权行为循环：

| 配置 | 支持值 |
| --- | --- |
| `grants` | `money`、`material`、`strength` |
| `multipliers` | `fish_hall_money`、`trash_material`、`barbell_strength` |

Fish 的一次性赠送沿用正式存档的四位有效数字规则。倍率在在线与离线结算中叠加到原有规则上：离线鱼厅与材料仍按既有 50% 效率结算，力量仍为 0。购买或到期不会重新抽取正在进行的行为，原行为完成后下一轮才根据新状态选择行为。

Fish 引擎的 checkpoint 保留已购买件数，恢复时核对相同计划摘要、时间与购买次数；倍率由计划重建，已发放资源不重复发放。`paid-run` 首版执行完整的一组对照，尚未提供批次级断点续跑入口。

## 报告

输出目录包含：

- `index.html`、本地 ECharts 与 `paid-report.js`：离线中文报告。
- `paid_comparison.json`：完整计划、输入摘要、画像、种子、运行路径、结果及购买账本。
- `paid_summary.csv`：各方案累计花费、资源余额与差值、Fish 期末进度和成长空窗。
- `paid_milestones.csv`：成长节点达成状态及节省时间。

成长曲线可切换场景，显示实际资源与 CPS；纵轴使用 `log10(1 + 数值)`，悬停显示原始值，最多保留约 3000 个采样点／方案。完整采样仍保存在各正式运行的 timeline 中。

Fish 额外展示当前／历史最高境界、鱼雷与杠铃 ID、鱼厅等级、两类重生次数、系统永久进展次数、最大相邻在线空窗和尾部在线空窗。当前境界可能因转世下降，应结合历史最高境界及转世次数阅读。

相同节点只有双方达成时才计算节省时间，正值表示付费更早，负值表示更晚。只有一方达成时显示明确状态，另一方的时间留空，不能按零处理或外推。鱼雷、境界、鱼厅和重生节点按达到至少该档位／次数比较，跳档不会被误判为落后；杠铃按实际装备 ID 比较。Generic 首版只提供墙钟时间差，不推算在线时间。

所有方案保持同一画像 ID、在线安排、策略和随机种子。随机流按行为／投掷序号配对；购买可能改变候选行为与投掷频次，不承诺在同一墙钟时刻捕获相同内容。单种子实验只能描述这组轨迹，不能解释为付费人群的分位数或转化预测。

## 当前范围

首版不模拟卡关自动购买、随机付费商品、付费改变掉落概率、非资源型权益、退款、混合货币、营收和转化率。商品表的生产适配与执行工具包工作台入口也不在本次交付中。执行工具包未自动发布。

新增功能测试：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_payments.py -q
```
