# Standard RNG Simulation Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic Roblox-style rarity-score RNG simulator and CLI output pipeline.

**Architecture:** Keep RNG simulation independent from the existing incremental run loop. Extend config/schema/loading/validation just enough to carry `rng_tables`, `rng_scenarios`, and profile `luck`, then implement RNG behavior in focused `rng.py` and artifact writing in `rng_outputs.py`.

**Tech Stack:** Python 3.11, stdlib `random`, `math`, `hashlib`, `json`, `csv`, existing PyYAML config loader, pytest.

---

## Chunk 1: Config And Algorithm Core

### Task 1: Schema, Loader, Builder, And Linter

**Files:**
- Modify: `src/igess/schema.py`
- Modify: `src/igess/loader.py`
- Modify: `src/igess/builder.py`
- Modify: `src/igess/linter.py`
- Test: `tests/test_rng.py`

- [ ] **Step 1: Write failing config tests**

Add tests that load a config containing `rng_tables`, `rng_scenarios`, and profile `luck`, then assert the built model exposes these values. Add tests for invalid RNG algorithm and non-positive denominators.

- [ ] **Step 2: Run tests to verify RED**

Run: `python -m pytest tests/test_rng.py -v`
Expected: fail because RNG schema fields do not exist yet.

- [ ] **Step 3: Implement minimal config support**

Add dataclasses `RngRarity`, `RngTable`, and `RngScenario`. Add `luck` to `PlayerProfile`. Add `rng_tables` and `rng_scenarios` to `Rules` and `EconomyModel`. Parse optional YAML sections in `loader.py`, validate them in `linter.py`, and pass them through in `builder.py`.

- [ ] **Step 4: Run tests to verify GREEN**

Run: `python -m pytest tests/test_rng.py -v`
Expected: pass for config tests.

### Task 2: Rarity-Score Roll Algorithm

**Files:**
- Create: `src/igess/rng.py`
- Test: `tests/test_rng.py`

- [ ] **Step 1: Write failing algorithm tests**

Assert `select_rarity_by_log_power` returns mythic for luck `5.65` and `u=0.0002`, and not secret. Assert theoretical probabilities are clamped to `1`.

- [ ] **Step 2: Run tests to verify RED**

Run: `python -m pytest tests/test_rng.py -v`
Expected: fail because `igess.rng` does not exist.

- [ ] **Step 3: Implement minimal algorithm**

Create pure helpers for stable rarity sorting, log-space selection, and probability calculation.

- [ ] **Step 4: Run tests to verify GREEN**

Run: `python -m pytest tests/test_rng.py -v`
Expected: pass.

## Chunk 2: Simulation And Artifacts

### Task 3: Monte Carlo Simulator

**Files:**
- Modify: `src/igess/rng.py`
- Test: `tests/test_rng.py`

- [ ] **Step 1: Write failing simulation tests**

Assert two runs of the same RNG scenario produce identical summaries and distributions. Assert first-hit roll indexes are recorded for reached rarities.

- [ ] **Step 2: Run tests to verify RED**

Run: `python -m pytest tests/test_rng.py -v`
Expected: fail because `RngSimulator` is not implemented.

- [ ] **Step 3: Implement simulator**

Use `random.Random` with a stable seed derived from model seed, scenario id, profile id, and trial index. Record rarity counts, first-hit rolls, best rarity per trial, and high-rarity events at or above `event_threshold`.

- [ ] **Step 4: Run tests to verify GREEN**

Run: `python -m pytest tests/test_rng.py -v`
Expected: pass.

### Task 4: Output Writer And CLI

**Files:**
- Create: `src/igess/rng_outputs.py`
- Modify: `src/igess/cli.py`
- Test: `tests/test_rng.py`

- [ ] **Step 1: Write failing CLI/artifact tests**

Invoke `python -m igess.cli rng-run --config ... --scenario ... --out ...` and assert all RNG artifacts exist with deterministic LF output.

- [ ] **Step 2: Run tests to verify RED**

Run: `python -m pytest tests/test_rng.py -v`
Expected: fail because `rng-run` is not registered.

- [ ] **Step 3: Implement writer and CLI**

Write JSON/CSV/Markdown artifacts with stable ordering. Add `rng-run` parser and command handling.

- [ ] **Step 4: Run tests to verify GREEN**

Run: `python -m pytest tests/test_rng.py -v`
Expected: pass.

## Chunk 3: Sample And Verification

### Task 5: Sample Config And Docs

**Files:**
- Modify: `examples/shelldiver_v0/economy.yaml`
- Modify: `README.md`

- [ ] **Step 1: Add sample RNG config**

Add an `aura_roll` table and `aura_baseline` scenario using the rarity denominators from the approved design.

- [ ] **Step 2: Document usage**

Add a concise README section with the `rng-run` command and artifact list.

### Task 6: Final Verification

**Files:**
- Test: full repository

- [ ] **Step 1: Run focused tests**

Run: `python -m pytest tests/test_rng.py -v`
Expected: all RNG tests pass.

- [ ] **Step 2: Run full tests**

Run: `python -m pytest`
Expected: full suite passes.

- [ ] **Step 3: Run CLI smoke command**

Run: `python -m igess.cli rng-run --config examples/shelldiver_v0/economy.yaml --scenario aura_baseline --out .tmp/rng`
Expected: command exits 0 and writes RNG artifacts.
