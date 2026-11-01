# QueryLuck 优化后的 Week1 性能复测

日期：2026-11-01。本轮仅诊断，没有修改生产 Lua、IGESS 业务代码、数值表或策略，也没有提交或发布。

## 结论

剩余成本仍集中在完整状态查询，其次是推进与收益结算。建议下一轮先收敛同一次完整查询内的重复快照与校验，再优化稳定输出的 JSON 编码。幸运值映射与普通鱼等级计算也值得继续优化，但必须分别验证，不能直接把探针时间当作最终收益。

无探针 Week1 参考耗时 **216.334 秒**；带探针内部调用耗时 **298.692 秒**（控制器外层 299.117 秒）。探针包含函数计时、调用归属、指令采样和 Python cProfile，开销明显。两者是诊断及结果一致性对照，不是优化前后性能验收。

本轮鱼池、力量重生、寻宝兽境界导表已不同于上一轮 203.618 秒中位数对应的输入，因此不能据此宣称性能回退。

## 执行与输入身份

- 正式接口：`python -m igess.cli model simulate --project <frozen-project> --scenario week_1_growth --runs-root <isolated-root> --json`。
- 固定 seed 20260626、默认玩家策略、每天 7200 秒活跃、7 天/604800 秒、300 秒在线采样、tick / equivalent_batch_v1。
- 冻结当前 Lua 源码、导表、Python 与项目配置，位置为 `.tmp/fish-post-luck-hotspots-20261101/`。探针仅注入 diagnostic-source；clean-source 保持原样。
- 两次模拟串行，CPU 亲和性 mask 65535（性能核心逻辑 CPU 0–15）；监控未发现其他 Lua 模拟重叠。
- clean run：`20261101T065205271374Z-week_1_growth`。
- diagnostic run：`20261101T065541200203Z-week_1_growth`。
- clean source SHA256：`b3f24e2937a9c70d9ea3e0bfe8ea7dd5a17bd1ac2bddd6db4568da9fdaebc41d`。
- diagnostic source SHA256：`1da23757a1168baeb518538b9e40497995629ea92c691668fa839e6bd0f3ba23`。
- shared data SHA256：`d8ef862c80d2b7654636370b823dce7430902555b2d03dadb7eb35d662dc2d53`。
- Git 参考 HEAD：IGESS `8f81cc31dda4ab43a928388766f17a76a4288a79`，fish-oasis `84f47173466c4ed1689ceb825af921b7f4305727`。工作区存在其他改动，因此冻结输入摘要才是本次身份依据。

计时限制：准备脚本的诊断副本收尾及摘要计算，在 clean 控制器启动后约 8 秒才完成，和主 Lua 启动短暂重叠；clean 所用文件在开始前已复制完成，此时没有修改其输入。216.334 秒仅作为单次无探针参考，不作为严格性能验收。后续运行脚本已增加准备完成检查。

## 请求级热点

下表为带探针正式主 Lua 会话的请求往返墙钟时间，占比以 298.692 秒为分母，包括相应 Lua 工作、通信和响应解析。

| 请求 | 次数 | 耗时 | 占诊断总时间 |
|---|---:|---:|---:|
| 完整状态 query | 11,228 | 177.318 秒 | 59.36% |
| 时间推进 advance | 4,765 | 77.680 秒 | 26.01% |
| 动作查询 query_actions | 2,029 | 7.575 秒 | 2.54% |
| prepare_throw | 437 | 6.472 秒 | 2.17% |
| select_throw_landing | 437 | 4.799 秒 | 1.61% |

Python 总进程 CPU 时间 17.188 秒。cProfile 中锁等待 283.223 秒主要反映等待子进程响应，不能当作 Python 锁竞争的优化目标。全部会话响应 JSON 解析共 4.488 秒，累计 645,474,776 个字符；这不是峰值内存。

## 查询内部热点

下表使用 Lua `os.clock`，含探针干扰。父子函数存在包含关系，不可把表中各行相加，也不能与请求墙钟直接相减来推断纯通信成本。

| 工作 | 次数 | 累计时间 | 说明 |
|---|---:|---:|---|
| 查询 DTO 构建 pipeline.Query | 11,228 | 130.251 秒 | 包含下列业务查询、校验、复制与计算 |
| JSON Encode | 11,228 | 40.064 秒 | 查询 DTO 构建之后的编码 |
| MapStrengthToFishLuck | 11,228 | 27.201 秒 | QueryLuck 已免除奖励求解，剩余力量映射仍有成本 |
| ArchiveSchema.Validate | 57,268 | 19.179 秒 | 平均 5.10 次/完整查询 |
| CalculateProductionSnapshot | 12,714 | 18.098 秒 | 包含等级收益计算等 |
| ArchiveService.GetSnapshot | 103,666 | 13.205 秒 | 平均 9.23 次/完整查询，已包含其内部克隆 |
| CalculateLevelRate | 464,338 | 11.469 秒 | 是收益快照等的子调用，不另行叠加 |
| inventoryProjection | 11,228 | 8.972 秒 | 实际 inventory.Query 仅 1,486 次，已有复用生效 |

快照归属：根查询、barbell、hall、offlineReward、rebirth、torpedo、trashMan 各 11,228 次；guns 22,456 次；inventory 1,486 次；codex 1,128 次。重复查询并非只发生在某一个模块。

校验归属：barbell、offlineReward、rebirth、torpedo、trashMan 各 11,228 次，codex 1,128 次。快照与校验两组计时在当前探针边界互不包含，合计约 32.384 秒；不能再把 Schema.Clone 时间加上去。

VM 指令采样最多的是 BigNumber，其后为 Json、ArchiveSchemaValidationSupport、ArchiveSchemaMigration。这是指令样本数，不是 CPU 百分比，也不能据此把所有 BigNumber 成本归到幸运值。

## 推进与纯计算

advance 中 SettleProduction 调用 10,292 次，包含时间 75.663 秒；其中收益快照约 14.702 秒、档案校验约 6.976 秒。RunTransaction 包含时间 75.694 秒，扣除已包裹子调用后的时间仍有 50.498 秒，但该数包含未单独包裹的事务回调与其他工作，不能直接叫作事务框架开销。

全主会话普通鱼 CalculateLevelRate 调用 828,939 次，仅 639 组不同规则对象/参数组合；GetLevelSnapshot 调用 44,111 次，仅 539 组。说明存在纯结果复用空间，但这个组合计数不是已经实现的缓存命中率，也没有测得缓存后的端到端收益。兽类收益依赖额外状态，不能直接套普通鱼缓存键。

## 下一步顺序与验证边界

1. **一次查询共享只读快照，按相同规则和校验选项复用验证结果。** 先查清服务是否会修改快照、校验选项是否一致及原有失败顺序，再选择最小改动。保持 DTO 隔离，不把可变内部对象暴露给调用方；不跳过合法性校验。
2. **JSON 编码稳定部分复用。** 当前查询编码约 40 秒，优先研究有界的稳定字段名编码复用等局部方案；保留动态余额、进度、revision、能力与错误输出。增量观察属于更大的协议改动，需单独设计。
3. **普通鱼纯等级结果复用。** 按规则身份和完整参数隔离，限制生命周期与容量，返回值保持隔离；不进入 checkpoint。
4. **进一步拆分力量幸运值映射。** 27.201 秒足以值得关注，下一步需要区分 BigNumber 对数区间、边界比较与稳定规则计算。当前没有记录相同力量输入的重复率，不承诺缓存收益；也不改变区间边界和数值精度。

每项改动应单独做同输入差分，再以串行、无探针的整周对照验收。当前只有诊断，没有新增优化收益百分比。

## 一致性验证

通过公开 `runs show/artifacts --json` 核对两个运行均成功、身份完整、覆盖 0–604800 秒、全部登记产物存在。

- timeline、events、source_progression、source_behavior 字节完全一致。
- checkpoint 解压后，仅剔除预期不同的 model_digest 和 session.codeDigest，其余内容及有序命令历史一致。
- manifest 仅剔除预期不同的源码身份与计时后一致。
- 负对照：人为修改 next_throw_id 后比较器正确拒绝。
- 运行后重新计算 live 源码与数据摘要，均与 clean 冻结输入一致。

上述验证覆盖本轮 Week1 产物及恢复状态，没有做全量逐请求 DTO trace 差分，也不是整个仓库测试套件验收。没有生产接口变更，无需更新 skill/code map。

## 证据

- [summary.json](summary.json)：汇总热点、归属与组合计数。
- [profile.json](profile.json)、[python.pstats](python.pstats)：原始探针数据。
- [validation.json](validation.json)：一致性与负对照结果。
- [identity.json](identity.json)、[live-verification.json](live-verification.json)：冻结身份及运行后复核。
- [run-order.json](run-order.json)、[cpu-condition.json](cpu-condition.json)：串行次序与 CPU 条件。
- [prepare.py](prepare.py)、[probe.lua](probe.lua)、[run.py](run.py)、[diagnose.py](diagnose.py)、[analyze.py](analyze.py)：本轮独立诊断脚本。
