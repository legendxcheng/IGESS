# IGESS 同源后端正式运行与报告

Status: ready-for-agent
Implementation: completed

IGESS 新增 `fish_source` 适配器，在正式 `model simulate`/RunRegistry 中调度玩家意图，通过源会话查询资格与报价。输出标准 timeline、events、analysis、Web 报告和源观察成长/行为报告；显式预检不支持的倍率、旧目标策略及场景假设。

验收：smoke、1 天、7 天正式运行成功，报告和最终 checkpoint 齐全；拒绝与故障不会静默退回 Python 后端。

## Comments

- 2026-09-24：实现于 `src/igess/fish_source_engine.py`、`fish_source_reports.py` 与独立 `projects/fish_source`；正式边界测试见 `tests/test_fish_source_formal.py`。30 天场景由下一票验证。
