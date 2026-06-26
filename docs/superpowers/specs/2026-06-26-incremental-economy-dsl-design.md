# Incremental Economy DSL Design

## Context

`E:\IGESS` starts as an empty repository. The authoritative requirements are in `E:\雨林星\立项\炸鱼佬传说\增量经济模拟DSL交接文档.md`, especially section 13, `v0.1 最小实现范围`.

This design treats v0.1 as a local Python command line simulator for Cookie Clicker / idle / incremental economy analysis. It reads YAML system rules and Luban-export-style tabular data, validates configuration before simulation, builds a deterministic economy model, runs fixed-tick simulations for multiple player profiles, and writes machine-readable timelines plus a Markdown report.

## Approaches Considered

1. **Python CLI with JSON/CSV fixtures and YAML rules**
   - Best fit for the handoff and this empty repo.
   - Easy to test, easy for AI agents to iterate, and good for deterministic local analysis.
   - Recommended for v0.1.

2. **TypeScript simulator with `break_infinity.js`**
   - Strong ecosystem match for incremental-game number handling.
   - More setup cost in this empty Windows repo and less natural for analysis/reporting.

3. **Spreadsheet-first prototype**
   - Useful for quick curves, but violates the handoff warning against one-off scripts and weakens the DSL/model boundary.

## Scope

v0.1 includes:

- Python 3.11+ CLI project.
- YAML model/rules/scenario loading.
- Luban-export-style JSON table loading for `resources`, `generators`, `upgrades`, and `constants`.
- Stable internal dataclasses for model definitions and simulation state.
- Explicit `number_backend`, with `bignum_log` enabled through a `SimNumber` wrapper.
- Safe formula compilation from YAML expressions at load/build time.
- Static config linting for id references, formula parameters, modifier targets, source types, policy/profile references, and deterministic seed declaration.
- Exponential generator costs and linear generator production.
- Modifier pipeline: `(base + flat) * (1 + add_pct) * product(mult) ^ exp`.
- Three behavior policies: `cheap_unlock_first`, `fastest_payback`, `new_content_bias`.
- `fastest_payback` lookahead depth 1 by adding immediately-unlocked upgrade value into candidate scoring.
- Three player profiles in the sample: `casual`, `optimizer`, `explorer`.
- Fixed tick simulation with an `analytic_leap` interface stub reserved for later.
- Deterministic JSON or CSV timeline output.
- Markdown analysis report.
- Windows PowerShell entrypoint.

v0.1 defers:

- Multi-layer prestige implementation.
- Probability gates.
- Build delays.
- Complex offline reward caps.
- Chart visualization.

## Architecture

The package is named `igess`.

- `numbers.py`: `SimNumber` and numeric backend helpers. Business logic stores resources, costs, outputs, modifiers, and comparisons through this type.
- `formula.py`: safe expression parser/compiler using Python AST. It supports arithmetic, `pow`, `floor`, `ceil`, `min`, `max`, and `log10`; it rejects arbitrary names, attributes, imports, calls, and runtime `eval`.
- `schema.py`: dataclasses for YAML config, Luban-exported rows, player profiles, scenarios, policies, model definitions, state, events, and timeline rows.
- `loader.py`: reads YAML and JSON tables, normalizes stable ordering, and creates raw config objects.
- `linter.py`: validates references and deterministic requirements before model building.
- `builder.py`: compiles formulas and builds an `EconomyModel`.
- `modifiers.py`: computes modifier stacks for generator output targets.
- `policy.py`: chooses purchase actions for the three v0.1 behavior policies.
- `time_engine.py`: exposes fixed tick stepping and an explicit `analytic_leap` placeholder interface.
- `simulator.py`: runs scenarios/profile combinations, applies production, purchases, unlocks, and records timelines/events.
- `analyzer.py`: creates summary metrics and Markdown report content.
- `outputs.py`: writes deterministic JSON/CSV/Markdown with stable ordering and LF newlines.
- `cli.py`: command line entrypoint.

Sample configuration lives under `examples/shelldiver_v0/`:

- `economy.yaml`
- `luban_exports/resources.json`
- `luban_exports/generators.json`
- `luban_exports/upgrades.json`
- `luban_exports/constants.json`

## Data Flow

1. CLI receives `--config`, `--tables`, `--scenario`, and `--out`.
2. `ConfigLoader` reads YAML and Luban-export JSON tables.
3. `ConfigLinter` checks all references and formula targets.
4. `ModelBuilder` compiles formula ASTs and constructs `EconomyModel`.
5. `Simulator` runs every requested profile for the scenario using fixed ticks.
6. `PolicyEngine` chooses purchases after each production step.
7. `Simulator` applies offline reward pulses, milestone rewards, and simple prestige/reset when configured.
8. `Analyzer` summarizes output.
9. `outputs.py` writes deterministic timeline/report artifacts.

## Error Handling

Configuration errors fail before simulation and include actionable messages with ids, fields, and table/config section names. Formula compilation errors identify the formula id and rejected AST/name/function. CLI exits non-zero for invalid configuration or missing files.

Simulation avoids hidden randomness. A scenario can be rerun byte-for-byte with the same config, table data, and seed because outputs are sorted, serialized with stable field order, and written with LF line endings.

## Testing

The implementation follows TDD:

- `tests/test_numbers.py`: `SimNumber` large-number arithmetic, comparisons, formatting, and the `1e18 - 10` precision trap.
- `tests/test_formula.py`: safe compile/evaluate behavior and rejection of unsafe expressions.
- `tests/test_linter_builder.py`: successful sample model build plus id/formula/modifier validation failures.
- `tests/test_modifiers_policy.py`: modifier pipeline result and policy ordering, including fastest-payback lookahead.
- `tests/test_simulator_outputs.py`: deterministic run, JSON/CSV/Markdown output, profile differences, and CLI smoke test.

Full verification command:

```powershell
python -m pytest
python -m igess.cli run --config examples/shelldiver_v0/economy.yaml --tables examples/shelldiver_v0/luban_exports --scenario day_1_progression --out .tmp/sim
python -m igess.cli lint --config examples/shelldiver_v0/economy.yaml --tables examples/shelldiver_v0/luban_exports
```
