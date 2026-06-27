# IGESS Roadmap v0.5 Agent Analyst

This document defines the v0.5 direction after IGESS v0.4. The goal is to make
IGESS easier for an Agent to operate on behalf of a designer while preserving a
clear authorship boundary: humans own source data tables, and Agents operate the
simulation, analysis, reporting, and recommendation loop.

## Product Principle

v0.5 should turn IGESS into an **Agent-operated numerical analysis workflow**, not
an Agent-authored data editor.

The intended division of labor is:

- **Human**: edits Luban/Excel source tables and approves any structural YAML
  changes.
- **Agent**: runs export/lint/simulate/report/compare/scan/gate workflows,
  interprets results, and produces optimization recommendations.
- **IGESS**: provides deterministic commands, artifacts, reports, and evidence
  that make the Agent's reasoning auditable.

## Permission Boundary

### Agent Must Not Modify Data Tables

The Agent must not directly edit:

- `data-tables/Datas/resources.xlsx`
- `data-tables/Datas/generators.xlsx`
- `data-tables/Datas/upgrades.xlsx`
- `data-tables/Datas/constants.xlsx`
- `data-tables/Datas/milestones.xlsx`
- `data-tables/Datas/prestige_layers.xlsx`
- Any other bulk Luban/Excel source table.

For table data, the Agent may only produce human-readable recommendations:

```text
Recommended table change
Table: generators.xlsx
Row: fisherman
Field: cost_growth
Current value: 1.15
Suggested range: 1.12 - 1.14
Reason: Casual profile has long early purchase gaps.
Verification: edit the table, export, then rerun igess advise.
```

### Agent May Modify YAML Only With Human Authorization

The Agent may propose and, after explicit human approval, apply changes to
`economy.yaml` or other YAML configuration files.

Allowed YAML change areas:

- Scenario definitions.
- Player profiles.
- Behavior policies.
- Session patterns.
- Formula definitions.
- Generator type / modifier pipeline definitions.
- Regression gates.
- Scan presets.
- Report/advice configuration.

The preferred workflow is:

1. Agent proposes a YAML patch.
2. Human reviews and approves it.
3. Agent applies the patch.
4. Agent runs lint, simulation, report, compare, and gate checks.
5. Agent summarizes the outcome and any follow-up table recommendations.

## v0.5 Theme

**Agent Analyst Workflow**

The Agent should behave like a numerical analyst:

- It reads the current project state.
- It runs the right deterministic IGESS commands.
- It compares current results against previous runs or targets.
- It explains major bottlenecks and regressions.
- It suggests what the human should change in tables or YAML.
- It never silently mutates bulk source tables.

## Proposed Commands

### `igess advise`

Primary v0.5 command. Runs a full analysis loop and produces an advice package.

```powershell
igess advise --config examples/shelldiver_v0/economy.yaml --tables examples/shelldiver_v0/luban_exports --scenario day_1_progression --out .tmp/advice
```

Expected outputs:

- `advice.json`: structured findings, evidence, and recommendations.
- `advice.md`: human-readable analysis report.
- `run/`: the simulation output.
- `report/`: static Web report.
- `scan/`: optional scan outputs when scan presets are configured.
- `gate/`: gate results when regression gates are configured.

Responsibilities:

- Validate config and table exports.
- Run the requested scenario.
- Generate the static report.
- Extract metrics.
- Evaluate gate status when gates exist.
- Detect high-signal problems.
- Generate table recommendations without applying them.
- Generate YAML recommendations as patch proposals without applying them.

### `igess advise --baseline`

Compares a new run against a baseline run.

```powershell
igess advise --config examples/shelldiver_v0/economy.yaml --tables examples/shelldiver_v0/luban_exports --scenario day_1_progression --baseline .igess/runs/previous --out .tmp/advice
```

Responsibilities:

- Run the current scenario.
- Compare current run against baseline.
- Highlight improvements and regressions.
- Explain whether the latest human table edits moved metrics in the intended
  direction.

### `igess yaml-plan`

Generates a YAML-only change proposal from a user intent. It must not edit files.

```powershell
igess yaml-plan --config examples/shelldiver_v0/economy.yaml --intent "Add a strict early-game gate for first prestige timing" --out .tmp/yaml_plan
```

Expected outputs:

- `yaml_plan.json`: machine-readable patch proposal.
- `yaml_plan.md`: explanation of proposed changes and expected effects.
- `economy.patch.yaml`: proposed YAML patch or replacement fragments.

This command is for structural logic changes, not bulk data tuning.

### `igess yaml-apply`

Applies a previously generated YAML plan after human approval.

```powershell
igess yaml-apply --config examples/shelldiver_v0/economy.yaml --plan .tmp/yaml_plan/yaml_plan.json
```

Responsibilities:

- Verify the plan only touches allowed YAML sections.
- Refuse to touch Excel/Luban table files.
- Create a backup or Git-friendly diff.
- Run lint after applying.

### `igess review-run`

Analyzes an existing run directory without rerunning the simulation.

```powershell
igess review-run --run .tmp/run --out .tmp/review
```

Responsibilities:

- Read `run_manifest.json`, timeline, events, analysis, and payback data.
- Generate explanation and recommendations from existing artifacts.
- Useful when a human or CI already produced a run.

## Advice Model

`advice.json` should be the stable output contract for Agents and dashboards.

Suggested top-level shape:

```json
{
  "schema_version": 1,
  "scenario_id": "day_1_progression",
  "status": "needs_attention",
  "summary": "...",
  "findings": [],
  "table_recommendations": [],
  "yaml_recommendations": [],
  "verification": {},
  "artifact_paths": {}
}
```

### Finding

```json
{
  "id": "early_gap.casual.001",
  "severity": "warning",
  "category": "progression_gap",
  "profile_id": "casual",
  "message": "Casual profile has a 92s purchase gap in early progression.",
  "evidence": {
    "metric": "bottleneck_gap_seconds",
    "actual": "92",
    "expected": "<=60",
    "source": "analysis.json"
  }
}
```

### Table Recommendation

```json
{
  "id": "table.generators.fisherman.cost_growth",
  "kind": "table_recommendation",
  "table": "generators",
  "workbook": "generators.xlsx",
  "row_id": "fisherman",
  "field": "cost_growth",
  "current_value": "1.15",
  "suggested_value": "1.12 - 1.14",
  "reason": "Reduces early purchase gaps without changing economy structure.",
  "apply_mode": "human_only"
}
```

### YAML Recommendation

```json
{
  "id": "yaml.regression_gates.day_1_progression",
  "kind": "yaml_recommendation",
  "file": "economy.yaml",
  "section": "regression_gates.day_1_progression",
  "change_type": "add_or_update",
  "proposal_path": "yaml_plan.json",
  "requires_human_approval": true
}
```

## Agent Workflow

The default Agent loop should be:

1. Inspect project status with `doctor`.
2. Export tables if the human asks for source-table-backed analysis.
3. Lint config and tables.
4. Run scenario.
5. Generate report.
6. Compare against baseline if provided.
7. Run gates if configured.
8. Run configured scans if useful.
9. Generate `advice.json` and `advice.md`.
10. Present recommendations to the human.

At no point should this loop edit source tables.

## Dashboard Integration

v0.5 should add an Agent Analyst panel to the dashboard.

The panel should show:

- Latest run status.
- Main findings.
- Gate pass/fail state.
- Recommended table edits for the human.
- Proposed YAML changes waiting for approval.
- Buttons to rerun analysis after the human edits tables.

Dashboard actions should remain deterministic wrappers around IGESS commands.

## Safety Rules

- Source Excel/Luban tables are read-only from the Agent perspective.
- YAML changes require explicit human approval.
- Every recommendation must cite evidence: metric, artifact path, row, event, or
  report section.
- Every auto-run must write artifacts to a dedicated output directory.
- Advice must distinguish between "data tuning" and "logic/config tuning".
- Failed lint/run/gate steps must produce actionable messages instead of partial
  silent success.

## Acceptance Criteria

v0.5 is complete when:

- `igess advise` can run the sample project and write `advice.json` plus
  `advice.md`.
- Advice includes at least one finding category from current artifacts.
- Advice can produce table recommendations without editing any table file.
- Advice can produce YAML recommendations without applying them.
- `igess yaml-plan` generates a reviewable YAML-only proposal.
- `igess yaml-apply` applies only approved YAML plans and refuses table paths.
- `igess review-run` analyzes an existing run without rerunning.
- Dashboard exposes an Agent Analyst panel backed by the same advice artifacts.
- Tests verify that table files are never modified by Agent commands.

## Suggested Implementation Order

1. Define `advice.json` schema and markdown renderer.
2. Implement run artifact analysis into findings.
3. Implement table recommendation generation from payback, bottleneck, invalid
   content, and scan data.
4. Implement YAML recommendation generation as proposals only.
5. Implement `igess advise`.
6. Implement `igess review-run`.
7. Implement `igess yaml-plan`.
8. Implement `igess yaml-apply` with strict path/section allowlists.
9. Add dashboard Agent Analyst panel.
10. Add tests that hash table files before and after Agent commands.

## Non-Goals

- Agent-authored Excel/Luban table editing.
- Automatic acceptance of YAML changes.
- Cloud service orchestration.
- Replacing the human designer's judgment.
- Training or hosting an LLM inside IGESS.

## Open Questions

- Should `igess advise` always run scans, or only when scan presets exist?
- Should YAML plans use JSON Patch, a custom YAML patch format, or full proposed
  replacement fragments?
- Should advice compare against the latest `.igess/runs` entry by default, or only
  when a baseline is explicitly passed?
- How much dashboard UI should be built in v0.5 versus keeping the first version
  CLI/artifact-first?
