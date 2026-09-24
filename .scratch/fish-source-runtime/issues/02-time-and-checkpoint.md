# 虚拟时间、运行快照与会话恢复

Status: ready-for-agent
Implementation: completed-with-limitations

统一虚拟时间承载源业务定时回调；同源准确模式为基准，等价批量模式只在无定时任务与活动 buff 的区间合并。正式运行冻结 Lua 源与所选导表，记录代码、数据、VM、策略身份；checkpoint 可跨进程重放活动中的锻炼和投掷。

验收：分段/连续与准确/批量推进可观察结果相等，活动中 checkpoint 恢复不重复奖励，代码或数据变化拒绝旧 checkpoint。

## Comments

- 2026-09-24：源会话测试覆盖准确/批量状态、回执及 revision 对比，跨进程测试覆盖活动中恢复；正式入口覆盖 checkpoint 读取和数据失配。当前正式工作流仅在运行末写最终 checkpoint；周期性中途落盘另需补齐。
