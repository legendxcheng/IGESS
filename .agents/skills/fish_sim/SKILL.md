---
name: fish_sim
description: 在 IGESS 项目内迭代 projects/fish_source 的同源 Lua 模拟逻辑，或回答 Fish 玩法、模拟架构、行为策略、恢复和报告口径问题。提供游戏背景、代码定位与验证路径；代码迭代影响这些信息时同步维护本 Skill。
---

# Fish 模拟开发与问答

本 Skill 属于 IGESS 仓库，入口为 `projects/fish_source/README.md`。下文仓库路径均相对 IGESS 根目录；`<source>` 指当前配置解析出的游戏源码根目录，默认是同盘兄弟目录 `E:/fish-oasis`。

## 开始时建立上下文

1. 读取 `projects/fish_source/README.md`、`RoadMap.md` 与根目录 `CONTEXT.md`，区分模拟已接入能力、待办和历史验收结果。
2. 读取 `projects/fish_source/economy.yaml` 的 `engine.source_runtime`，确认实际 `project_root`、`data_root` 与 Lua 入口。相对路径按项目目录解析。旧 `projects/fish` 已停用，旧 Python 模型不作为新规则实现或比较基线。
3. 按问题读取 [代码导航](references/code-map.md) 中相关入口；涉及游戏业务规则时先读 `<source>/simulation/README.md`，再追踪对应服务。涉及另一个仓库的修改时先读取该仓库适用的 `AGENTS.md`，遵守用户范围与实际写权限。

纯问答以当前文件证据回答，不默认启动长模拟或修改代码。迭代开发先明确变化属于玩家策略、宿主接口、游戏规则、数值输入还是报表，沿对应层修改。

## 原项目是什么游戏

Fish 是以摸鱼／炸鱼为主题的增量养成游戏，包含随机收集、经营产出、在线锻炼和重生循环。原游戏在 UE／绿洲启元游戏环境中运行 Lua 服务；IGESS 在无 DS 的数值宿主中复用这些服务。

- 玩家投出摸鱼神器（代码常称 `Torpedo`），力量影响自然飞行落点和水域；鱼与材料结果通过各自随机链结算。
- 鱼进入背包后可上阵摸鱼厅持续产金币，金币先累积在槽位，领取才进入钱包；卖鱼获得一次性资源（材料）。
- 金币投入杠铃，在线锻炼获得力量并影响 Fish Luck；神器影响 Trash Luck。寻宝兽收集并加工废料，完成加工后进入 `material` 钱包，用于资源线养成。
- 力量重生与寻宝兽返祖提供长期成长。读当前源规则确认重置字段、永久收益、突破条件和具体币种，不把阶段性设计描述写死为结算公式。
- 图鉴奖励、图鉴枪、周期鱼潮与鱼蛋孵化形成另一条收集与养成链。真实鱼潮包含射击与争夺；模拟当前采用每场 120 秒、6 次源换弹、5 颗源随机蛋的近似。

设计意图入口：`<source>/gdd/01-核心玩法概述.md`；系统开放查 `54-系统开放规划.md`，枪和鱼潮查 `52-图鉴发枪与鱼潮打蛋.md`。GDD 可能领先实现，例如鱼升级币种、寻宝兽门槛与基础枪补弹规划。回答“目前怎么运行”须追踪当前服务、导表和运行回执；回答“设计想怎样”须注明设计出处。发现两者冲突时说明差异，不自行把规划接入模拟。

## 保持同源边界

- Python 负责玩家意图、行动耗时、上下线、采样、协议与产物；Lua 负责合法性、价格、扣款、奖励、生产和重生。新增行为接入源操作，避免在 Python 复制经济公式或直接改余额。
- Fish 实际数值来自 `engine.source_runtime.data_root`，默认 `<source>/igess_export/json`。本项目 `Datas/` 与 `luban_exports/` 是通用 authoring 结构，改它们不会调整 Fish 数值。生产改表／导出由策划负责，除非用户明确要求代改；测试夹具不得充当生产调优结果。
- `source_priority_v1` 是模拟玩家策略，不等同于真实玩家或旧 Python 策略。行为权重、操作耗时、在线窗口、自然落点与固定距离对照均须保留可归因身份。
- 查询与采样仅观察状态。优化批量推进、查询缓存或分页时，保持源回执、revision、随机结果和最终状态；缓存身份覆盖相关解锁、库存与存档变化。
- 截断不是下线。checkpoint 需保留飞行、前台动作、鱼潮、孵化及待完成副作用；重试保持操作身份，避免重复扣款或发奖。金币／材料 DTO 保持 BigNumber 精度。
- 报告分清钱包与待领金额、余额与累计收入、一次性奖励与持续生产、突破资助与突破完成、采样峰值与真实峰值、本段事件与生命周期首次。缺失采样不能靠重生成报告补齐。
- 同源数值宿主不覆盖 UE 碰撞、真实路线、网络复制、原生武器或多人竞争。GameBalancer 使用发布时冻结的运行包；本地源码修复不代表交付包已更新。
- 收集成长包含正常图鉴完成、首次永久拥有枪、新鱼种与新非普通变异组合。首次即变异可带双标签，总次数只计一个收集事件；按永久图鉴历史去重，不按现存背包。新运行保存本段起始解锁／枪基线及冻结名称，续跑不重放历史；旧续跑缺基线不推断新鱼种首次。时间为源观察时点，同批不推断先后；分类标签数不要求相加等于事件总数。

## 验证与交付

从 IGESS 根目录执行，环境需 Python 3.11+、项目依赖与 `lua55`。优先使用 README 的入口；已有环境可使用 `.tmp/py311-venv/Scripts/` 下的同名程序。

```powershell
uv run igess model status --project projects/fish_source
uv run igess model simulate --project projects/fish_source --scenario smoke --json
uv run --extra dev python -m pytest tests/test_fish_source_formal.py -q
```

`status` 是十 tick 就绪检查，不登记正式运行。按修改层选择代码导航中的回归；规则和调度修改至少覆盖相关行为与正式 smoke。时间推进、恢复、幂等或性能变化还需验证对应边界或连续运行／恢复运行等价性；只改文档时检查链接和内容即可。检查 skipped 原因，源仓库或 Lua 缺失不能算集成通过。长程验证按影响与用户需求选择 `day_1_growth`、`week_1_growth`、`month_1_growth`，不默认全部运行。

正式结果使用命令返回的 `output_dir` 与 `report_index`，核对登记状态、`run_manifest.json`、timeline/events、`source_progression.json`、`source_behavior.json` 与 checkpoint。核对引擎、场景、策略、种子、源码／适配器／所选导表摘要；不同输入或策略不能归因为单个数值变化。解释问题时引用文件／符号或运行证据，区分观察事实、原因推断与建议。

仅需跑数值与解读报告时，可读取仓库 `.codex/skills/fish-balance-loop/SKILL.md`；用户要求构建或发布 GameBalancer 时再读取 `.codex/skills/publish-gamebalancer/SKILL.md`。普通模拟开发不自动发布工具包。

## 迭代后维护本 Skill

每次代码迭代完成前，将实际 diff 与本文件及 `references/code-map.md` 对照：

- 入口、模块职责、服务位置、命令或测试路径改变：同步更新代码导航。
- 游戏背景、模拟覆盖、策略假设、恢复或报表口径改变：同步更新相关说明，并更新受影响的项目 README／RoadMap。
- 新增关键运行依赖或验证方式：更新可执行命令及环境边界。

只更新受影响的信息，删除失效指针；细节留在源文档，通过路径和检索词定位。不要把每次运行指标、测试数量或流水账累积进 Skill。若此次迭代未影响这些信息，无需机械改动 Skill。交付时说明是否更新及原因；这是随迭代执行的维护步骤，不是后台自动监听。
