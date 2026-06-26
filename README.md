# IGESS

Incremental Game Economy Simulation System (`IGESS`) is a local Python CLI for simulating idle / incremental game economies from YAML rules plus Luban-export-style data tables.

The v0.1 scope follows `E:\雨林星\立项\炸鱼佬传说\增量经济模拟DSL交接文档.md`.

## Quick Start

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -e .[dev]
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\python -m igess.cli lint --config examples/shelldiver_v0/economy.yaml --tables examples/shelldiver_v0/luban_exports
.\.venv\Scripts\python -m igess.cli run --config examples/shelldiver_v0/economy.yaml --tables examples/shelldiver_v0/luban_exports --scenario day_1_progression --out .tmp/sim
```

Outputs are deterministic JSON, CSV, and Markdown files.

## v0.1 Scope

Implemented now:

- YAML rules and Luban-export-style JSON tables.
- `resources`, `generators`, `upgrades`, and `constants` tables.
- Optional `milestones` and `prestige_layers` tables.
- Explicit `number_backend` and a `SimNumber` economy number wrapper.
- Safe AST formula compilation at load/build time.
- Config linting for ids, formulas, source types, modifier targets, profiles, policies, and deterministic seed.
- Exponential generator costs, linear production, upgrade modifiers, and the standard modifier pipeline.
- `casual`, `optimizer`, and `explorer` player profiles in the sample config.
- `cheap_unlock_first`, `fastest_payback`, and `new_content_bias` behavior policies.
- Session-pattern-driven offline reward pulses.
- Milestone reward claims.
- Simple prestige conversion and configured resource reset.
- Fixed tick simulation and an explicit `analytic_leap` placeholder for later.
- JSON, CSV, and Markdown outputs.
- Windows sample runner: `.\scripts\run_sample.ps1`.

Deferred from v0.1:

- Probability gates.
- Build delays.
- Complex offline caps.
- Multi-layer prestige balancing beyond the simple configurable layer included in the sample.
- Chart visualization.

See [Luban Workflow](docs/luban-workflow.md) for the authoring/export contract.
