# Agent Analyst v0.5 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development if subagents are available, or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship IGESS v0.5 as an Agent-operated numerical analysis workflow: Agents can run, review, compare, report, and recommend; humans keep ownership of bulk table edits; YAML changes are proposal-first and require explicit approval before application.

**Architecture:** Add an Agent Analyst layer above the existing workflow/reporting modules. The layer writes durable `advice.json` and `advice.md` artifacts, exposes CLI commands, and surfaces the same artifacts in the dashboard. YAML change planning is a separate, allowlisted workflow with explicit approval gates.

**Tech Stack:** Python 3.12, existing IGESS CLI/workflow/reporting modules, PyYAML, pytest, static HTML dashboard.

---

## Task 1: Define Advice Contract And Renderer

- [ ] Add tests for `advice.json` shape, stable schema version, markdown output, finding categories, table recommendations, YAML recommendations, and artifact path references.
- [ ] Implement an `igess.advice` module with typed dataclasses or plain serializable builders for:
  - findings
  - table recommendations
  - YAML recommendations
  - verification metadata
  - artifact paths
- [ ] Implement markdown rendering for a concise human report.
- [ ] Keep the contract deterministic and filesystem-portable by writing relative artifact paths where possible.

## Task 2: Analyze Existing Run Artifacts

- [ ] Add tests proving `review-run` can analyze a prepared run directory without creating a new simulation run.
- [ ] Read current run artifacts, including manifest, metrics, analysis, payback, and events when present.
- [ ] Generate at least one high-signal finding from sample artifacts.
- [ ] Generate table recommendations as `apply_mode: human_only`.
- [ ] Generate YAML recommendations as proposals only, never as direct edits.

## Task 3: Implement `igess advise`

- [ ] Add CLI tests for `igess advise`.
- [ ] Reuse existing workflow code to lint, run a scenario, and generate the static report.
- [ ] Support `--baseline` by writing compare artifacts and referencing them in advice.
- [ ] Write outputs under the requested directory:
  - `run/`
  - `report/`
  - `advice.json`
  - `advice.md`
  - optional `compare/`
  - optional `gate/`
- [ ] Preserve source table files exactly; test with hashes before and after the command.

## Task 4: Implement YAML Plan Workflow

- [ ] Add tests for `igess yaml-plan` that prove it writes a reviewable plan without editing the source YAML.
- [ ] Define a narrow plan format with:
  - schema version
  - intent
  - allowed YAML file path
  - allowlisted top-level section changes
  - expected effects
- [ ] Write `yaml_plan.json`, `yaml_plan.md`, and `economy.patch.yaml`.
- [ ] Keep generated plans conservative, favoring regression/advice scaffolding from intent instead of bulk table tuning.

## Task 5: Implement Safe YAML Apply

- [ ] Add tests for `igess yaml-apply`.
- [ ] Require explicit `--approve` for real application.
- [ ] Refuse plans that touch Excel, Luban export tables, `data-tables`, or disallowed YAML sections.
- [ ] Apply only supported YAML merge operations to the requested YAML config.
- [ ] Run lint after applying and report failures clearly.

## Task 6: Add Dashboard Agent Analyst Panel

- [ ] Add dashboard tests for an Agent Analyst section.
- [ ] Show latest advice status, main findings, table recommendations, YAML recommendations, and artifact links when available.
- [ ] Keep dashboard actions deterministic wrappers around existing command behavior.
- [ ] Avoid adding hidden mutation paths for tables.

## Task 7: Docs, Versioning, And Verification

- [ ] Update README and docs for `advise`, `review-run`, `yaml-plan`, and `yaml-apply`.
- [ ] Update package version to `0.5.0`.
- [ ] Run full pytest in the feature worktree.
- [ ] Commit feature branch.
- [ ] Merge back to `main`.
- [ ] Run full pytest again on `main`.

## Safety Invariants

- [ ] No Agent command writes `.xlsx`, `.xls`, `.csv`, `.tsv`, or Luban table source files.
- [ ] YAML plans are generated before application and require human approval.
- [ ] Every recommendation cites an artifact, metric, row, or section.
- [ ] Failed lint/run/gate steps produce explicit status in advice artifacts.
- [ ] Dashboard displays advice; it does not become an implicit data editor.
