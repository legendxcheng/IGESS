---
name: fish-balance-loop
description: Run and review repeatable Fish numeric-balance iterations through IGESS. Use when the user asks to simulate Fish for a duration, open or inspect its Web report, analyze Strength/FishLuck/TrashLuck or persistent-progression pacing, compare a newly exported Luban/Excel data snapshot with a prior run, or discuss attributable tuning proposals while the human designer retains ownership of production table edits and exports.
---

# Fish Balance Loop

Run a source-traceable Fish simulation, open its generated Web report, explain the balance findings, and repeat after the human designer edits and exports the production tables.

## Preserve the ownership boundary

- Let the human designer edit production Excel/Luban values and run the export.
- Do not modify production numeric tables, exported JSON, or generated Lua unless the user explicitly asks.
- Analyze and propose values or directions; never present a proposal as already applied.
- Preserve unrelated and uncommitted workspace changes. Run `git status --short` before work and never clean the workspace.
- Use `E:\fish-oasis\igess_export\json` as the production snapshot. Do not substitute fixtures, copied GDD data, prose values, or CLI overrides for a production balance run.

## Select the scenario

Map common requested durations to the existing Fish scenarios:

| Requested duration | Scenario |
| --- | --- |
| quick rule check | `smoke` |
| 1 day | `day_1_growth` |
| 7 days | `week_1_growth` |
| 30 days | `month_1_growth` |

Use 1 day for early pacing, 7 days for the normal tuning loop, and 30 days for milestone validation.

If the requested duration has no scenario, add a clearly named scenario to `projects/fish_source/economy.yaml` only when that duration was explicitly requested. Keep the production profile, seed, start state, and data source unchanged. Choose a record interval and compact outputs that keep artifacts practical. Do not emulate a production run with `--override`.

## Run the loop

### 1. Establish the request

Identify:

- requested duration or scenario;
- metrics or systems to emphasize;
- whether this is a fresh baseline or a candidate to compare with a named prior run.

Make a reasonable default of `week_1_growth` when the user requests a general balance review without a duration. State that assumption before starting.

### 2. Perform preflight checks

From `E:\IGESS`:

```powershell
git status --short
.\.tmp\py311-venv\Scripts\igess.exe model status --project projects\fish_source
```

Confirm that the source model is ready, `lua55` is available, and `engine.source_runtime.project_root` / `data_root` point to the intended Fish checkout and selected JSON export. Read `projects/fish_source/README.md` and `projects/fish_source/RoadMap.md` before rule or tuning recommendations. `projects/fish` is retired; preserve its historical code/reports and never use it for a new run or comparison baseline.

If the user says they re-exported tables, do not assume the new data was loaded. Verify `run_manifest.source_runtime.selected_export_root` and `selected_export_sha256` against the actual selected export; require `engine_id=fish_source` and a model digest. This backend has no `production_data` flag.

### 3. Run through the registered IGESS workflow

Prefer the machine-readable response:

```powershell
.\.tmp\py311-venv\Scripts\igess.exe model simulate `
  --project projects\fish_source `
  --scenario week_1_growth `
  --json
```

Replace the scenario as requested. Do not bypass `WorkflowService`, the Fish engine adapter, `RunRegistry`, or standard artifact generation with an ad hoc domain script when producing a formal report.

Keep the user informed during long simulations. Do not leave more than 60 seconds without a concise progress update when tool execution permits it.

### 4. Validate the new run

Read `result.output_dir` and `result.report_index` from the JSON response rather than guessing the latest directory. Require all applicable artifacts before declaring success:

- `report/index.html`;
- `output/run_manifest.json`;
- `output/final_checkpoint.json`;
- `output/source_progression.json`;
- `output/source_behavior.json`;
- `report/report_data.json`;
- standard timeline, events, and analysis outputs.

Require the registered `run_status.json` to say `success` and every `run_manifest.artifacts` file to exist. Confirm scenario, profile, execution window, root seed, model digest, source `code_sha256`, `integration_code_sha256`, `selected_export_sha256`, Lua version, player/claim/equipment policy, natural landing policy and periodic tide origin/interval. Preserve the selected production JSON bytes and timestamps. Read source timings and artifact sizes when investigating long-run cost. Distinguish simulation-rule failures from report or artifact infrastructure failures. Preserve failed run directories as evidence.

A long run can fail at source execution, checkpoint, artifact writing or report generation. Do not describe an in-memory domain result as a successful formal Web-report run. Report the exact boundary that failed and propose output compaction separately.

### 5. Open the report automatically

After validation, open the exact `result.report_index` in the user's visible default browser:

```powershell
Start-Process -FilePath $reportIndex
```

If browser inspection is requested and browser-control tooling is available, load its required skill and inspect the rendered page. Otherwise analyze the machine-readable report artifacts and provide a clickable local link.

### 6. Analyze Fish-first metrics

Treat the Fish-specific progression sections as authoritative. The generic report's `Purchase events: 0` or empty payback data does not mean Fish had no economic activity.

Review metrics that the actual artifacts support:

- Strength, Fish Luck and Trash Luck sampled current/peak values and rebirth boundaries. A sampled peak is not a continuous-time true peak; unavailable stagnation or recovery metrics remain unavailable.
- Source persistent progression rows, active-time waits/density/gaps and online sessions without progression. Separate completed realm progression from breakthrough funding. Individual codex unlocks/claims, fish upgrades, egg observations, repeated participation and repeated gun ownership do not count as new system openings.
- Lifecycle `first_times` for normal codex completion, gun claim, first tide participation and treasure-beast unlock; use both wall time and cumulative online time. `lifecycle_gun_milestones` retains ownership/equipment/upgrade identities through checkpoints.
- Each tide's participation/skip reason, actual six reload receipts and expense, occupied seconds, admitted eggs and this segment's hatches. The explicit approximation is **5 acquired random eggs / 120 foreground seconds / 6 reloads**, with damage-independent yield and no real hit/competition model.
- Exact final wallets, unclaimed hall money, one-time codex money/material, fish-sale material, production and tide expense. Hall collection is a transfer; an admitted egg is not yet a fish. Check source inventory count/capacity and blocked due eggs when relevant.

Use cumulative online time for player-experience gaps; offline waits must not inflate them. Do not infer beast access from strength or initial realm: require the actual area-four landing fact. A production run that never completes a codex or cannot afford tides is a balance finding; do not grant a gun or change inputs to force access.

For a resumed formal run, `execution_window` describes this segment. Commands, events, hatches, sampled peaks and period summaries cover this segment; wallets, source throws and acquisition totals continue the checkpoint. First lifecycle timestamps are retained separately. Report segment online duration separately from cumulative online coordinates. Resume with the same scenario using `--checkpoint-in`; `--until-seconds` is an absolute execution cutoff, not a player logout or a changed model.

Separate three layers in the conclusion:

1. observed facts from the run;
2. inferred causes tied to specific systems or table fields;
3. proposed tuning changes and expected tradeoffs.

Avoid attributing a result to one field when multiple production inputs changed between runs.

### 7. Deliver the review

Lead with the balance outcome, then provide:

- scenario, run ID, model digest, and report link;
- a compact KPI summary with prior values when comparing;
- the most important pacing or growth problems by active-time stage;
- likely responsible tables and fields;
- one or more attributable tuning options with risks;
- unresolved design decisions for discussion.

Do not drown the user in raw event counts. Prefer timings, gaps, rates, peaks, resets, and player-visible milestones.

### 8. Repeat after human export

Wait for the human designer to confirm that Excel changes were exported. Then rerun the same scenario with the same profile, seed, and policy. Compare baseline and candidate model digests and Fish-specific KPIs.

Use IGESS `compare` or `gate` where it correctly consumes the required metrics. Until Fish-specific compare/gate integration is complete, directly compare `source_progression` and `source_behavior` artifacts and clearly label that analysis as Fish-specific.

Never launch a broad parameter scan unless the user asks for it and the relevant Fish Luban fields are supported. Preserve one-change-at-a-time attribution whenever practical.

## Example invocations

- `Use $fish-balance-loop to run 7 days, open the report, and focus on permanent-progression gaps.`
- `我已经重新导表了，用 $fish-balance-loop 跑 1 天并和上一轮比较双 Luck。`
- `用 $fish-balance-loop 跑 30 天；如果正式网页产物失败，告诉我失败边界，不要把内存结果当正式成功。`
