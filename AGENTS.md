## Agent skills

### Issue tracker

Issues and specs are tracked as local Markdown files under `.scratch/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the default five canonical triage label strings. See `docs/agents/triage-labels.md`.

### Domain docs

This repo uses a single-context domain-doc layout. See `docs/agents/domain.md`.

### Fish simulation

Use `projects/fish_source` for all new Fish simulation, tuning, and rule work. Read `projects/fish_source/README.md` and `projects/fish_source/RoadMap.md` for current scope and progress. `projects/fish` is retired; its code and reports are historical references only.

For Fish simulation development or questions about its gameplay, architecture, behavior, or reports, use the project skill [fish_sim](.agents/skills/fish_sim/SKILL.md). After code iterations, update that skill and its code map when their guidance is affected.

Fish runs delegated to the Agent default to the already running Dashboard at `http://127.0.0.1:8771`. Use `.agents/skills/fish_sim/scripts/run_dashboard.py submit/status`; see [service submission](.agents/skills/fish_sim/references/dashboard-runs.md) for receipts, continuation and completion checks. An unavailable service must not silently fall back to an independent CLI run.

### Simulation performance

Before writing a numerical simulation, changing its hot loop, state observation, caching or scheduling, or evaluating performance, read [数值模拟性能指南](docs/agents/simulation-performance.md). Apply its design and acceptance checklists; distinguish measured end-to-end gains from diagnostic estimates. For Fish, also follow `fish_sim` and the guide's source-reuse boundary.
