# 幸运值查询按需计算验收（2026-11-01）

## 状态

实现、功能等价和三组固定性能核的串行 Week1 对照已完成。端到端中位数 252.677 → 203.618 秒，耗时降低 19.42%（速度比 1.241 倍）。这是本次固定输入场景与受控运行条件下的测量，不是全部运行环境的保证。

## 实际改动

源游戏 `FishThrowService.QueryLuck` 改为调用 `ThrowOutcomeResolver.QueryLuck`。新入口复用完整抛投的输入校验、私有冻结规则、修正项和幸运值映射，只构造 `fishLuck / trashLuck / fishPoolId / trashPoolId` 四个字段。正式抛投仍调用完整 `Resolve`，奖励抽取、随机坐标、大数精度、舍入与游戏行为不变。

省掉的是只读观察中未使用的 bonus / mutation / fish / trash 奖励抽取、奖励筛选、`fishRollPower` 大数除法及多余 DTO。幸运值映射自身需要的精确计算仍保留。

共享 `prepareLuck` 仅提取原来的公共前缀。显式 options（包括空表）、自定义随机提供者或规则，以及无法证明奖励尾部不会拒绝的极端默认配置，继续执行完整 Resolve 再投影，保留错误顺序与注入提供者的副作用。

快路径的规则安全条件包括正常鱼和垃圾回退项、各变异鱼池非空、bonus 层数与倍率界限、浮点数及 BigNumber 指数余量。默认随机数的最小正值为 2^-53；trash/bonus luck 不超过 1e280，故对应除法保持有限。最多四层 1e±6 倍率及随机分子/分母操作远小于预留的 1024 指数余量。编译器原本即限制 mutation 总权重在安全整数范围内。

仅缓存模块私有、冻结默认规则的一项安全判定；不缓存玩家幸运值，不增加玩家状态或 checkpoint 字段。公开 DTO 每次独立构造。

## 冻结身份与测量入口

- 基线源代码：`01f258b01b93d2e411316092c0b112e8aef6e65cdaee68daf1ad1e75e2f6d6ad`
- 候选源代码：`970db32fc4fd865a3b2b25e7225dd0faa7cc3a1578685be00079893051ce72ef`
- 同一导表：`2ab9696157c44460503e2c5ff23a66eb4cb2636b31e03b5a70ffb205e45aaa81`
- 同一 IGESS 适配器：`9d5ca91921fdb5fcd764fa08e9da2dc2beed6e4a1bf798c5d7b207c4739c7d0c`
- 源码、导表、Python 执行代码、两个项目配置均冻结在 `E:/IGESS/.tmp/fish-luck-query-20261101/`。两个配置仅源代码根目录不同，选择相同冻结导表。
- 硬件：Intel Core i7-14700KF，28 逻辑处理器；Windows，Python 3.11.9，Lua 5.5。未修改优先级。早期测量采用默认全部核心；最终对照将两侧都固定在逻辑核 0～15（操作系统 CPU Set efficiency class=1 的八个物理核，affinity mask=65535）。拓扑与条件见 `cpu-condition.json`；这个设置仅作用于本测试进程树，不改变游戏或系统设置。
- 正式入口：`python -m igess.cli model simulate --project <frozen-project> --scenario week_1_growth --runs-root <isolated-runs> --json`。端到端计时包括新 Python 进程启动、Lua 模拟、检查点与报告。无内部探针。
- 同输入、default 策略、种子 20260626、每日在线 7200 秒、604800 秒 Week1；短场景为 86400 秒 Day1。具体请求和结构化回执见各 JSON。

## 正确性证据

1. `tests/throw_luck_query_test.lua`：221 个精确差分用例通过。覆盖当前导表所有池边界及前后、长精度大数、修正项、非法输入/选项、随机种子边界、自定义随机提供者、异常默认鱼池/垃圾池/bonus 规则、DTO 隔离。测试同时加载冻结旧 Resolver，核对完整抛投输出不变。
2. 无奖励计算检查：在不需要对数插值的池端点，QueryLuck 的奖励随机调用和大数除法均为零，完整 Resolve 对照确实执行两者。这不是对所有幸运值映射的零除法声明。
3. Day1 原观察点追踪：1,397 次完整查询及请求选项一致，最终完整 Query 一致。见 `comparisons.json` 的 trace 项；追踪运行仅用于正确性，不作正式性能成绩。
4. 已完成的 Week1 核心产物 `timeline.json / events.json / source_progression.json / source_behavior.json` 字节一致；解压 checkpoint 后全部业务状态与有序会话历史一致。只忽略 model/code digest 与运行耗时这些明示身份字段。篡改 `next_throw_id` 的负例被比较器拒绝。
5. 相关 IGESS 五个测试文件：29 通过、2 失败（`regressions-isolated.log`）。两个失败为旧池边界断言 51→2 和 2001→3；当前表边界是 200 / 3000。冻结旧代码复跑相同参数得到同样两项失败（`baseline-pool-regression.log`），并非本改动引入。通过项包括正式模拟/报告、批量查询等价、自然落水与真实新进程 checkpoint 续跑。
6. 既有源端 `throw_outcome_resolver_test.lua` 在第 630 行期望 base luck 20、实际 16.778466380674359；冻结旧代码与当前候选同样失败。没有为了通过旧表预期而改动数值或原测试。

## 早期测量与排除理由

| 运行 | 耗时（秒） | 处理 |
| --- | ---: | --- |
| pair1 baseline Week1 | 264.281 | 与候选间隔较长且中间进行了回归测试；保留原始结果，不混入后续连续配对 |
| pair1 candidate Week1 | 356.751 | 本组未证明收益，核心业务等价；原因未确定 |
| pair2 candidate Week1 | 396.527 | 运行中发现另一 Agent 的正式 Week1 与其重叠，排除性能结论 |
| final1 baseline Week1（默认核心） | 506.005 | 无外部 Lua 重叠，但出现较大跨轮漂移；单列默认调度条件，不与后续固定核结果混算 |
| final1 candidate Week1（默认核心） | 433.274 | 本组耗时降低 14.37%，核心字节/完整 checkpoint 业务历史等价；仅作默认调度下的补充观测 |
| trace baseline / candidate Day1 | 39.324 / 29.642 | 带完整观察追踪，仅作正确性证据 |

10:28（本地时间）出现外部 Lua PID 65896，父进程 59048 的命令为正式 `projects/fish_source --scenario week_1_growth`。用户确认属于另一优化 Agent，并同意让它完成当前任务后暂停新测速。本任务只停止自己的调度父进程，当前候选正常完成；没有停止或修改对方进程。

后续使用 `run_isolated_pairs.py`，等待外部 Lua 退出后，按 baseline→candidate、candidate→baseline、baseline→candidate 顺序执行三组新配对，再测短场景。每 5 秒检查进程树并记录任何外部 Lua 重叠；发生重叠则保留产物并中止后续计时，不将其当作无干扰成绩。进程检查在业务进程外，不改动 Lua/Python 模拟计算。

默认核心下新基线仍达到 506.005 秒，系统 CPU 抽样也从约 50% 降到 8%。为控制异构 CPU 调度这一变量，最终改为同一组固定性能核的 `pinned-final1/2/3` 配对以及 `pinned-short`。这是实验条件控制，并非已证明早期漂移一定由能效核造成。旧结果全部保留；最终统计脚本只选取预先指定的 pinned 组，运行顺序与外部 Lua 重叠检查见 `pinned-final-order.json`，系统负载抽样见 `background-load.jsonl`。

## 最终正式配对

| 顺序 | 基线（秒） | 候选（秒） | 耗时降低 |
| --- | ---: | ---: | ---: |
| pinned-final1：基线→候选 | 255.027 | 203.618 | 20.16% |
| pinned-final2：候选→基线 | 251.459 | 201.735 | 19.77% |
| pinned-final3：基线→候选 | 252.677 | 203.740 | 19.37% |

基线范围 251.459～255.027 秒；候选范围 201.735～203.740 秒。短场景 Day1 24.588 → 18.889 秒，耗时降低 23.18%。

八条最终正式运行均通过公共 `igess runs show/artifacts --json` 复核：success、identity_complete、登记产物齐全，源代码/导表/适配器身份符合冻结记录，完整执行窗口正确。三组 Week1 与一组 Day1 核心字节、checkpoint 全部业务状态和有序历史均一致；比较器负例均被拒绝。最终进程监控记录未发现外部 Lua 重叠。

原始回执见 `pinned-*.json`；最终统计见 [final-summary.json](final-summary.json)，运行顺序见 [pinned-final-order.json](pinned-final-order.json)，等价比较见 [pinned-final-comparisons.json](pinned-final-comparisons.json)，运行登记核验见 [registry-checks.json](registry-checks.json)。

## 最终运行 ID

| 场景与组 | 基线 | 候选 |
| --- | --- | --- |
| pinned-final1 / week_1_growth | `20261101T025100325847Z-week_1_growth` | `20261101T025515885472Z-week_1_growth` |
| pinned-final2 / week_1_growth | `20261101T030207535832Z-week_1_growth` | `20261101T025841972687Z-week_1_growth` |
| pinned-final3 / week_1_growth | `20261101T030623805175Z-week_1_growth` | `20261101T031039979506Z-week_1_growth` |
| pinned-short / day_1_growth | `20261101T031405501854Z-day_1_growth` | `20261101T031430793690Z-day_1_growth` |

## 交付范围

源码仅修改两处 Lua 业务文件，新增定向测试；同步 source simulation README、fish_sim skill/code map 及 Fish 项目 README/RoadMap。没有改表、策略、奖励概率、检查点格式或发布 GameBalancer。提交仅包含本项改动，保留其他脏工作区内容，未推送。

最终核验两处业务源码与候选快照逐字节一致，见 `live-verification.json`。测试期间工作区的 `proj/Script/Table/tbtrashmanrealm.lua` 与 `igess_export/json/tbtrashmanrealm.json` 发生了本任务之外的变化，已原样保留；因此当前整个源树/导表摘要与冻结输入不同，19.42% 是冻结输入下本项优化的独立收益，不是新表或其他并行工作的合并成绩。变化清单见 `parallel-workspace-changes.json`。当前导表下补跑同一源端差分测试仍为 221 项通过，见 `final-live-luck-regression.log`。

尚未进行 UE/DS/客户端验收；本次证据覆盖同源 Lua 与 IGESS。本次采用该优化：受控配对证明整周收益，原查询/抛投业务行为与恢复历史保持等价。

## 接受与提交

用户已确认验收并授权 Git 提交。游戏源码提交为 `84f47173466c4ed1689ceb825af921b7f4305727`（`E:/fish-oasis`，性能优化：幸运值查询仅计算所需结果）；IGESS 的相关文档段落与本目录证据独立提交。源码提交前核对暂存 Lua 字节与被测候选一致，不包含数值表、其他 `simulation/Query.lua` 修改或其他未提交工作。

本目录保留原始回执、逐次观察、比较器、测试日志及最终统计。`.tmp/fish-luck-query-20261101/` 中的完整源代码/导表快照和正式运行产物为本机验证材料，不随本次提交复制。这里的脚本记录一次性实验流程，需要对应冻结输入；不能在缺少快照时直接重跑并把当前工作区当作原基线。
