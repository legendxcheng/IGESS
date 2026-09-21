# 杠铃半秒收益累计验证

日期：2026-09-21。

## 已确认范围

用户选择：保留每段 60 秒的 `exercise_barbell` 行为，按每 0.5 秒一次正确累计
力量；不要求策略、事件或存档出现 0.5 秒时间点。两种生产画像及其 YAML 时长未改动。

源项目提交 `fab55c1682164d9e417eba0f2ff13f554f2e9770` 将 `Barbell.timeCost`
从 1 改为 0.5，`BarbellEconomyRules.lua` 使用 `ExerciseTiming.IsTime` 验证。
源项目时间运算使用整数毫秒，结算按完整次数计算。当前权威导表 15 档均为 0.5 秒。

模拟阻塞点为 `FishBarbellDataAdapter._load_rules` 对 `timeCost` 的正整数校验。
已改为 Decimal 秒值，保持毫秒精度与源项目的最大时间范围，拒绝布尔值、非数值、
非有限数、非正值和小于毫秒的精度；没有把生产表或单次收益写死进模拟代码。
原有生产结算公式 `strengthPerExercise / timeCost × elapsed_seconds` 可以直接消费
小数间隔，故不需要修改全局时钟。

整数秒区间能被 0.5 整除，因此当前数据的区间基础收益等于完整次数 × 单次力量。
保持既有大数钱包精度与归一化规则，不模拟每半秒一次的钱包事务或行为抢占；其他
不能整除结算区间的周期仍属于既有连续收益近似，需要逐次结算时应另建周期进度。

## 自动化证据

- 定向回归：51 passed。
- Fish、通用行为、checkpoint 和 TimeEngine 组合回归：322 passed、1193 deselected。
- 新增测试覆盖 0.5/0.25/0.125/0.001 秒与整数兼容、非法值、1 秒和 60 秒收益、
  画像倍率、库存数量不放大产出、非锻炼与离线零收益，以及复制/原地循环中的
  第 31 秒 checkpoint 落盘恢复和整段运行结果一致。
- 现有外部生产测试里的首把杠铃收益和间隔断言改为对照实际生成行；该混合测试的
  其他旧表值断言不属于本次修订范围，未用它代替本次正式运行验证。

命令：

```powershell
.\.tmp\py311-venv\Scripts\python.exe -m pytest tests -k 'fish or behavior or checkpoint or time_engine' -q
.\.tmp\py311-venv\Scripts\igess.exe model simulate --project projects\fish --scenario day_1_growth --json
.\.tmp\py311-venv\Scripts\python.exe .scratch/fish-barbell-subsecond/audit_run.py
```

## 正式生产证据

- 运行：`20260921T085635814804Z-day_1_growth`，default，24 小时，每日在线 7200 秒，种子 20260626。
- 模型摘要：`sha256:d7ad83f893ae66c855317c16e822e32c54df8da0d408e6a093e734f514c9ffdb`。
- 数据根：`E:\fish-oasis\igess_export\json`，同批 `python\schema.py`，
  `production_data=true`、无 override，所有输入及加载器哈希已与运行 manifest 核对。
- [正式报告](../../projects/fish/runs/20260921T085635814804Z-day_1_growth/report/index.html)。
- [审计程序](audit_run.py) 与 [审计结果](run-audit.json) 验证所有声明产物、报告、
  checkpoint 的场景/画像/种子/时间/摘要，以及每段锻炼的时长、间隔和基础/最终收益。
- 共 75 段 60 秒锻炼，等价 9000 次；使用 1～5 号杠铃，每段基础力量分别为
  120、240、600、3000、9000。其他行为与离线事件没有杠铃力量入账。

本次源数据同时改变每次力量：铁杠铃 2→1，周期 1→0.5，仍为每秒 2；
河豚杠铃 5→2，实际每秒 5→4（下降 20%）。导表 description 仍含旧的单次数字，
模拟只读取数值字段。当前其他表和价格也有变更，不能将新旧一天结果的差异单独
归因于半秒周期。

未修改游戏源码、生产源表或导表文件，未发布 GameBalancer。`model status` 的
通用十 tick 探针仍有已知 Fish 失败；本次验证通过的是正式 Fish 引擎工作流。
