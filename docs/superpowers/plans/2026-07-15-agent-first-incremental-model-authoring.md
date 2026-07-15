# Agent-First Incremental Model Authoring Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents are available) or superpowers:executing-plans to implement this plan. Keep every checkbox as an independently verifiable TDD step.

**Goal:** Let an Agent create a blank IGESS project, apply one formal economy rule at a time to `economy.yaml` plus Luban workbooks, receive derived completeness guidance after every rule, automatically smoke-simulate runnable partial models, and then launch formal simulations and tuning from the same attributable model state.

**Architecture:** Introduce a small `igess.authoring` package with separate response, schema, change parsing, project, source adapter, probe, status, locking, transaction, audit, and service modules. Formal YAML and Luban workbooks remain authoritative. Read commands use ephemeral exports; apply uses a recoverable staged transaction and commits synchronized exports, audit, and optional smoke artifacts. Existing simulation/reporting code remains the execution engine.

**Tech stack:** Python 3.11+, argparse, dataclasses, Decimal, PyYAML, openpyxl, pathlib, hashlib, stdlib `msvcrt`/`fcntl`, pytest, vanilla HTML/CSS/JavaScript.

**Workspace constraint:** Intentional uncommitted activity/activity-output changes already exist in this worktree. Work in place, preserve them, stage only files named in each task, and inspect `git diff --cached --name-only` before every commit.

**Design reference:** `docs/superpowers/specs/2026-07-15-agent-first-incremental-model-authoring-design.md`

---

## Target File Structure

### Presentation and legacy CLI

- Create `src/igess/human_numbers.py` for six-significant-digit presentation formatting.
- Create `src/igess/cli_support.py` for legacy input-path diagnostics only.
- Create `src/igess/reporting/kpis.py` for pure report KPI derivation.
- Modify `src/igess/cli.py`, `src/igess/scan.py`, `src/igess/simulator.py`, `src/igess/rng.py`, `src/igess/analyzer.py`, and report view/assets.
- Create focused tests `test_human_numbers.py`, `test_cli_help.py`, `test_cli_diagnostics.py`, `test_cli_scan.py`, and `test_reporting_kpis.py`.

### Authoring package

- `response.py`: `AuthoringError`, stable JSON envelope, and human lines.
- `entity_schema.py`: immutable entity/field definitions and value validators.
- `change.py`: lossless YAML/JSON parser plus merge-patch validation.
- `project.py`: paths, discovery, model digest, and run-root compatibility.
- `templates.py`: exact blank YAML/workbook/README/runner templates.
- `yaml_source.py`: canonical YAML-backed upserts.
- `workbook_source.py`: marker-aware Luban table upserts.
- `exports.py`: staged project copy and command-scoped export helpers.
- `probe.py`: static eligibility and ten-tick observable-change probe.
- `status.py`: structural/completeness derivation.
- `locking.py`: cross-process shared/exclusive project locks.
- `transactions.py`: prepared/committing/committed journals and recovery.
- `change_records.py`: successful and failed attempt audit records.
- `service.py`: init/status/apply/simulate orchestration.
- `cli.py`: nested parser construction and response rendering for `igess model`.

### Authoring tests

- `test_authoring_response.py`, `test_authoring_entity_schema.py`, `test_authoring_change.py`
- `test_authoring_project.py`, `test_authoring_yaml_source.py`, `test_authoring_workbook_source.py`, `test_authoring_exports.py`
- `test_authoring_probe.py`, `test_authoring_status.py`
- `test_authoring_locking.py`, `test_authoring_transactions.py`, `test_change_records.py`
- `test_run_registry.py`, `test_authoring_service.py`, `test_authoring_cli.py`

---

## Chunk 1: CLI and Human Presentation

### Task 1: Exact human-number formatter

**Files:** create `src/igess/human_numbers.py`; create `tests/test_human_numbers.py`.

- [ ] Write parameterized RED tests for this exact table:

  | input | output |
  | --- | --- |
  | `None` | `None` |
  | `""` | `""` |
  | `"0"`, `"-0"` | `"0"` |
  | `"999999"` | `"999999"` |
  | `"999999.5"` | `"1000000"` |
  | `"1000000"` | `"1e6"` |
  | `"0.0001"` | `"0.0001"` |
  | `"0.00009999995"` | `"1e-4"` |
  | `"0.0000123456789"` | `"1.23457e-5"` |
  | `"739.864019013290554"` | `"739.864"` |
  | `"-739.864019013290554"` | `"-739.864"` |
  | `"1.234565"` | `"1.23456"` |
  | `"1.234575"` | `"1.23458"` |
  | `"1067640000000004000"` | `"1.06764e18"` |
  | `"1e+0007"` | `"1e7"` |
  | `"Infinity"`, `"-Infinity"`, `"NaN"` | unchanged |

  Also assert `human_number("1000000") == {"exact_value": "1000000", "display_value": "1e6"}` and that a 1000-digit finite value formats without float conversion or `InvalidOperation` leakage.

- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_human_numbers.py -q`; verify collection fails because the module is absent.

- [ ] Implement `format_human_number(value)` with `Decimal(str(value))`, `ROUND_HALF_EVEN`, and a local context whose precision is `max(80, len(number.as_tuple().digits) + 10)`, `Emax=MAX_EMAX`, and `Emin=MIN_EMIN`. For nonzero finite values choose fixed versus scientific notation from the original absolute value, then compute `adjusted = number.copy_abs().adjusted()` and round with `quantum = Decimal(1).scaleb(adjusted - 5)`. Format in the already-selected mode, lower-case scientific `E`, trim fractional zeros, and remove exponent `+` and leading zeros. Normalize either signed zero to `0`. Return unparseable and special source strings unchanged.

- [ ] Implement `human_number(value)` as the two-key exact/display mapping. Run `.\.venv\Scripts\python.exe -m pytest tests/test_human_numbers.py tests/test_numbers.py -q`; expect pass.

- [ ] Stage only the two files, inspect the cached file list, and commit `feat: add exact human number formatting`.

### Task 2: Discoverable legacy CLI help

**Files:** create `tests/test_cli_help.py`; modify `src/igess/cli.py`.

- [ ] Add a local subprocess helper in the test file:

```python
def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "igess.cli", *args],
        check=False,
        capture_output=True,
        text=True,
    )
```

  Assert top-level help names and describes every existing command, includes `Commands`, and documents exit codes 0/1/2. For `run --help`, assert descriptions for `--config`, `--tables`, `--scenario`, `--out`, defaults where present, and a complete example. Repeat argument-help assertions for `lint`, `scan`, `rng-run`, `report`, `dashboard`, and `init`. Do not assert or expose `model` yet.

- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_cli_help.py -q`; verify help-description assertions fail.

- [ ] Refactor only parser metadata: top-level `description`, titled subparsers, command `help` plus `description`, argument `help`, and `RawDescriptionHelpFormatter` epilogs. Do not change dispatch or output contracts and do not register a bare `model` parser.

- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_cli_help.py tests/test_ergonomics.py -q`; expect exit `0`. Commit only CLI/help-test files as `feat: make simulation commands discoverable`.

### Task 3: Actionable path and scenario diagnostics

**Files:** create `src/igess/cli_support.py`; create `tests/test_cli_diagnostics.py`; modify `src/igess/cli.py`, `src/igess/simulator.py`, `src/igess/rng.py`.

- [ ] Define `CONFIG = "examples/shelldiver_v0/economy.yaml"` and `TABLES = "examples/shelldiver_v0/luban_exports"` plus the same `run_cli` helper in the new test. Assert exact diagnostic fragments and exit `1` for missing config, workbook source directory (`export-tables --datas`), runtime export directory (`run --tables`), run directory (`report --run`), and proposal (`review-proposal --proposal`). Each message must name the argument role and supplied path and contain no `Traceback`.

- [ ] Add simulator tests asserting `unknown scenario 'bad'; available: analytic_smoke, day_1_progression` for `run` and `advise`'s simulation path, plus an RNG test asserting `unknown scenario 'bad'; available: aura_baseline` for `rng-run`. Assert exit `1`.

- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_cli_diagnostics.py -q`; verify current generic `FileNotFoundError`/`KeyError` assertions fail.

- [ ] Implement `require_file(path, role)` and `require_directory(path, role)` in `cli_support.py`. Call them immediately before each legacy command reads its config, workbook source, runtime tables, run, baseline, plan, or proposal input. Preserve existing exception handling and stdout on success.

- [ ] In `Simulator.run_scenario` and `RngSimulator.run_scenario`, perform membership checks before indexing and raise a `ValueError` with sorted ids or `none`. Run `.\.venv\Scripts\python.exe -m pytest tests/test_cli_diagnostics.py tests/test_simulator_outputs.py tests/test_tuning.py tests/test_rng.py -q`; expect exit `0`. Commit the focused slice.

### Task 4: Typed scan-range errors

**Files:** create `tests/test_cli_scan.py`; modify `src/igess/scan.py`.

- [ ] Parameterize invalid specifications: `bad`, `=1..2:1`, `a=`, `a=1`, `a=1..2`, `a=1..2:`, `a=x..2:1`, `a=1..x:1`, `a=1..2:x`, `a=1..2:0`, `a=2..1:1`, `a=1..2:-1`, and `a..b=1..2:1`. Assert `ValueError` has the syntax `PATH=START..STOP:STEP`, the fisherman example, and the rejected text; subprocess mode exits `1` without traceback.

- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_cli_scan.py -q`; verify failures expose raw unpack/Decimal errors.

- [ ] Implement one `parse_scan_parameter(spec)` boundary: validate one `=`, one `..`, one `:`, a dot-separated nonempty identifier path, and exact `Decimal` parsing inside a single `try/except (InvalidOperation, ValueError)`. Enforce nonzero step, direction agreement, and the existing variant cap. Route `run_scan` through it.

- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_cli_scan.py tests/test_tuning.py -q`; expect exit `0`. Commit `feat: explain invalid scan ranges`.

### Task 5: Pure KPI definitions

**Files:** create `src/igess/reporting/kpis.py`; create `tests/test_reporting_kpis.py`.

- [ ] Construct this literal `ReportData` fixture directly; do not run the simulator:

```python
return ReportData(
    run_dir=tmp_path,
    manifest={"scenario_id": "fixture", "profiles": ["beta", "alpha"]},
    timeline=[
        {"profile_id": "alpha", "time_seconds": 10, "resources": {"gold": "8"}},
        {"profile_id": "beta", "time_seconds": 20, "resources": {"gold": "5"}},
        {"profile_id": "alpha", "time_seconds": 30, "resources": {"gold": "12"}},
        {"profile_id": "beta", "time_seconds": 5, "resources": {"gold": "1"}},
    ],
    events=[
        {"profile_id": "alpha", "time_seconds": 0, "kind": "unlock_generator", "item_id": "zero"},
        {"profile_id": "beta", "time_seconds": 3, "kind": "unlock_upgrade", "item_id": "z"},
        {"profile_id": "alpha", "time_seconds": 3, "kind": "unlock_activity", "item_id": "b"},
        {"profile_id": "alpha", "time_seconds": 3, "kind": "unlock_activity", "item_id": "a"},
        {"profile_id": "alpha", "time_seconds": 4, "kind": "buy_generator", "item_id": "g"},
        {"profile_id": "beta", "time_seconds": 5, "kind": "buy_upgrade", "item_id": "u"},
        {"profile_id": "beta", "time_seconds": 6, "kind": "prestige_reset", "item_id": "p"},
    ],
    analysis={
        "invalid_content_report": {
            "never_purchased": ["generator:x"],
            "never_unlocked": ["upgrade:y"],
        },
        "overpowered_content_report": [{"item_id": "generator:g"}],
        "bottleneck_report": {"alpha": [{"start": 0, "end": 90, "duration": 90}]},
    },
    payback_rows=[
        {"profile_id": "alpha", "kind": "generator", "item_id": "g", "payback_seconds": "100"},
        {"profile_id": "beta", "kind": "upgrade", "item_id": "z", "payback_seconds": "Infinity"},
        {"profile_id": "alpha", "kind": "upgrade", "item_id": "b", "payback_seconds": "Infinity"},
    ],
    missing_artifacts=[],
)
```

- [ ] Assert literal results: `duration_seconds == "30"`; profile keys are `['beta', 'alpha']`; final resources are `{'beta': {'gold': '5'}, 'alpha': {'gold': '12'}}`; purchase count `2`; first key unlock is `{'time_seconds': '3', 'profile_id': 'alpha', 'kind': 'unlock_activity', 'item_id': 'a'}`; prestige count `1`; worst payback is the alpha/upgrade/b row with `Infinity`; never counts are both `1`; warning-category count is `5`. Parameterize removal of each one of the five warning inputs and assert `4`, then remove all and assert `0`.

- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_reporting_kpis.py -q`; verify import failure. Implement pure `build_overview(data) -> dict[str, Any]` plus small named helpers in `kpis.py`; parse payback with `Decimal`, never float. Return exact numeric strings at this layer.

- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_reporting_kpis.py -q`; expect exit `0`. Commit only KPI module/tests.

### Task 6: Report schema v2 numeric contract and HTML

**Files:** modify `src/igess/reporting/view_model.py`, `src/igess/reporting/assets/report.js`, `src/igess/reporting/assets/report.css`, `tests/test_reporting_view_model.py`, `tests/test_reporting.py`.

- [ ] Change RED expectations to schema version `2`. Assert every human numeric field in overview, resource series, total-CPS series, and payback diagnostics has `exact_value`, `display_value`, and `chart_value`. Assert `chart_value` is `None` for Infinity/out-of-range values while exact/display remain present. Assert final-resource KPI and worst-payback payloads keep exact values.

- [ ] In static-report tests assert generated HTML contains an Overview KPI grid and exact-value affordance; `report.js` references `overview`, `display_value`, and `exact_value`; embedded/file JSON match and use schema `2`.

- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_reporting_view_model.py tests/test_reporting.py -q`; verify schema-v2 assertions fail. Change `chart_point` to merge `human_number(value)` with bounded `chart_value`, call `build_overview`, expose optional manifest `model_digest` at `scenario.model_digest`, and make all numeric series/diagnostic builders use the numeric contract. Time fields used only as axes remain integer time fields; any separately displayed time passes through the three-field contract.

- [ ] Render KPI cards from `display_value`, put `exact_value` in `title` or a `<details>` element, and add scoped CSS. Run `.\.venv\Scripts\python.exe -m pytest tests/test_reporting_kpis.py tests/test_reporting_view_model.py tests/test_reporting.py -q`; expect exit `0`. Commit report schema/UI files.

### Task 7: Compact Markdown only

**Files:** modify `src/igess/analyzer.py`; modify `tests/test_analyzer.py`.

- [ ] Add a synthetic `SimulationResult` assertion that `Analyzer.markdown` contains `739.864s`, a compact resource value, and compact payback, while `Analyzer.report` still contains the exact source strings. Assert JSON/CSV writer tests remain unchanged.

- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_analyzer.py -q`; verify Markdown assertion fails. Apply `format_human_number` only in `Analyzer.markdown` final time/resources/payback rendering; do not modify `Analyzer.report`, output writers, gates, comparisons, or tuning inputs.

- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_analyzer.py tests/test_simulator_outputs.py tests/test_reporting.py -q`; expect exit `0`. Commit `feat: compact human-facing analysis values`.

---

## Chunk 2: Incremental Authoring Core

### Task 8: Stable response envelope

**Files:** create `src/igess/authoring/__init__.py`, `src/igess/authoring/response.py`, `tests/test_authoring_response.py`.

- [ ] RED-test `AuthoringError(code, message, details, result)`, `CommandResponse.to_payload()`, deterministic `to_json()`, and `human_lines()`. Assert the payload key order and exact outer keys `schema_version`, `command`, `ok`, `code`, `message`, `details`, `result`; verify an error may carry a full failed status result.

- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_authoring_response.py -q`; verify collection fails because `igess.authoring.response` is absent.

- [ ] Implement frozen dataclasses with no CLI dependency. `human_lines()` emits message, ordered missing requirements, warnings, changed files, and artifact paths from typed result keys; it must not stringify arbitrary nested dictionaries.

- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_authoring_response.py -q`; expect exit `0`, then commit `feat: define authoring command responses`.

### Task 9: Entity schemas and exact validators

**Files:** create `src/igess/authoring/entity_schema.py`, `tests/test_authoring_entity_schema.py`.

- [ ] Encode all 19 version-1 entity definitions from the design as immutable metadata: storage kind/name, required/optional fields, and validators. Test that the exported entity set exactly matches the design and table column order exactly matches registered workbook headers.

- [ ] Parameterize positive/negative validation at every boundary: id regex and empty id; text empty; integer versus boolean; exact decimal string/integer versus JSON/YAML float; positive/nonnegative zero and negatives; every condition operator and malformed `owned` form; upgrade target wildcard/id; each enum; nonempty lists/maps; boolean must be native; formula safe-compiler acceptance/rejection; RNG nonempty rarities, exact unique denominators, and table event-threshold membership; regression gates with zero versus at least one nonempty supported map; envelope `id` forbidden inside `fields`. Explicitly test RNG input order `{epic: "100", common: "1", rare: "10"}` is accepted and normalized to `common, rare, epic` by exact denominator; duplicate exact values such as `"1"` and `"1.0"` fail.

- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_authoring_entity_schema.py -q`; verify import failure. Implement small validator functions that raise `AuthoringError` with code `invalid_change` and entity/id/field/value/allowed details. Use `SimNumber.parse` and the existing safe formula compiler; never convert economic values to float. Normalize RNG rarity mappings by ascending exact denominator after validating uniqueness.

- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_authoring_entity_schema.py tests/test_linter_builder.py -q`; expect exit `0`. Commit schema module/tests.

### Task 10: Lossless change parsing and merge patch

**Files:** create `src/igess/authoring/change.py`, `tests/test_authoring_change.py`.

- [ ] RED-test YAML and JSON file/stdin text with the exact top-level keys. Reject booleans for version, unsupported version/operation/entity, unknown top-level/field keys, missing required create fields, JSON numeric tokens containing `.`/exponent, YAML float tags, duplicate `id` in fields, required-field null, and invalid `if_model_digest`. Assert integer economic tokens normalize to exact decimal strings.

- [ ] Test update behavior against a supplied current entity: omitted values retained, nested maps recursively merged, lists replaced, optional null deleted, required null rejected, and an absent entity requires all required fields.

- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_authoring_change.py -q`; verify collection fails because `igess.authoring.change` is absent.

- [ ] Implement a JSON `parse_int` wrapper plus `parse_float` rejection callback and a PyYAML safe-loader constructor that rejects the float tag before construction. Implement `parse_change_text(text, format_name, current=None)` and `merge_fields(current, patch, schema)`; return a frozen `ModelChange`.

- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_authoring_response.py tests/test_authoring_entity_schema.py tests/test_authoring_change.py -q`; expect exit `0`. Commit `feat: parse exact incremental changes`.

### Task 11: Project paths, discovery, digest, and run-root policy

**Files:** create `src/igess/authoring/project.py`, `tests/test_authoring_project.py`.

- [ ] RED-test discovery only when `economy.yaml`, `Datas`, and `luban_exports` are direct children. Assert role-specific errors for each missing path. Assert new project paths use `runs/`, `reports/`, `changes/`, `.igess/transactions`, and `.igess/model.lock`.

- [ ] Define compatibility exactly: `AuthoringProject.runs` is `root/runs`; `legacy_runs` is `root/.igess/runs`; `read_run_roots()` returns existing roots in `[runs, legacy_runs]` order without duplicates; every new authoring run is written only to `runs`. Dashboard history merges both by run id with the modern root winning duplicates.

- [ ] Test digest stability/order and sensitivity: hash the canonical relative path plus a NUL byte plus bytes for `economy.yaml`, `Datas/__tables__.xlsx`, and all workbooks it registers, sorted lexically. Changing exports/runs/changes must not alter it; changing the registry or any registered source must.

- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_authoring_project.py -q`; verify collection fails because `igess.authoring.project` is absent.

- [ ] Implement the frozen `AuthoringProject` and `sha256:<hex>` digest. Run `.\.venv\Scripts\python.exe -m pytest tests/test_authoring_project.py -q`; expect exit `0`, then commit.

### Task 12: Exact blank project templates

**Files:** create `src/igess/authoring/templates.py`; modify `tests/test_authoring_project.py`, `tests/test_ergonomics.py`.

- [ ] RED-test absent/empty target success, nonempty refusal without partial files, output-name sanitization, explicit id validation, and the exact tree from the design. Confirm legacy `igess init` remains populated and unchanged.

- [ ] Assert generated YAML exactly: model id, `tick_seconds: 1`, `number_backend: bignum_log`, `random_seed: 20260626`; formulas `exponential_cost(base_cost,growth,owned) = base_cost * pow(growth, owned)`, `generator_output(base_output,owned,multiplier) = base_output * owned * multiplier`, and `prestige_gain(progress,divisor,exponent) = floor(pow(progress / divisor, exponent))`; generator type `building`; source types `active`, `generator`, `offline`, `milestone`, `prestige`; modifier pipeline `[base, flat, add_pct, mult, exp]`; modifier ids/stages `flat/flat`, `add_pct/add_pct`, `multiply/mult`, `exponent/exp`; `cheap_unlock_first`; session `authoring_default` with offline-every `60` and offline-duration `0`; profile `default` with every source efficiency `"1"`, conservative prestige, empty `activity_weights`, luck `"1"`; and scenario `smoke` with duration-hours `"0.002777777777777778"`, tick mode, `[default]`, `new_player`, one-second recording, and all five standard output names. This is exactly ten one-second ticks.

- [ ] Assert all nine workbooks and exact three marker rows/column order/types. The eight entity workbooks have no game-data rows. `__tables__.xlsx` has exactly these eight registration rows, in order, each with mode `map` and key `id`: `(resources, resources.xlsx)`, `(generators, generators.xlsx)`, `(activities, activities.xlsx)`, `(activity_outputs, activity_outputs.xlsx)`, `(upgrades, upgrades.xlsx)`, `(constants, constants.xlsx)`, `(milestones, milestones.xlsx)`, `(prestige_layers, prestige_layers.xlsx)`. For prestige reset type assert `(list#sep=;),string`. Assert README contains four model commands and source-of-truth text; `run.ps1` invokes status then smoke simulate.

- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_authoring_project.py tests/test_ergonomics.py -q`; verify initializer-specific assertions fail while legacy ergonomics still pass.

- [ ] Implement `initialize_authoring_project(out, model_id=None)` with UTF-8/LF text writes and openpyxl workbooks. Reuse current schema constants, not sample rows or `src/igess/templates.py`. Run `.\.venv\Scripts\python.exe -m pytest tests/test_authoring_project.py tests/test_ergonomics.py -q`; expect exit `0`, then commit.

### Task 13: Canonical YAML source adapter

**Files:** create `src/igess/authoring/yaml_source.py`, `tests/test_authoring_yaml_source.py`.

- [ ] For every YAML-backed entity, RED-test create and update at its design mapping. Include recursive player-profile map merge, scenario list replacement, optional deletion, RNG validation with selected table, regression-gate merge, duplicate mapping id detection, and unknown reference surfacing. Persist the deliberately unordered RNG fixture from Task 9 and assert YAML plus reload order is `common, rare, epic`.

- [ ] Assert serialized bytes are UTF-8, use LF only, preserve top-level/current insertion order, use `safe_dump(allow_unicode=True, sort_keys=False)`, end with one newline, and produce identical bytes on a no-op repeat. Explicitly assert comments are not preserved.

- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_authoring_yaml_source.py -q`; verify collection fails because the adapter is absent.

- [ ] Implement `read_yaml_entity`, `find_yaml_duplicates`, and `upsert_yaml_entity(candidate_config, change) -> bool`. Validate the merged whole entity before write. Run `.\.venv\Scripts\python.exe -m pytest tests/test_authoring_yaml_source.py tests/test_authoring_entity_schema.py -q`; expect exit `0`, then commit.

### Task 14: Marker-aware workbook source adapter

**Files:** create `src/igess/authoring/workbook_source.py`, `tests/test_authoring_workbook_source.py`.

- [ ] RED-test each table-backed entity, prestige list encoding with `;`, update-in-place, duplicate ids, headers found by marker values rather than fixed rows, unrelated formulas/cells/styles preserved, and no extra rows for a no-op update.

- [ ] Create two fixtures: one workbook with an existing styled data row and one blank template. Assert a new row copies style/number format/alignment from the nearest preceding data row; when none exists, each new cell copies the corresponding column cell's style from the `##type` row before receiving its value. Assert only values in schema columns are changed.

- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_authoring_workbook_source.py -q`; verify collection fails because the adapter is absent.

- [ ] Implement `inspect_table`, `find_duplicate_ids`, and `upsert_workbook_entity(path, change) -> bool` using openpyxl. Save to a sibling temporary file and replace only after a successful reopen check. Run `.\.venv\Scripts\python.exe -m pytest tests/test_authoring_workbook_source.py tests/test_luban_sources.py -q`; expect exit `0`, then commit.

### Task 15: Candidate copy and runtime exports

**Files:** create `src/igess/authoring/exports.py`, `tests/test_authoring_exports.py`.

- [ ] RED-test `stage_sources(project, transaction_dir)` copies only authoritative YAML/workbooks and preserves relative paths. Test `apply_to_candidate` selects YAML/workbook adapters and returns canonical changed relative paths.

- [ ] For one representative row of every table, invoke the real `export_registered_workbooks`; index each exported JSON row list by its `id` in the assertion, then assert exact decimal strings, prestige list decoding, `_source.workbook/table/row`, and no write to the project's committed `luban_exports`.

- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_authoring_exports.py -q`; verify collection fails because export helpers are absent.

- [ ] Implement `export_candidate(candidate, out)` and `ephemeral_export(project)` context manager. Hash export relative paths plus bytes so stale committed exports can be compared. Run `.\.venv\Scripts\python.exe -m pytest tests/test_authoring_exports.py tests/test_luban_sources.py -q`; expect exit `0`, then commit.

### Task 16: Static smoke eligibility

**Files:** create `src/igess/authoring/probe.py`, `tests/test_authoring_probe.py`.

- [ ] Build exact fixture models and assert eligibility for all alternatives: positive always activity + positive output + positive activity weight in every smoke profile + positive source efficiency; affordable positive always generator + positive output/efficiency + start-state cost resource at least base cost. Assert zero resource rows independently makes the model ineligible. Assert zero/missing values and one failing profile make each route ineligible.

- [ ] Assert event/time alone are never considered a production path. Assert missing smoke scenario/profile/reference and formula compile failure produce structural errors, not eligibility.

- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_authoring_probe.py -q`; verify collection fails because probe helpers are absent.

- [ ] Implement `static_smoke_eligibility(raw, model) -> EligibilityResult` with ordered findings. Run `.\.venv\Scripts\python.exe -m pytest tests/test_authoring_probe.py -q`; expect exit `0`, then commit.

### Task 17: Ephemeral ten-tick probe

**Files:** modify `src/igess/authoring/probe.py`, `tests/test_authoring_probe.py`.

- [ ] RED-test observable changes independently for resource value, owned-generator count, purchased-upgrade set, and prestige value. Assert unlock/event records and elapsed time without one of those four changes return `smoke_no_state_change`. Inject simulator build/run/artifact failures and assert typed `smoke_failed` rather than incomplete.

- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_authoring_probe.py -q`; verify the newly added ten-tick assertions fail against static-only probe code.

- [ ] Implement `run_ten_tick_probe(model, scenario_id="smoke", artifact_root=None)`. Compare initial/final snapshots using exact `SimNumber`; when `artifact_root` is absent create no files; when present use the existing output/report writers and return their paths/findings.

- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_authoring_probe.py tests/test_simulator_outputs.py tests/test_reporting.py -q`; expect exit `0`, then commit.

### Task 18: Derived status service

**Files:** create `src/igess/authoring/status.py`, `tests/test_authoring_status.py`.

- [ ] RED-test the complete typed payload for blank, resource-only, eligible-but-no-change, runnable, ready, and failed projects. Ready requires a valid non-smoke scenario. Entity counts must be returned even for a partially malformed project; duplicate workbook/YAML ids, unsafe formula, malformed source files, and unresolved supplied references make `failed`. For each failed fixture assert any discoverable scenario ids remain in `available_scenarios` and injected latest smoke id `prior-smoke-1` remains in `latest_smoke_run_id`.

- [ ] Cover every observable-change category from Task 17, both eligibility routes, every smoke profile's weights/efficiencies, generator affordability, and event/time exclusion. Inject build/execution/artifact probe failures and assert failed status with structured requirement.

- [ ] Define `latest_smoke_run_id` injection explicitly: `derive_status(project, latest_smoke: Callable[[], RunRecord | None])`; unit tests pass a lambda, service wiring passes the registry query. Construct a project where `Datas/resources.xlsx` contains `gold` while committed `resources.json` is an older empty export. Assert entity counts, structural checks, and probe see `gold` through the current Datas ephemeral export, committed JSON remains unchanged, and exactly one `exports_stale` warning is added.

- [ ] Assert status does not modify source, committed exports, changes, runs, or reports by comparing recursive file manifests before/after. Implement ordered sort key `(code, entity or "", id or "", message)` and always return `ModelStatus` even on failure.

- [ ] Implement `derive_status` end to end: open an ephemeral current-Datas export; inspect YAML and workbook sources to collect every readable entity count, duplicate/malformed diagnostics, and discoverable scenarios before whole-model loading; load the ephemeral export with `ConfigLoader`, strict-lint it, and build the model; on structural error return `failed` with partial counts/scenarios plus injected latest smoke; otherwise call static eligibility, then the artifact-free ten-tick probe when eligible; map no eligibility/no change to `incomplete`, observable change to `runnable`, and runnable plus a valid non-smoke scenario to `ready`; compare ephemeral and committed export digests for `exports_stale`; sort requirements/warnings and attach the injected latest smoke id on every exit path.

- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_authoring_status.py -q`; verify collection fails because the status service is absent.

- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_authoring_status.py tests/test_authoring_probe.py tests/test_linter_builder.py -q`; expect exit `0`, then commit.

---

## Chunk 3: Transactions, Commands, Dashboard, and Delivery

### Task 19: Cross-process locks

**Files:** create `src/igess/authoring/locking.py`, `tests/test_authoring_locking.py`.

- [ ] RED-test two spawned Python processes: shared/shared overlap, exclusive blocks shared, exclusive blocks exclusive, and process termination releases the lock. Use events/files for synchronization and sub-five-second timeouts.

- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_authoring_locking.py -q`; verify collection fails because the lock module is absent.

- [ ] Implement `project_lock(project, exclusive)` with `msvcrt.locking` on Windows and `fcntl.flock` on POSIX. Keep the lock file handle open for the context lifetime; create `.igess` first. Implement `recovered_shared_snapshot(project, recover_callback)` as exclusive callback-driven recovery followed by shared snapshot, avoiding an import cycle with the later transaction module; a writer may win the documented gap.

- [ ] Run `1..3 | ForEach-Object { .\.venv\Scripts\python.exe -m pytest tests/test_authoring_locking.py -q; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } }`; expect all three exits `0`, then commit.

### Task 20: Recoverable transaction engine

**Files:** create `src/igess/authoring/transactions.py`, `tests/test_authoring_transactions.py`.

- [ ] Define exact on-disk contract in tests: `.igess/transactions/<change_id>/journal.json`, `candidate/`, `backups/`, and `staged_artifacts/`. Journal schema `1` stores phase, pre-digest, ordered targets with relative live/candidate/backup paths and `live_existed`, staged run/change destinations, and last completed checkpoint.

- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_authoring_transactions.py -q`; verify collection fails because the transaction module is absent.

- [ ] Parameterize engine failures at stale-digest recheck, every source replace, export-directory replace, staged-run move, staged-change-record move, and committed-journal write. For each pre-commit failure assert source/export bytes equal the pre-transaction snapshot and no partial final run/change remains. Mapping, export, lint, probe, artifact creation, and real failed-audit behavior belong to the service matrix in Task 23 because they require collaborators not created in this task.

- [ ] Parameterize hard-crash recovery after each commit checkpoint. On next command's recovery, any phase other than `committed` restores all backed-up live targets according to `live_existed`, removes moved final artifacts listed in the journal, and emits `recovered_transaction`; committed journals keep live targets and only remove backups/staging.

- [ ] Implement `Transaction` with an injected `checkpoint(name)` callback, same-volume candidate/backups, and ordered `os.replace`. Every journal update writes a sibling temporary JSON file, flushes and `os.fsync`s it, atomically `os.replace`s `journal.json`, then fsyncs the containing directory where supported. Recheck current source digest under the exclusive lock and raise `stale_model` on mismatch. Cleanup starts only after committed journal plus durable audit. A cleanup failure after durable `committed` keeps post-change state and the next recovery removes only backups/staging; test it separately from rollback cases.

- [ ] Run `1..3 | ForEach-Object { .\.venv\Scripts\python.exe -m pytest tests/test_authoring_transactions.py -q; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } }`; expect all three exits `0`, then commit.

### Task 21: Change-record storage

**Files:** create `src/igess/authoring/change_records.py`, `tests/test_change_records.py`.

- [ ] RED-test success path `changes/<UTC timestamp>-<change_id>.json` and failure path `changes/failed/<UTC timestamp>-<change_id>.json`. Exact schema: version, outcome, timestamp, change envelope, pre/post digest, sorted affected files, full status payload or error envelope, warnings, and correlated run id. Failure post-digest is null.

- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_change_records.py -q`; verify collection fails because the change-record module is absent.

- [ ] Test atomic write, newest `latest()`, malformed-record skip with warning, and stable ordering for equal timestamps. Implement `ChangeRecordStore.stage_success`, `write_failure`, `latest`, and `list_records`. Run `.\.venv\Scripts\python.exe -m pytest tests/test_change_records.py -q`; expect exit `0`, then commit.

### Task 22: Versioned run registry and retention

**Files:** modify `src/igess/run_registry.py`; create `tests/test_run_registry.py`.

- [ ] RED-test schema-versioned status with `kind` (`smoke|formal|advice`), optional `change_id`, and required `model_digest` for new authoring runs. Load legacy unversioned files with `kind="formal"`, null optional fields, and unchanged paths.

- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_run_registry.py -q`; verify new schema/field assertions fail against the legacy registry.

- [ ] Test new ids: formal/advice keep current scenario suffix; smoke contains `-smoke-<change_id>`. Test merged modern/legacy roots from Task 11 and modern-root duplicate precedence.

- [ ] Create 22 smoke, two formal, and two advice records with mixed success/failure. `prune_smoke(keep=20)` must delete only the two oldest smoke directories and no other kinds. Manual `model simulate` does not call pruning.

- [ ] Implement backward-compatible dataclass defaults and registry methods. Run `.\.venv\Scripts\python.exe -m pytest tests/test_run_registry.py tests/test_dashboard.py -q`; expect exit `0`, then commit.

### Task 23: Authoring service orchestration

**Files:** create `src/igess/authoring/service.py`, `tests/test_authoring_service.py`; modify `src/igess/outputs.py`, `tests/test_simulator_outputs.py`.

- [ ] RED-test `init`, `status`, `apply`, and `simulate` response contracts exactly as the design table. Inject project, transaction, status, registry, clock, and id factory dependencies; do not patch globals.

- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_authoring_service.py -q`; verify collection fails because the service is absent.

- [ ] Test incomplete apply: candidate validates, source/export commit, success audit, `smoke.status="not_run"`, no run. Test eligible no-change apply: probe artifacts are committed, state incomplete with finding. Test runnable/ready apply: correlated smoke run has the post-model digest and change id, then smoke pruning occurs.

- [ ] Inject mapping, export, lint, status/probe build, smoke execution, smoke artifact write, success-audit staging, stale digest, and each transaction commit failure. Each returns its stable code, restores source/export bytes, and calls `ChangeRecordStore.write_failure` once after identity is known. A first-call success-audit failure must roll back and then successfully write the failure record. Test persistent failed-record media failure separately: formal state is still restored, response code is `audit_failed`, and details contain the unwritten audit path. Invalid proposal before project/change identity creates no record. Stale proposal via `if_model_digest` and precommit mismatch both return `stale_model`. `status` failure still returns full typed status.

- [ ] Extend `OutputWriter.write_all` and `write_manifest` with optional `model_digest=None`; omit the key for legacy callers and store the exact value for authoring runs. For `simulate`, assert ephemeral export is used, committed exports remain untouched, default `smoke` and explicit formal scenario work, and `run_status.json`, `output/run_manifest.json`, and report `scenario.model_digest` share the captured source digest. Every manual `model simulate`, including scenario `smoke`, is `kind="formal"`, has null `change_id`, uses a normal scenario-suffixed id, and is never pruned. Only apply's correlated automatic probe is `kind="smoke"` with `-smoke-<change_id>`.

- [ ] Implement orchestration using explicit collaborators and transaction staging. Every command first invokes exclusive recovery; status/simulate then take a shared snapshot and merge any `recovered_transaction` entries into response warnings, while apply retains the exclusive lock through cleanup. Human text comes from `CommandResponse.human_lines()`. Run `.\.venv\Scripts\python.exe -m pytest tests/test_authoring_service.py tests/test_authoring_transactions.py tests/test_change_records.py tests/test_run_registry.py tests/test_simulator_outputs.py -q`; expect exit `0`, then commit.

### Task 24: `igess model` CLI

**Files:** create `src/igess/authoring/cli.py`, `tests/test_authoring_cli.py`; modify `src/igess/cli.py`, `src/igess/authoring/__init__.py`.

- [ ] RED-test subprocess contracts for all four commands. `init`: human/JSON and exact result paths. `status`: absent project error, valid incomplete exit `0`, failed full JSON exit `1`. `apply`: file extension auto-detection, stdin YAML/default, stdin JSON/`--format json`, exactly-one source argparse exit `2`, invalid change, stale digest, incomplete success, automatic smoke. `simulate`: default/explicit scenario and artifact paths. Every domain failure must have no traceback.

- [ ] Add parser help assertions for exact arguments, defaults, examples, and exit codes. JSON assertions parse exactly one stdout object and require empty stderr on success. Human assertions require concise message plus ordered missing/warning lines.

- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_authoring_cli.py tests/test_cli_help.py -q`; verify `model` parser/dispatch assertions fail while legacy help remains green.

- [ ] Implement nested parser registration only now. `authoring.cli.add_model_parser(subparsers)` owns all nested metadata and `dispatch_model(args)`; `src/igess/cli.py` delegates before legacy loading. `_render_response` uses `response.to_json()` or message plus `human_lines()`, returning 0/1; argparse retains 2.

- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_authoring_cli.py tests/test_cli_help.py tests/test_docs_examples.py -q`; expect exit `0`, then commit.

### Task 25: Workflow and Dashboard observability

**Files:** modify `src/igess/workflows.py`, `src/igess/dashboard.py`, `src/igess/cli.py`, `tests/test_dashboard.py`, `tests/test_cli_help.py`.

- [ ] Resolve project discovery explicitly: change Dashboard `--config`/`--tables` parser defaults to `None`. When `--project` directly contains an authoring project and neither override is supplied, use `economy.yaml` plus ephemeral current Datas through `AuthoringService`; explicitly supplied overrides retain legacy behavior. When the project is not authoring and overrides are omitted, preserve the old sample defaults relative to the project. Keep `.igess/runs` readability.

- [ ] RED-test state badge, counts, ordered missing requirements, recovery/stale warnings, latest change, latest smoke, scenario `<select>` populated from status, unified kind-labelled history and report links, and HTML escaping. Test GET only for home/status/report assets; smoke/formal/advice mutations require POST and redirect to `/`.

- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_dashboard.py -q`; verify the new authoring cards/select/POST assertions fail against the current page.

- [ ] Add `WorkflowService.model_status`, `latest_change`, `run_authoring_scenario`, and merged `list_runs`. Keep existing lint/run APIs. Render the read-oriented cards and actions; do not add arbitrary editing/chat.

- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_dashboard.py tests/test_run_registry.py tests/test_cli_help.py -q`; expect exit `0`, then commit.

### Task 26: Documentation and hermetic test policy

**Files:** modify `README.md`, `docs/agent-operator-guide.md`, `docs/luban-workflow.md`, `tests/test_docs_examples.py`, `tests/test_stone_role_level.py`, `tests/test_stone_realm_progression.py`, `pyproject.toml`.

- [ ] RED-test documented `model init/status/apply/simulate`, exact one-change YAML, JSON envelope, progressive states, automatic smoke, source-of-truth, Dashboard scope, formal tuning handoff, and legacy compatibility.

- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_docs_examples.py -q`; verify the new workflow documentation assertions fail.

- [ ] Register `external_data`, mark the two Stone modules, and set default pytest addopts to `-m "not external_data"`. Document the explicit external command. Preserve current activity-output documentation edits by patching sections, not replacing files.

- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_docs_examples.py -q`; expect exit `0`, then commit only named files.

### Task 27: Deterministic real workflow and final verification

- [ ] Run the four commands in `Required Verification Commands` at the end of this plan; assert each exits `0` before continuing.

- [ ] Execute this rerunnable PowerShell workflow with a GUID directory and exact change files:

```powershell
$Project = Join-Path $env:TEMP ("igess-agent-authoring-" + [guid]::NewGuid().ToString("N"))
$ChangeDir = Join-Path $Project "proposals"

function Invoke-IgessJson([string[]]$CliArgs) {
  $text = & .\.venv\Scripts\python.exe -m igess.cli @CliArgs
  if ($LASTEXITCODE -ne 0) { throw "IGESS failed: $text" }
  return ($text | ConvertFrom-Json)
}
function Assert-True($Condition, [string]$Message) {
  if (-not $Condition) { throw $Message }
}

$Init = Invoke-IgessJson @("model", "init", "--out", $Project, "--id", "final_smoke", "--json")
Assert-True ($Init.ok -and $Init.code -eq "initialized") "init contract failed"
New-Item -ItemType Directory -Path $ChangeDir | Out-Null

@'
version: 1
operation: upsert
entity: resource
id: gold
fields:
  name: 金币
  dimension: currency
'@ | Set-Content -LiteralPath (Join-Path $ChangeDir "01-resource.yaml") -Encoding utf8

@'
version: 1
operation: upsert
entity: activity
id: gather
fields:
  name: 采集
  source_type: active
  unlock_condition: always
'@ | Set-Content -LiteralPath (Join-Path $ChangeDir "02-activity.yaml") -Encoding utf8

@'
version: 1
operation: upsert
entity: activity_output
id: gather_gold
fields:
  activity_id: gather
  output_resource: gold
  amount_per_second: "1"
'@ | Set-Content -LiteralPath (Join-Path $ChangeDir "03-output.yaml") -Encoding utf8

@'
version: 1
operation: upsert
entity: player_profile
id: default
fields:
  activity_weights:
    gather: "1"
'@ | Set-Content -LiteralPath (Join-Path $ChangeDir "04-weight.yaml") -Encoding utf8

@'
version: 1
operation: upsert
entity: scenario
id: balance_60s
fields:
  duration_hours: "0.0166666666666666666666666667"
  time_mode: tick
  profiles: [default]
  start_state: new_player
  record_interval_seconds: 10
  outputs: [resource_curve, purchase_timeline, unlock_timeline, prestige_timeline, bottleneck_report]
'@ | Set-Content -LiteralPath (Join-Path $ChangeDir "05-scenario.yaml") -Encoding utf8

$Blank = Invoke-IgessJson @("model", "status", "--project", $Project, "--json")
Assert-True ($Blank.ok -and $Blank.result.state -eq "incomplete") "blank must be incomplete"
$Applied = @()
Get-ChildItem -LiteralPath $ChangeDir -Filter *.yaml | Sort-Object Name | ForEach-Object {
  $Applied += ,(Invoke-IgessJson @("model", "apply", "--project", $Project, "--change", $_.FullName, "--json"))
}
Assert-True (($Applied | ForEach-Object { $_.ok }) -notcontains $false) "an apply failed"
$EarlyStates = @($Applied[0].result.status.state, $Applied[1].result.status.state, $Applied[2].result.status.state)
Assert-True (($EarlyStates | Where-Object { $_ -ne "incomplete" }).Count -eq 0) "early rules must remain incomplete"
Assert-True ($Applied[3].result.status.state -eq "runnable") "profile weight must make model runnable"
Assert-True ($Applied[3].result.smoke.status -eq "success") "runnable change must run smoke"
Assert-True (-not [string]::IsNullOrWhiteSpace($Applied[3].result.smoke.run_id)) "smoke run id missing"
Assert-True (Test-Path (Join-Path $Project "runs/$($Applied[3].result.smoke.run_id)/run_status.json")) "smoke artifact missing"
Assert-True ($Applied[4].result.status.state -eq "ready") "formal scenario must make model ready"
$Final = Invoke-IgessJson @("model", "simulate", "--project", $Project, "--scenario", "balance_60s", "--json")
Assert-True ($Final.ok -and $Final.result.kind -eq "formal" -and $Final.result.status -eq "success") "formal simulate failed"
Assert-True (Test-Path $Final.result.output_dir) "formal output missing"
Assert-True (Test-Path $Final.result.report_index) "formal report missing"
```

  The assertions mechanically prove blank/resource/activity/output are incomplete, profile weight makes runnable with smoke artifacts, formal scenario makes ready, and final simulation succeeds.

- [ ] Inspect workbooks, exports, change audit, run status, and report with this exact assertion command:

```powershell
@'
import json
import sys
from pathlib import Path
from openpyxl import load_workbook

root = Path(sys.argv[1])
workbooks = {
    "resources.xlsx": (["id", "name", "dimension"], "gold"),
    "activities.xlsx": (["id", "name", "source_type", "unlock_condition"], "gather"),
    "activity_outputs.xlsx": (["id", "activity_id", "output_resource", "amount_per_second"], "gather_gold"),
}
for filename, (fields, expected_id) in workbooks.items():
    sheet = load_workbook(root / "Datas" / filename, data_only=False).active
    rows = list(sheet.iter_rows(values_only=True))
    assert rows[0][0] == "##var" and list(rows[0][1:]) == fields
    assert rows[1][0] == "##" and rows[2][0] == "##type"
    assert all(value == "string" for value in rows[2][1:])
    assert expected_id in {str(row[1]) for row in rows[3:] if row[1] is not None}

def indexed(name):
    rows = json.loads((root / "luban_exports" / name).read_text(encoding="utf-8"))
    return {row["id"]: row for row in rows}

for filename, expected_id in [
    ("resources.json", "gold"),
    ("activities.json", "gather"),
    ("activity_outputs.json", "gather_gold"),
]:
    row = indexed(filename)[expected_id]
    assert row["_source"]["workbook"].endswith(".xlsx")
    assert row["_source"]["table"] == filename.removesuffix(".json")
    assert isinstance(row["_source"]["row"], int)

change_path = sorted((root / "changes").glob("*.json"))[-1]
change = json.loads(change_path.read_text(encoding="utf-8"))
run_status_path = sorted((root / "runs").glob("*/run_status.json"))[-1]
run_status = json.loads(run_status_path.read_text(encoding="utf-8"))
report_data = json.loads(
    (run_status_path.parent / "report" / "report_data.json").read_text(encoding="utf-8")
)
digest = change["post_digest"]
assert digest.startswith("sha256:")
assert run_status["model_digest"] == digest
assert report_data["scenario"]["model_digest"] == digest
'@ | .\.venv\Scripts\python.exe - $Project
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

- [ ] Run `git diff --check`, inspect `git status --short`, and verify the cached diff is empty after the final task commit. Re-run `.\.venv\Scripts\python.exe -m pytest -q`; expected exit `0` with only documented external-data tests deselected.

---

## Required Verification Commands

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_human_numbers.py tests/test_cli_help.py tests/test_cli_diagnostics.py tests/test_cli_scan.py tests/test_reporting_kpis.py tests/test_reporting_view_model.py tests/test_reporting.py tests/test_analyzer.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_authoring_response.py tests/test_authoring_entity_schema.py tests/test_authoring_change.py tests/test_authoring_project.py tests/test_authoring_yaml_source.py tests/test_authoring_workbook_source.py tests/test_authoring_exports.py tests/test_authoring_probe.py tests/test_authoring_status.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_authoring_locking.py tests/test_authoring_transactions.py tests/test_change_records.py tests/test_run_registry.py tests/test_authoring_service.py tests/test_authoring_cli.py tests/test_dashboard.py tests/test_docs_examples.py
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: all hermetic tests pass; external Stone workbook checks are deselected by default and remain runnable explicitly with `-m external_data`.
