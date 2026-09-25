# Fish 同源 Lua 模拟项目

此项目通过 IGESS 正式入口运行 Fish 源项目的 Lua 业务服务，无需 DS。与历史 `projects/fish` Python 后端分开登记运行和基线。

```powershell
uv run igess model simulate --project projects/fish_source --scenario smoke
uv run igess model simulate --project projects/fish_source --scenario day_1_growth
```

`economy.yaml` 的 `engine.source_runtime.project_root` 默认指向同盘兄弟目录 `E:\fish-oasis`，`data_root` 指向该源项目的 `igess_export/json`。运行需要本机 `lua55`。修改目录布局时更新这两个路径。每次运行会冻结 Lua 模块和所选 JSON 导表，记录二者内容摘要、IGESS 适配器摘要、Lua 版本、策略、种子和模型摘要。标准 timeline、events、analysis、Web 报告、同源成长/行为产物和 checkpoint 位于本项目 `runs/`。

本项目的 `Datas/` 与 `luban_exports/` 仅满足 IGESS 当前 authoring 项目的通用配置结构；Fish 数值实际来自 `engine.source_runtime.data_root`。编辑这些通用工作簿不会改变同源 Fish 数值。要测试新的 Fish 数值，应更新所选 Fish JSON 导表，并在运行产物中核对 `selected_export_sha256`。不应把两个后端的运行当成单因素数值改动比较。

Web 报告读取同源状态和交易回执，展示力量、双 Luck、钱包与待领金额、金币投资、杠铃购买及每日／每周成长操作。突破资助不等于突破完成；峰值仅指记录中的采样峰值。旧长场景按天采样，无法补出 5 分钟在线毛产出与精确停滞，缺失指标明确显示为未记录。可用 `igess report --run <运行目录>/output --out <运行目录>/report` 更新已有报告展示，无需重新模拟。

新运行的 1／7／30 天场景已恢复每累计在线 300 秒采样（`sampling_time_basis: online`），离线时间不消耗采样周期；另记录上下线、离线奖励领取及两类重生前后状态，相同状态去重。采样只查询源状态，不改变玩家操作；间隔与时间口径写入运行清单。增加采样点需要重新模拟，不能通过重生成旧报告补齐。状态采样仍不代表完整在线毛产出或连续时间真实峰值。

“资源（材料）余额”有独立图表，直接展示源状态的 `material`，横轴为累计在线时间。默认线性视图保留零余额，可切换对数视图查看数量级；它是扣除消耗后的余额，不是累计获取量。通用资源曲线和总览也使用“资源（材料）”名称，与游戏界面对应。

`source_priority_v1` 使用画像权重在当前可执行操作中选择玩家意图，并按配置的操作耗时、每日在线窗口、领取周期和显式落点假设推进。价格、合法性、扣款、奖励、重生和生产由源 Lua 决定；源规则拒绝会记入事件。力量为零等无法计算当前幸运值的状态在成长产物中记为缺失，不填零。付费倍率等没有源服务支撑的假设画像会在运行前拒绝。

该画像是新策略，不沿用旧 Python 后端的选鱼、出售保护、最高鱼雷等目标策略。当前同权候选按固定轮转选择，单项行为选择第一个满足源报价的目标，背包满时尝试出售第一条未上阵鱼；不合法目标由源服务拒绝。若配置旧 `behavior_target_policies`，运行会在预检中拒绝，避免误以为它生效。

这套宿主覆盖普通鱼数值链，不模拟 UE 世界碰撞、网络复制、真实玩家路线和 DS。`advance_mode: equivalent_batch_v1` 只在区间内没有定时任务和活动 buff 时合并生产事务，保留逐秒模式的最终回执、revision 与状态；`accurate` 可作为逐秒对照。1 天同源正式运行中快速模式约 20 秒、逐秒模式约 53 秒，四份核心业务产物逐字节一致；旧 Python 正式运行约 1.6 秒，但策略语义不同，不能把耗时比当成严格同工作量比值。目前没有整体提速结论。7 天和 30 天配置中沿用的 `compact_event_details` 标记目前不压缩同源回执。
