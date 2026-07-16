# Activity Output Structure Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add player activities with profile-specific behavior weights and multi-resource activity outputs.

**Architecture:** Keep generators as purchasable automatic production. Add `activities` as player behavior channels and `activity_outputs` as one-to-many resource output rows. Profiles choose behavior mix through normalized `activity_weights`, while existing `source_efficiency` still scales output by source type.

**Tech Stack:** Python dataclasses, YAML/JSON loaders, existing Luban-style workbook exporter, pytest.

---

## Chunk 1: Runtime Model

### Task 1: Schema And Loading

**Files:**
- Modify: `src/igess/schema.py`
- Modify: `src/igess/loader.py`
- Modify: `src/igess/builder.py`
- Test: `tests/test_linter_builder.py`

- [x] Write a failing test proving sample config loads `activities`, `activity_outputs`, and profile `activity_weights`.
- [x] Run the focused test and verify it fails because fields are missing.
- [x] Add `ActivityRow`, `ActivityOutputRow`, `PlayerProfile.activity_weights`, `RawConfig.activities`, `RawConfig.activity_outputs`, and `EconomyModel` dictionaries.
- [x] Load optional `activities.json` and `activity_outputs.json` from table exports.
- [x] Build activity dictionaries in `ModelBuilder`.
- [x] Run the focused test and verify it passes.

### Task 2: Validation

**Files:**
- Modify: `src/igess/linter.py`
- Test: `tests/test_linter_builder.py`

- [x] Write failing tests for unknown activity source type, unknown activity output resource, unknown activity output activity, and unknown profile activity weight.
- [x] Run focused tests and verify they fail for missing validation.
- [x] Validate activity conditions, source types, output references, and non-negative profile weights.
- [x] Run focused tests and verify they pass.

## Chunk 2: Simulation

### Task 3: Activity Production

**Files:**
- Modify: `src/igess/simulator.py`
- Modify: `src/igess/schema.py`
- Test: `tests/test_simulator_outputs.py`

- [x] Write a failing simulation test where one activity produces two resources and profile weights change output mix.
- [x] Run the focused test and verify it fails because activities do not produce.
- [x] Add `SimulationState.unlocked_activities`.
- [x] Add activity CPS to `_resource_cps`.
- [x] Add activity production to `_produce`.
- [x] Normalize unlocked activity weights per profile.
- [x] Emit `unlock_activity` events in `_update_unlocks`.
- [x] Run the focused test and verify it passes.

## Chunk 3: Sample Data And Workflow

### Task 4: Sample Tables

**Files:**
- Modify: `examples/shelldiver_v0/economy.yaml`
- Modify: `tools/create_sample_luban_sources.py`
- Generated: `data-tables/Datas/*.xlsx`
- Generated: `examples/shelldiver_v0/luban_exports/*.json`
- Modify: `tests/test_luban_sources.py`
- Modify: `tests/test_linter_builder.py`

- [x] Add `activity_weights` to sample profiles.
- [x] Register `activities` and `activity_outputs` in `__tables__.xlsx`.
- [x] Generate activity source workbooks with marker rows.
- [x] Export JSON tables from workbooks.
- [x] Update tests that assert registered/exported table count or sample resources.
- [x] Run Luban source tests and verify generated JSON matches checked-in exports.

## Chunk 4: Verification

### Task 5: Full Verification

**Files:**
- No production edits expected.

- [x] Run focused tests: `python -m pytest tests/test_linter_builder.py tests/test_simulator_outputs.py tests/test_luban_sources.py`.
- [x] Run full suite: `python -m pytest`.
- [x] Run CLI smoke: `python -m igess.cli lint --config examples/shelldiver_v0/economy.yaml --tables examples/shelldiver_v0/luban_exports`.
- [x] Summarize behavior, changed files, and verification results.

Verification note: full suite reported two failures in external `E:\stone-oasis`
data-dependent tests; the repo-local suite excluding those two files passed.
