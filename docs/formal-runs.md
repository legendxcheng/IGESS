# 正式运行与调试

正式运行的共同执行流程在 `src/igess/formal_run.py`。修改执行顺序、checkpoint、模拟产物、报告或终态处理时，从这里开始。模型规则提交时自动触发的十 tick smoke 仍由 authoring 的事务流程负责。

## 入口与职责

| 入口 | 输入准备与响应 | 共同执行部分 |
| --- | --- | --- |
| `WorkflowService.run_scenario` | 准备前登记运行，读取开发配置，返回 `RunRecord` | `FormalRunExecutor.execute` |
| `AuthoringService._simulate_shared` / `model simulate` | 共享锁内使用临时导表，准备后预留目录和登记运行，返回 `CommandResponse` | `FormalRunExecutor.execute` |
| `OperatorService._run_snapshot` / 调优工作台 | 固定场景、只读输入快照，运行后追加工具版本与清洗后的诊断，成功后才比较和检查回归 | `FormalRunExecutor.execute` |

`PreparedRun` 交付已准备的引擎、adapter、运行记录及恢复输入。共同模块依次执行模拟、checkpoint、模拟产物、报告、最终状态，返回 `RunOutcome`。输入权限、锁、事务、快照和响应转换由入口负责；`model simulate` 的报告与终态写入仍位于共享锁和临时导表的有效期内。

Generic 在工作流和工具包中的旧元数据格式继续保留；`model simulate` 的 Generic 正式运行继续携带模型摘要。不要为了让三个入口的 JSON 完全相同而删除这些既有差异。

## 按运行 ID 定位失败

源码开发入口失败时，详细诊断保存在项目根目录的 `.igess/diagnostics/<run_id>.json`。在运行 ID 分配前失败则使用 `attempt-<uuid>.json`，不额外创建运行记录。诊断目录已加入 Git 忽略规则。

- `model simulate` 的错误响应在 `details.diagnostic_id` 和 `details.diagnostic_path` 中提供关联信息。
- 开发工作流的失败消息包含诊断路径。
- JSON 的 `phase` 是内部执行阶段，`primary_error` 保存原始异常及异常链，`secondary_errors` 保存之后发生的状态写入、诊断或清理异常。
- `context` 提供当时可得的运行 ID、引擎、场景、画像、模型摘要、种子、输入引用、override 及产物位置。准备阶段失败时，尚未得到的上下文不会被补造。

```powershell
# 把 <run_id> 替换为失败响应中的运行 ID；在对应项目根目录执行。
Get-Content -LiteralPath '.igess/diagnostics/<run_id>.json' -Raw
```

`model simulate` 保持原有错误码和 `details.phase`；更细的阶段在 `details.execution_stage` 和诊断 JSON 的 `phase` 中查看。

| 内部阶段 | 排查位置 |
| --- | --- |
| `prepare` | 输入加载、模型校验、画像选择和 adapter 准备 |
| `reservation` | authoring 正式运行目录预留 |
| `simulate` | 引擎执行 |
| `checkpoint` | 最终 checkpoint 写入 |
| `artifacts` | `OutputWriter` 和领域产物 |
| `report` | 静态报告读取与生成 |
| `run_status` | 运行历史的状态持久化 |
| `snapshot_cleanup` | 执行结束后退出临时导表上下文 |

模拟完成但报告失败时，整次运行标为 `failed`，消息包含 `[report]`。已经写出的数据和 Fish 最终 checkpoint 保留；checkpoint 可继续作为显式恢复输入。调优工作台不会对失败运行执行比较。

如果失败状态也无法写入，调用返回失败并提示未保存；磁盘历史可能仍是上一次的 `running` 状态。开发诊断会保留最早异常与后续写入异常。诊断本身写入失败时，返回原失败和诊断未保存提示，不把诊断失败替换为主要原因。

这些详细诊断仅供源码开发使用，包含调用栈和本地路径，保存于报告目录之外。执行工具包不依赖 `development_diagnostics` 或 `authoring`，仍只写清洗后的业务诊断与原有诊断包；完整导表快照仍需显式选择。

## 验证与当前边界

`tests/test_formal_run.py` 验证旧入口引擎约束及失败保真；三个入口各自的测试覆盖响应兼容、相同 Generic 输入的产物等价、报告失败、Fish checkpoint 恢复和工具包依赖隔离。`tests/test_operator_toolkit.py` 还通过 Python 3.11 实际生成并检查工具包。

旧 `run`、`scan`、`advise` 只支持 Generic，收到 Fish 或其他不支持的引擎时会在写产物前报错。Fish 正式模拟使用 `model simulate`；这不表示它提供 Fish 参数扫描或建议功能。

目前没有新增定期 checkpoint、自动重放或一键重建报告。引擎中途失败时，诊断中的模拟时间和当前行为标为不可得；最终 checkpoint 只有引擎成功返回并完成写入后才存在。
