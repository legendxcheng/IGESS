# IGESS Roadmap v0.2-v0.4

This document plans the next three IGESS releases after the v0.1 simulation core.
The guiding goal is to turn IGESS from a developer CLI into a practical economy
design tool that a designer can run, inspect, compare, and iterate on without
reading raw JSON or CSV files first.

## Current Baseline

v0.1 provides the simulation foundation:

- Luban-style Excel source tables under `data-tables/Datas`.
- Exported JSON tables under `examples/shelldiver_v0/luban_exports`.
- YAML model configuration and scenarios.
- Deterministic linting, simulation, analysis, traces, and CSV/JSON/Markdown outputs.
- Fixed tick and analytic stepping modes.
- CLI-first workflow: `export-tables`, `lint`, and `run`.

The main usability gap is that results are still artifact-oriented. A designer
has to open multiple files, mentally connect timeline data to events and payback
analysis, and manually compare runs.

## Product Direction

IGESS should evolve around three increasingly usable loops:

1. **Read one run clearly**: a generated Web report explains what happened.
2. **Run and inspect locally**: a local dashboard removes command-line friction.
3. **Compare and guard changes**: regression and scanning tools make tuning safer.

The system should remain local-first, deterministic, and easy to commit into a
game repository. Web features should improve visibility without requiring cloud
services or a database.

## Version Summary

| Version | Theme | Main User Outcome |
| --- | --- | --- |
| v0.2 | Static Web reports | After running a scenario, open one report folder and understand progression, events, payback, and warnings. |
| v0.3 | Local dashboard | Choose scenarios and profiles in a browser, run simulations, browse run history, and open reports without hand-written commands. |
| v0.4 | Tuning workflow | Compare runs, scan parameters, initialize projects, diagnose setup, and enforce regression thresholds. |

## v0.2 Static Web Report

### Goal

Generate a self-contained Web report from an existing simulation output directory.
The first report should require no server and should work by opening `index.html`
from disk.

### Proposed CLI

```powershell
igess report --run .tmp/sim --out .tmp/report
```

Optional later flags:

```powershell
igess report --run .tmp/sim --out .tmp/report --title "Day 1 Economy"
igess run ... --out .tmp/sim --report .tmp/report
```

### Report Contents

- **Overview**: scenario, duration, time mode, profiles, model id, generated time,
  and input/output file summary.
- **Resource curves**: profile-by-profile resource trends from `timeline.csv` or
  `timeline.json`.
- **Event timeline**: purchases, unlocks, milestones, prestige events, and offline
  pulses with profile filters.
- **Payback table**: sortable generator and upgrade payback data from `payback.csv`.
- **Analysis panels**: bottlenecks, invalid content, overpowered content, and
  high-signal warnings from `analysis.json`.
- **Trace view**: show source rows and formula traces behind a selected warning,
  event, or payback entry when trace data is available.

### UX Principles

- The first screen should answer: "Is this economy behaving roughly as intended?"
- Charts should compare player profiles by default.
- Tables should preserve raw values, but also format large numbers using the
  existing `SimNumber` display conventions where possible.
- Warnings should be grouped by severity and point back to source table rows.
- The report should be useful offline and easy to share as a folder.

### Technical Shape

- Add a report-generation module under `src/igess/reporting`.
- Add `report` to `src/igess/cli.py`.
- Prefer no frontend build system for v0.2.
- Generate static HTML, CSS, and JavaScript assets from templates.
- Use lightweight SVG or Canvas charts implemented locally to avoid CDN/runtime
  dependency risk.
- Treat existing simulation outputs as the report API. If the report needs more
  metadata, add a small `run_manifest.json` to future `run` outputs while keeping
  backward compatibility with current outputs.

### Acceptance Criteria

- `igess report --run .tmp/sim --out .tmp/report` creates `index.html` and assets.
- Opening the report shows at least one resource chart, one event timeline, one
  payback table, and analysis warnings.
- Missing optional files degrade gracefully with a visible "not available" state.
- The report works on Windows from a local file path.
- Tests cover report data loading, empty/missing artifact behavior, and generated
  file existence.

### Non-Goals

- Editing economy data in the browser.
- Running simulations from the browser.
- Multi-run comparison.
- User accounts, cloud publishing, or remote hosting.

## v0.3 Local Dashboard

### Goal

Provide a local browser UI for selecting models, running scenarios, opening reports,
and browsing recent runs. This removes most command-line friction while preserving
the deterministic local workflow.

### Proposed CLI

```powershell
igess dashboard
igess dashboard --project E:\IGESS
igess dashboard --host 127.0.0.1 --port 8765
```

### Core Screens

- **Project Home**: detected config files, table export path, recent runs, and
  environment status.
- **Run Scenario**: scenario picker, profile selector, output directory choice,
  time mode display, and run button.
- **Run Detail**: embedded v0.2 report plus links to raw artifacts.
- **Run History**: list of prior runs with scenario, profiles, duration, status,
  created time, and report link.
- **Diagnostics**: lint status, table export status, Python/package version, and
  common repair hints.

### Technical Shape

- Add an optional `web` extra in `pyproject.toml`.
- Use a small local HTTP server. FastAPI/Uvicorn is the likely default because it
  gives clear routing and typed request/response behavior, but this should remain
  an optional dependency.
- Reuse the simulation and report modules directly instead of shelling out to the
  CLI.
- Store dashboard-created runs in a predictable local directory such as
  `.igess/runs/<timestamp>-<scenario>`.
- Keep the frontend simple. A server-rendered HTML app or static JS app is enough
  until the UI needs richer state.

### Acceptance Criteria

- `igess dashboard` starts a local server and prints the URL.
- The dashboard can lint the sample project, run `day_1_progression`, and open the
  generated report.
- Failed runs show the lint or simulation error clearly in the browser.
- Run history survives server restart because it is based on filesystem artifacts.
- Tests cover server route behavior and dashboard service-layer orchestration.

### Non-Goals

- Concurrent multi-user operation.
- Long-running background job infrastructure beyond a simple local task model.
- Browser-based Excel editing.

## v0.4 Tuning Workflow

### Goal

Make IGESS useful for repeated balance iteration, not just one-off simulation.
v0.4 should help a designer compare changes, discover sensitive parameters, and
catch accidental regressions before changes land.

### Feature Areas

#### Run Comparison

Proposed CLI:

```powershell
igess compare --base .igess/runs/run_a --candidate .igess/runs/run_b --out .tmp/compare
```

Expected output:

- Delta report for resource curves, unlock times, purchase counts, prestige timing,
  and payback changes.
- Highlighted regressions such as "optimizer reaches generator_3 35% later".
- Static comparison report generated with the v0.2 report system.

#### Parameter Scanning

Proposed CLI:

```powershell
igess scan --config examples/shelldiver_v0/economy.yaml --tables examples/shelldiver_v0/luban_exports --scenario day_1_progression --param generators.mine_1.growth=1.12..1.25:0.01 --out .tmp/scan
```

Expected output:

- Multiple deterministic runs generated from parameter overrides.
- Summary table of key metrics per parameter value.
- Optional report view for selecting candidate values.

#### Regression Gates

Proposed config concept:

```yaml
regression_gates:
  day_1_progression:
    max_unlock_delay_pct:
      generator.mine_3: 20
    max_payback_seconds:
      upgrade.net_boost_1: 600
    min_prestige_gain:
      optimizer: 1
```

Expected behavior:

- `igess gate --base <run> --candidate <run> --config <config>` exits non-zero
  when thresholds are violated.
- Gate results can be consumed by CI later, but v0.4 should remain useful locally.

#### Project Ergonomics

Commands to consider:

```powershell
igess init --template incremental-basic --out my_economy
igess doctor --project .
igess explain --run .tmp/sim --event <event_id>
```

Expected improvements:

- Faster new-project setup.
- Better diagnostics for missing tables, mismatched schema, stale exports, and
  unsupported formulas.
- Human-readable explanation path from report warning back to table row and formula.

### Technical Shape

- Introduce a stable run metadata model so comparison and gates do not infer too
  much from filenames.
- Add metric extraction utilities that convert raw timeline/event/payback data into
  comparable scenario metrics.
- Extend the report generator to support comparison and scan views.
- Keep parameter overrides explicit and traceable. Generated runs should record the
  override set that produced them.

### Acceptance Criteria

- A designer can compare two runs and identify major progression differences in
  one generated report.
- A designer can scan at least one numeric table/config parameter over a range and
  see metric changes.
- Regression gates produce deterministic pass/fail output suitable for local scripts.
- `igess doctor` gives actionable diagnostics for the sample project.

## Suggested Implementation Order

1. Add run manifest output to `igess run`.
2. Implement v0.2 report data loading and validation.
3. Implement v0.2 static report generation.
4. Add report command tests and sample report documentation.
5. Implement dashboard service layer around existing export/lint/run/report flows.
6. Add dashboard UI and local server command.
7. Add run registry/history.
8. Implement metric extraction for comparisons.
9. Implement compare reports.
10. Implement parameter scan overrides and scan summaries.
11. Implement regression gates.
12. Add `init`, `doctor`, and `explain` ergonomics commands.

## Testing Strategy

- Preserve deterministic CLI tests as the backbone.
- Add golden-ish tests for generated report structure without snapshotting large
  HTML blobs.
- Test report loaders with missing, empty, and malformed artifacts.
- Test dashboard service methods without needing a browser for most coverage.
- Use browser-level checks only for high-value UI paths once the dashboard exists.
- For compare/scan/gate, use small synthetic runs so tests remain fast.

## Risks and Mitigations

- **Report complexity grows too quickly**: keep v0.2 read-only and single-run only.
- **Frontend build tooling slows iteration**: avoid a build system until dashboard
  interaction truly needs it.
- **Artifacts become inconsistent**: add `run_manifest.json` and typed loader
  validation before building more UI.
- **Parameter scans hide provenance**: record every override in each generated run.
- **Dashboard becomes a separate product too early**: reuse CLI service modules and
  keep file artifacts as the source of truth.

## Release Exit Criteria

### v0.2

- Static report command implemented.
- Sample run can generate and open a readable report.
- Report docs included in `README.md` or a dedicated docs page.
- All tests pass.

### v0.3

- Local dashboard command implemented.
- Sample project can be linted, run, and viewed from the browser.
- Run history works from filesystem artifacts.
- All tests pass, including dashboard service tests.

### v0.4

- Compare, scan, and gate workflows implemented for at least the sample project.
- `doctor` provides useful local diagnostics.
- Documentation covers a full tuning loop: edit table, export, lint, run, report,
  compare, and gate.
- All tests pass.
