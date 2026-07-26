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
- Use `E:\fish-oasis\igess_export\json` and its matching `python\schema.py` as the production snapshot. Do not substitute fixtures, copied GDD data, prose values, or CLI overrides for a production balance run.

## Select the scenario

Map common requested durations to the existing Fish scenarios:

| Requested duration | Scenario |
| --- | --- |
| quick rule check | `smoke` |
| 1 day | `day_1_growth` |
| 7 days | `week_1_growth` |
| 30 days | `month_1_growth` |

Use 1 day for early pacing, 7 days for the normal tuning loop, and 30 days for milestone validation.

If the requested duration has no scenario, add a clearly named scenario to `projects/fish/economy.yaml` only when that duration was explicitly requested. Keep the production profile, seed, start state, and data source unchanged. Choose a record interval and compact outputs that keep artifacts practical. Do not emulate a production run with `--override`.

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
.\.tmp\py311-venv\Scripts\igess.exe model status --project projects\fish
```

Confirm that the model is ready and that the production data root and generated schema exist. Read the latest `projects/fish/RoadMap.md` and, when resuming another session, `projects/fish/HANDOFF.md` before making rule or tuning recommendations.

If the user says they re-exported tables, do not assume the new data was loaded. Verify the resulting run manifest records `production_data=true`, the expected data root, input hashes, and a model digest.

### 3. Run through the registered IGESS workflow

Prefer the machine-readable response:

```powershell
.\.tmp\py311-venv\Scripts\igess.exe model simulate `
  --project projects\fish `
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
- `output/luck_progression.json` and `.csv`;
- `output/behavior_progression.json` and `.csv`;
- standard timeline, events, and analysis outputs.

Confirm the scenario, profile, duration, seed provenance, production-data flag, input hashes, and model digest. Distinguish simulation-rule failures from report or artifact infrastructure failures. Preserve failed run directories as evidence.

The 30-day authoring path may fail while writing very large artifacts. Do not describe an in-memory domain result as a successful formal Web-report run. Report the exact boundary that failed and propose output compaction separately.

### 5. Open the report automatically

After validation, open the exact `result.report_index` in the user's visible default browser:

```powershell
Start-Process -FilePath $reportIndex
```

If browser inspection is requested and browser-control tooling is available, load its required skill and inspect the rendered page. Otherwise analyze the machine-readable report artifacts and provide a clickable local link.

### 6. Analyze Fish-first metrics

Treat the Fish-specific progression sections as authoritative. The generic report's `Purchase events: 0` or empty payback data does not mean Fish had no economic activity.

Always review:

- Strength current value, peak, rebirth count, and recovery time;
- FishLuck and TrashLuck current/peak curves, growth rates, divergence, and longest stagnation;
- first persistent-progression wait;
- persistent gains per active hour;
- interval P50/P75/P90/P95, maximum interval, and tail gap;
- system-only progression count, density, maximum interval, and tail gap;
- complete online sessions without progression;
- category counts, diversity, and dominant-category share;
- torpedo, barbell, fish-hall, realm-breakthrough, and both rebirth timings;
- final money, material, strength, realm, equipment, and checkpoint consistency when relevant.

Use cumulative active play time for player-experience gaps. Do not use the 22-hour offline period to inflate progression waits. Exclude single-fish upgrades from persistent/system progression. Show both current Luck and historical peak so rebirth resets remain visible.

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

Use IGESS `compare` or `gate` where it correctly consumes the required metrics. Until Fish-specific compare/gate integration is complete, directly compare `luck_progression` and `behavior_progression` artifacts and clearly label that analysis as Fish-specific.

Never launch a broad parameter scan unless the user asks for it and the relevant Fish Luban fields are supported. Preserve one-change-at-a-time attribution whenever practical.

## Example invocations

- `Use $fish-balance-loop to run 7 days, open the report, and focus on permanent-progression gaps.`
- `我已经重新导表了，用 $fish-balance-loop 跑 1 天并和上一轮比较双 Luck。`
- `用 $fish-balance-loop 跑 30 天；如果正式网页产物失败，告诉我失败边界，不要把内存结果当正式成功。`
