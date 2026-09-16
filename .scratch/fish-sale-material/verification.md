# 卖鱼材料实施验证

日期：2026-09-16。用户已确认 [完整方案](design.md)。
IGESS 修改基准 `1bdc072`；实际游戏出售提交 `1ddeebc1`，再次核查 HEAD 为 `d7a065d4`。

## 自动化证据

- 全量默认 pytest：**1452 passed、8 skipped、16 deselected**，197.14 秒。该次包含最初的 20 项出售测试。
- 随后补充优先级、长动作周期合并、checkpoint 错误计数、失败结算原子性和正式 WorkflowService 产物测试；最终 `tests/test_fish_sale.py`：**27 passed**。
- Fish 行为、引擎、鱼厅缓存及报表组合回归：60 passed、2 deselected。
- 八个相关 Python 模块 pyright：0 errors、0 warnings。使用项目 Python 3.11 环境运行；系统 Python 的 pyright 启动器缺少 typing_extensions，未使用其失败结果替代检查。
- `node --check src/igess/reporting/assets/report.js`、`git diff --check` 通过。

覆盖：含变异且排除等级的售价、上阵/神兽保护、整批无效和重复实例的失败原子性、
品质组及同品质决胜、升级投入不保留、扩容后保留组变化、卖后继续投掷、实例 ID
单调递增、删除后等量追加的缓存、重生/突破/购买优先级、周期不打断动作、跨日不足
三秒顺延、错过周期合并、完整/紧凑账本、复制/原地循环等价、付费画像不放大售价、
动作中和离线中恢复，以及正式运行到网页报告的贯通。

## 正式生产证据

smoke、1d、7d、30d 均经 `igess model simulate --project projects/fish --scenario ... --json`
生成成功。模型摘要、四份报告及数值结论见
[卖鱼材料基线](../../projects/fish/reports/fish-sale-material-baseline.md)。

[audit_runs.py](audit_runs.py) 对明确 run ID 核验所有 manifest 产物存在、生产来源为真、
四份输入/加载器哈希和模型摘要相同、出售批次及钱包入账、当前库存与累计捕获守恒，
以及报告材料来源总额与完整/紧凑事件一致。精确审计结果在 [run-audit.json](run-audit.json)。

出售通过新的库存列表使既有身份缓存失效；没有允许出售上阵鱼，也没有为了删除功能
扩大游戏规则。累计卖出数量和已处理周期保存于 Fish checkpoint 的 event_counters，
冻结实例集合保存于既有行为 target_id；实际 PlayerState 存档结构不新增模拟专属字段。
规则摘要已换代，旧金币升级 checkpoint 不能以旧模型摘要静默恢复到新模型。

## 已知范围

- 通用十 tick `model status` 探针尚未派发 Fish，仍报 smoke_failed；四场景正式入口正常。
- 普通主动投掷 smoke 的独立旧分支不调度出售，因此仍保留无出售时的库存等于捕获校验。
  出售在有玩家行为的正式场景执行，带出售状态不跨分支恢复。
- 未修改生产源表、导表生成物或实际游戏代码，未发布 GameBalancer。
- 售价常量是实际游戏规则 10，生产基础值及变异值继续由强类型导表读取；未来游戏
  修改该常量时需要再次同步规则版本，不把界面收益倍率自动解释成卖鱼加成。
