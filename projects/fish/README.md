# IGESS Incremental Authoring Project

`economy.yaml` and `Datas/` describe this IGESS project's authoring shell and
the runtime input for a production-data active-throw smoke. They are not the
authority for Fish production values.
`luban_exports/` is generated from those local sources; do not edit generated
exports by hand.

Fish 的经济建模、RNG、玩家存档、专用模拟器接入与正式调参进度统一记录在 [RoadMap.md](RoadMap.md)。该文件是唯一进度源。

Fish 正式数值的唯一权威生产快照是 `E:\fish-oasis\igess_export`。正式表通过其中的 `python\schema.py` 加载同快照的 `json`；IGESS 只消费生成后的强类型表对象，并记录 JSON 与生成加载器哈希，不在本项目中维护手写业务字段解析器；机制测试可使用显式 fixture provider。

当前 `smoke` 会从生产 `tbtorpedo` 第一行初始化新档鱼雷，并用
`engine.active_throw.initial_strength` 初始化 `PlayerState` 力量。每个主动投掷
边界都从 `PlayerState` 锁定力量和已选鱼雷，再调用 `resolve_throw()`；当前
生产 smoke 明确配置为每秒一次、持续十秒。中奖鱼的 `tbfish.weight` 按整数
克写入鱼实例；鱼、废料、投掷统计和 `meta.revision` 在同一个状态迁移中
提交。运行会输出 `fish_throw_resolved` 标准事件并推进 checkpoint 的
`next_throw_id`，分段恢复不会重放已经结算的事件。

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
