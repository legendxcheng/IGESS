# Incremental Economy DSL Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the v0.1 Python CLI simulator described by `E:\雨林星\立项\炸鱼佬传说\增量经济模拟DSL交接文档.md`.

**Architecture:** A small Python package, `igess`, separates config loading, linting, formula compilation, model building, policy selection, simulation, analysis, and deterministic output. Sample YAML plus Luban-export-style JSON fixtures prove the full flow.

**Tech Stack:** Python 3.11+, standard library, PyYAML, pytest.

---

## Chunk 1: Project Foundation

### Task 1: Scaffolding and Sample Data

**Files:**
- Create: `pyproject.toml`
- Create: `README.md`
- Create: `src/igess/__init__.py`
- Create: `scripts/run_sample.ps1`
- Create: `examples/shelldiver_v0/economy.yaml`
- Create: `examples/shelldiver_v0/luban_exports/resources.json`
- Create: `examples/shelldiver_v0/luban_exports/generators.json`
- Create: `examples/shelldiver_v0/luban_exports/upgrades.json`
- Create: `examples/shelldiver_v0/luban_exports/constants.json`

- [ ] Write sample config and table fixtures that include fish, fisherman, boat, net, and three player profiles.
- [ ] Add project metadata and a PowerShell sample runner.
- [ ] Keep fixtures deterministic and sorted by id.

### Task 2: Core Tests First

**Files:**
- Create: `tests/test_numbers.py`
- Create: `tests/test_formula.py`
- Create: `tests/test_linter_builder.py`
- Create: `tests/test_modifiers_policy.py`
- Create: `tests/test_simulator_outputs.py`

- [ ] Write failing tests for all v0.1 behavioral claims.
- [ ] Run `python -m pytest` and confirm tests fail because modules do not exist.

## Chunk 2: Core Model

### Task 3: Numbers and Formula Engine

**Files:**
- Create: `src/igess/numbers.py`
- Create: `src/igess/formula.py`

- [ ] Implement `SimNumber` with `bignum_log` semantics, stable parsing, formatting, comparison, and arithmetic.
- [ ] Implement AST-based formula compilation and reject unsafe Python syntax.
- [ ] Run `python -m pytest tests/test_numbers.py tests/test_formula.py`.

### Task 4: Schema, Loader, Linter, Builder

**Files:**
- Create: `src/igess/schema.py`
- Create: `src/igess/loader.py`
- Create: `src/igess/linter.py`
- Create: `src/igess/builder.py`

- [ ] Implement dataclasses for config, rows, profiles, scenarios, model, state, and events.
- [ ] Implement YAML and JSON table loading.
- [ ] Implement linter checks for required seed, number backend, ids, source types, formula args, profile policies, and modifier targets.
- [ ] Build compiled `EconomyModel`.
- [ ] Run `python -m pytest tests/test_linter_builder.py`.

## Chunk 3: Simulation

### Task 5: Modifiers, Policies, and Time

**Files:**
- Create: `src/igess/modifiers.py`
- Create: `src/igess/policy.py`
- Create: `src/igess/time_engine.py`

- [ ] Implement modifier pipeline exactly as `(base + flat) * (1 + add_pct) * product(mult) ^ exp`.
- [ ] Implement `cheap_unlock_first`, `fastest_payback`, and `new_content_bias`.
- [ ] Implement `fastest_payback` lookahead depth 1 by considering newly unlocked immediate upgrade value.
- [ ] Add a fixed-tick time engine plus an `analytic_leap` unsupported placeholder.
- [ ] Run `python -m pytest tests/test_modifiers_policy.py`.

### Task 6: Simulator, Analyzer, Outputs, CLI

**Files:**
- Create: `src/igess/simulator.py`
- Create: `src/igess/analyzer.py`
- Create: `src/igess/outputs.py`
- Create: `src/igess/cli.py`

- [ ] Run fixed tick simulation for each scenario/profile.
- [ ] Apply generator production, source efficiency, unlocks, policy purchases, and events.
- [ ] Record timeline rows and purchase/unlock events.
- [ ] Write deterministic JSON/CSV timelines and Markdown analysis reports.
- [ ] Add `lint` and `run` CLI commands.
- [ ] Run `python -m pytest tests/test_simulator_outputs.py`.

## Chunk 4: Verification

### Task 7: Full Verification and Documentation

**Files:**
- Modify: `README.md`

- [ ] Run `python -m pytest`.
- [ ] Run `python -m igess.cli lint --config examples/shelldiver_v0/economy.yaml --tables examples/shelldiver_v0/luban_exports`.
- [ ] Run `python -m igess.cli run --config examples/shelldiver_v0/economy.yaml --tables examples/shelldiver_v0/luban_exports --scenario day_1_progression --out .tmp/sim`.
- [ ] Inspect output files for deterministic timeline and Markdown report.
- [ ] Update README with actual commands and scope.
