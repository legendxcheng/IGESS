# IGESS

Incremental Game Economy Simulation System (`IGESS`) is a local-first toolkit for
simulating, reporting, comparing, and regression-checking idle / incremental game
economies from YAML rules plus Luban-export-style data tables.

The original v0.1 scope follows `E:\雨林星\立项\炸鱼佬传说\增量经济模拟DSL交接文档.md`.
The current implementation is v0.5 and includes Web reports, a local dashboard,
run comparison, parameter scanning, regression gates, project ergonomics
commands, and Agent Analyst advice artifacts.

## Quick Start

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -e .[dev]
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\python -m igess.cli export-tables --datas data-tables/Datas --out examples/shelldiver_v0/luban_exports
.\.venv\Scripts\python -m igess.cli lint --config examples/shelldiver_v0/economy.yaml --tables examples/shelldiver_v0/luban_exports
.\.venv\Scripts\python -m igess.cli run --config examples/shelldiver_v0/economy.yaml --tables examples/shelldiver_v0/luban_exports --scenario day_1_progression --out .tmp/sim
```

Outputs are deterministic JSON, CSV, and Markdown files:

- `run_manifest.json`
- `timeline.json` / `timeline.csv`
- `events.json` / `events.csv`
- `analysis.json`
- `analysis.md`
- `payback.csv`

## v0.4 Workflow

The normal tuning loop is:

```powershell
.\.venv\Scripts\python -m igess.cli export-tables --datas data-tables/Datas --out .tmp/exports
.\.venv\Scripts\python -m igess.cli lint --config examples/shelldiver_v0/economy.yaml --tables .tmp/exports
.\.venv\Scripts\python -m igess.cli run --config examples/shelldiver_v0/economy.yaml --tables .tmp/exports --scenario day_1_progression --out .tmp/run_a
.\.venv\Scripts\python -m igess.cli report --run .tmp/run_a --out .tmp/report_a
.\.venv\Scripts\python -m igess.cli compare --base .tmp/run_a --candidate .tmp/run_a --out .tmp/compare
.\.venv\Scripts\python -m igess.cli scan --config examples/shelldiver_v0/economy.yaml --tables .tmp/exports --scenario day_1_progression --param generators.fisherman.cost_growth=1.14..1.15:0.01 --out .tmp/scan
.\.venv\Scripts\python -m igess.cli gate --base .tmp/run_a --candidate .tmp/run_a --config examples/shelldiver_v0/economy.yaml --out .tmp/gate
.\.venv\Scripts\python -m igess.cli doctor --project . --config examples/shelldiver_v0/economy.yaml --tables .tmp/exports
.\.venv\Scripts\python -m igess.cli explain --run .tmp/run_a --event 0
```

For a browser UI:

```powershell
.\.venv\Scripts\python -m igess.cli dashboard --project . --config examples/shelldiver_v0/economy.yaml --tables examples/shelldiver_v0/luban_exports --host 127.0.0.1 --port 8765
```

Open `http://127.0.0.1:8765/`.

### Static Reports

`report` reads a run directory and writes a self-contained report folder:

- `index.html`
- `assets/report.css`
- `assets/report.js`

The report includes overview metadata, resource curves, event timeline, payback
table, analysis warnings, and formula/source traces.

### Dashboard

`dashboard` starts a local stdlib HTTP server. It can lint the configured project,
run the sample scenario, persist run history under `.igess/runs`, and open the
generated static report for each run.

### Comparison

`compare` reads two run directories and writes:

- `comparison.json`
- `index.html`

It compares final resources, unlock times, purchase counts, prestige counts, and
payback seconds.

### Parameter Scan

`scan` supports one inclusive numeric override range:

```powershell
.\.venv\Scripts\python -m igess.cli scan --config examples/shelldiver_v0/economy.yaml --tables examples/shelldiver_v0/luban_exports --scenario day_1_progression --param generators.fisherman.cost_growth=1.14..1.15:0.01 --out .tmp/scan
```

Each variant records override provenance in `run_manifest.json` and produces its
own static report.

### Regression Gates

`gate` reads `regression_gates` from YAML. Supported rules:

```yaml
regression_gates:
  day_1_progression:
    max_unlock_delay_pct:
      generator:fisherman: 20
    max_payback_seconds:
      generator:fisherman: 999999
    min_prestige_gain:
      optimizer: 1
```

Gate results are written to `gate_results.json` and `gate_results.md`. The command
returns exit code `1` when thresholds fail.

### Project Ergonomics

```powershell
.\.venv\Scripts\python -m igess.cli init --out my_economy
.\.venv\Scripts\python -m igess.cli doctor --project my_economy --config my_economy/economy.yaml --tables my_economy/luban_exports
.\.venv\Scripts\python -m igess.cli explain --run .tmp/run_a --event 0
```

`init` copies a minimal sample project, `doctor` checks common setup problems, and
`explain` traces an event from a run artifact back to source metadata and formula
details when available.

## v0.5 Agent Analyst

v0.5 adds an Agent-operated analysis loop. Agents can run, review, compare, and
recommend, while human designers keep ownership of bulk Luban/Excel table edits.
Agent commands write advice artifacts and YAML proposals; they do not apply table
changes.

Run the full advice workflow:

```powershell
.\.venv\Scripts\python -m igess.cli advise --config examples/shelldiver_v0/economy.yaml --tables examples/shelldiver_v0/luban_exports --scenario day_1_progression --out .tmp/advice
```

Review an existing run without rerunning simulation:

```powershell
.\.venv\Scripts\python -m igess.cli review-run --run .tmp/advice/run --out .tmp/review
```

Create and apply a YAML-only plan after human approval:

```powershell
.\.venv\Scripts\python -m igess.cli yaml-plan --config examples/shelldiver_v0/economy.yaml --intent "Add early regression gates" --out .tmp/yaml_plan
.\.venv\Scripts\python -m igess.cli yaml-apply --config examples/shelldiver_v0/economy.yaml --plan .tmp/yaml_plan/yaml_plan.json --approve --tables examples/shelldiver_v0/luban_exports
```

`advice.json` and `advice.md` include findings, artifact evidence, human-only
table recommendations, and YAML recommendations that require explicit approval.
The dashboard also exposes an Agent Analyst panel backed by the same advice
artifacts.

## v0.8 Human Edit Verification

v0.8 closes the loop after an Agent produces human-only table recommendations.
It reviews proposal artifacts, lets designers edit Luban/Excel source tables by
hand, then verifies whether the current exported table values match the
recommendation and still pass deterministic simulation checks.

Review an advice or tuning-style proposal:

```powershell
.\.venv\Scripts\python -m igess.cli review-proposal --proposal .tmp/advice/advice.json --out .tmp/proposal_review
```

Verify edits against already-exported tables:

```powershell
.\.venv\Scripts\python -m igess.cli verify-edits --config examples/shelldiver_v0/economy.yaml --tables examples/shelldiver_v0/luban_exports --proposal .tmp/advice/advice.json --scenario day_1_progression --out .tmp/verify
```

Verify edits from Luban source workbooks without modifying the source files:

```powershell
.\.venv\Scripts\python -m igess.cli verify-edits --config examples/shelldiver_v0/economy.yaml --datas data-tables/Datas --proposal .tmp/advice/advice.json --scenario day_1_progression --out .tmp/verify
```

Outputs include `proposal_review.json`, `proposal_review.md`,
`verification_report.json`, `verification_report.md`, and a fresh simulation run
under the verification output directory.

## Implemented Scope

Implemented now:

- YAML rules and Luban-export-style JSON tables.
- `resources`, `generators`, `upgrades`, and `constants` tables.
- Optional `milestones` and `prestige_layers` tables.
- Explicit `number_backend` and a `SimNumber` economy number wrapper.
- Safe AST formula compilation at load/build time.
- Config linting for ids, formulas, source types, modifier targets, profiles, policies, and deterministic seed.
- Resource dimension metadata plus semantic formula-context checks to catch accidental cost/output/prestige parameter mixing.
- Exponential generator costs, linear production, upgrade modifiers, and the standard modifier pipeline.
- `casual`, `optimizer`, and `explorer` player profiles in the sample config.
- `cheap_unlock_first`, `fastest_payback`, and `new_content_bias` behavior policies.
- Session-pattern-driven offline reward pulses.
- Milestone reward claims.
- Simple prestige conversion and configured resource reset.
- Fixed tick simulation plus analytic next-event stepping for stable intervals.
- JSON, CSV, and Markdown outputs.
- Payback, bottleneck, invalid-content, and overpowered-content analysis artifacts with source-row and formula traces.
- `run_manifest.json` with schema, scenario, model, profile, artifact, and override metadata.
- Static Web report generation with `report`.
- Local browser dashboard with run history.
- Run comparison with `compare`.
- Parameter scanning with `scan`.
- Regression gates with `gate`.
- Project initialization, diagnostics, and event explanation with `init`, `doctor`, and `explain`.
- Agent Analyst workflow with `advise`, `review-run`, `yaml-plan`, and `yaml-apply`.
- Human edit verification with `review-proposal` and `verify-edits`.
- Windows sample runner: `.\scripts\run_sample.ps1`.

Still deferred:

- Probability gates.
- Build delays.
- Complex offline caps.
- Multi-layer prestige balancing beyond the simple configurable layer included in the sample.

See [Luban Workflow](docs/luban-workflow.md) for the authoring/export contract.

Sample Luban-style source workbooks are under `data-tables/Datas`. They can be regenerated with:

```powershell
.\.venv\Scripts\python tools/create_sample_luban_sources.py
.\.venv\Scripts\python -m igess.cli export-tables --datas data-tables/Datas --out examples/shelldiver_v0/luban_exports
```

Analytic stepping can be exercised with:

```powershell
.\.venv\Scripts\python -m igess.cli run --config examples/shelldiver_v0/economy.yaml --tables examples/shelldiver_v0/luban_exports --scenario analytic_smoke --out .tmp/analytic
```
