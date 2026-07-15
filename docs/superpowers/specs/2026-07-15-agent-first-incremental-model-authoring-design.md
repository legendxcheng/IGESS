# Agent-First Incremental Model Authoring Design

## Goal

Turn IGESS into an Agent-first numerical-design workspace where an Agent can add
one game-economy rule at a time, persist it to the project's formal
`economy.yaml` and Luban Excel sources, validate immediately, and run a smoke
simulation as soon as the partial model forms a valid executable loop.

The primary user is comfortable with Python and works with an Agent. The design
therefore prioritizes a stable machine-readable CLI, incremental validation,
auditable mutations, and useful reports over a no-code editor.

## Product Workflow

The intended workflow is:

1. Create a blank but structurally valid authoring project.
2. The Agent asks the user for one rule or one coherent rule group.
3. The Agent submits a structured change to IGESS.
4. IGESS validates the change in memory before mutating project files.
5. IGESS atomically writes the affected YAML or Luban workbook, exports runtime
   JSON, and runs strict linting.
6. IGESS derives model completeness from current source files.
7. If the model is runnable, IGESS runs a short deterministic smoke simulation.
8. IGESS returns a concise human summary and stable machine-readable result.
9. The Agent continues filling rules until the model is ready for formal runs,
   parameter scans, comparisons, gates, and advice.

Partial models are normal. An incomplete model is not treated as a generic
failure when its existing rules are structurally valid.

## Considered Approaches

### Existing-file editing plus CLI polish

The Agent would edit YAML and Excel directly and call existing commands. This is
the smallest change, but it leaves mutation safety, schema mapping, rollback,
and progressive completeness reasoning in every individual Agent workflow.

### Agent-native incremental model commands

IGESS owns structured mutations, persistence, export, validation, completeness,
and smoke simulation. This creates one auditable contract for Agents and keeps
formal project files as the source of truth. This is the selected approach.

### Full Web authoring wizard

A browser wizard could guide nontechnical users, but it duplicates the Agent's
role and carries substantially more UI complexity. The Dashboard will remain an
observability and operations surface rather than becoming a no-code editor.

## Source of Truth

Formal project data remains split according to the existing IGESS and Luban
contract:

- `economy.yaml` owns model configuration, formulas, source types, modifier
  policy, player profiles, scenarios, RNG scenarios, and regression gates.
- `Datas/*.xlsx` owns resources, generators, activities, activity outputs,
  upgrades, constants, milestones, and prestige layers.
- `luban_exports/*.json` is generated runtime data and is never the authoring
  source.

Agents do not write workbook cells directly. They submit structured changes to
IGESS, which maps entities to the correct YAML section or workbook.

## Project Initialization

`igess model init --out projects/<project_id> [--id <model_id>]` creates an
authoring-ready project. `model_id` defaults to the output directory name after
replacing characters outside `[A-Za-z0-9_-]` with `_`. The command accepts an
absent or empty target directory and refuses a non-empty target. Version 1 does
not provide `--force`.

The command creates:

```text
projects/<project_id>/
  economy.yaml
  Datas/
    __tables__.xlsx
    resources.xlsx
    generators.xlsx
    activities.xlsx
    activity_outputs.xlsx
    upgrades.xlsx
    constants.xlsx
    milestones.xlsx
    prestige_layers.xlsx
  luban_exports/
  runs/
  reports/
  changes/
  README.md
  run.ps1
```

The generated YAML contains engine defaults but no sample-game content:

- `bignum_log` backend;
- deterministic seed and fixed tick configuration;
- standard cost and production formulas;
- one default player profile;
- one short deterministic `smoke` scenario.

The defaults also include the current standard generator type, source types,
modifier pipeline and modifier types, `cheap_unlock_first` behavior policy, and
an `authoring_default` session pattern. The `default` profile assigns efficiency
`1` to every standard source type, uses `cheap_unlock_first`, has no activity
weights, and uses luck `1`. The `smoke` scenario uses fixed-tick mode, the
`default` profile, one-second recording, and a ten-tick duration. These defaults
make all profile and policy references self-contained before game content is
added.

Workbooks are registered and structurally valid but contain no game-specific
rows. The generated README documents the incremental Agent workflow, source of
truth, common commands, and artifact locations. `run.ps1` performs model status
and smoke execution without requiring users to reconstruct long commands.

The existing `igess init` command keeps its current sample-copy behavior and
tests. It does not delegate to `model init`; the two commands serve different
purposes.

## Incremental Change Protocol

The main commands and their exact version 1 arguments are:

```powershell
igess model init --out PATH [--id MODEL_ID] [--json]
igess model status [--project PATH] [--json]
igess model apply [--project PATH] (--change FILE | --stdin) [--format yaml|json] [--json]
igess model simulate [--project PATH] [--scenario ID] [--json]
```

`--project` defaults to the current directory. `model status`, `model apply`,
and `model simulate` discover `economy.yaml`, `Datas/`, and `luban_exports/`
directly below that directory. `model apply` requires exactly one of `--change`
or `--stdin`. File format is selected from `.yaml`, `.yml`, or `.json`; standard
input is YAML unless `--format json` is supplied. `model simulate` defaults to
the `smoke` scenario and always creates standard run output plus a static report
in the project run registry.

Example:

```yaml
version: 1
operation: upsert
entity: resource
id: gold
fields:
  name: 金币
  dimension: currency
```

Another example:

```yaml
version: 1
operation: upsert
entity: generator
id: mine
fields:
  name: 金矿
  generator_type: building
  output_resource: gold
  source_type: generator
  base_output: "1"
  base_cost: "10"
  cost_resource: gold
  cost_growth: "1.15"
  unlock_condition: always
```

The initial entity set matches the existing model surface:

- resource;
- generator;
- activity;
- activity output;
- upgrade;
- constant;
- milestone;
- prestige layer;
- formula;
- generator type;
- source type;
- modifier type;
- behavior policy;
- session pattern;
- player profile;
- scenario;
- RNG table;
- RNG scenario;
- regression gate.

The protocol is versioned. Unsupported versions, operations, entities, and
fields fail before mutation. The first version supports `upsert`; deletion and
batch transactions are deferred until a concrete workflow requires them.

### Upsert semantics

Entity identity is the pair `(entity, id)`. Creating an absent id requires every
field marked required by the canonical entity schema. Updating an existing id
uses JSON Merge Patch semantics for `fields`: nested mappings merge recursively,
lists replace, omitted fields remain unchanged, and `null` removes an optional
field. Removing a required field fails validation. Duplicate ids already present
in a workbook or YAML mapping make current model status `failed`; `upsert` never
chooses one duplicate implicitly.

Economic numeric fields accept decimal strings or integers. YAML/JSON floating
point tokens are rejected so parsing never depends on binary float semantics.
Boolean fields must be booleans, not `0`/`1` strings. Lists and mappings must be
their native YAML/JSON types.

An optional top-level `if_model_digest` lets an Agent reject a stale proposal.
Whether or not it is supplied, IGESS hashes all model source files before
staging and verifies the same hashes immediately before commit. Concurrent
source changes therefore fail with `stale_model` rather than being overwritten.

### Canonical table entity schemas

| Entity | Storage | Required on create | Optional |
| --- | --- | --- | --- |
| `resource` | `resources.xlsx` | `name`, `dimension` | none |
| `generator` | `generators.xlsx` | `name`, `generator_type`, `output_resource`, `source_type`, `base_output`, `base_cost`, `cost_resource`, `cost_growth`, `unlock_condition` | none |
| `activity` | `activities.xlsx` | `name`, `source_type`, `unlock_condition` | none |
| `activity_output` | `activity_outputs.xlsx` | `activity_id`, `output_resource`, `amount_per_second` | none |
| `upgrade` | `upgrades.xlsx` | `name`, `target`, `modifier_type`, `value`, `cost_resource`, `base_cost`, `unlock_condition` | none |
| `constant` | `constants.xlsx` | `value` | none |
| `milestone` | `milestones.xlsx` | `name`, `condition`, `reward_resource`, `reward_amount` | none |
| `prestige_layer` | `prestige_layers.xlsx` | `name`, `trigger_resource`, `reward_resource`, `formula`, `divisor`, `exponent`, `min_gain`, `reset_resources`, `unlock_condition` | none |

`id` comes from the envelope and cannot also appear in `fields`. Every generated
row receives deterministic `_source` metadata during export.

### Canonical YAML entity schemas

| Entity | YAML mapping | Required on create | Optional |
| --- | --- | --- | --- |
| `formula` | `formulas` | `args`, `expr` | none |
| `generator_type` | `generator_types` | `cost_formula`, `production_formula` | none |
| `source_type` | `source_types` | `description` | none |
| `modifier_type` | `modifier_types` | `stage` | none |
| `behavior_policy` | `behavior_policies` | `type` | `lookahead_depth`, `include_unlock_chain_value` |
| `session_pattern` | `session_patterns` | `offline_every_seconds`, `offline_duration_seconds` | none |
| `player_profile` | `player_profiles` | `source_efficiency`, `behavior_policy`, `session_pattern`, `prestige_policy` | `activity_weights`, `luck` |
| `scenario` | `scenarios` | `duration_hours`, `time_mode`, `profiles`, `start_state`, `record_interval_seconds`, `outputs` | none |
| `rng_table` | `rng_tables` | `algorithm`, `rarities` | none |
| `rng_scenario` | `rng_scenarios` | `table`, `rolls`, `trials`, `profiles` | `event_threshold` |
| `regression_gate` | `regression_gates` | at least one supported gate rule | supported gate rules not supplied by this change |

### Field type contract

`id` values are non-empty strings matching `[A-Za-z0-9_.-]+`. `text` is a
non-empty UTF-8 string. `decimal` is either an integer token or a base-10 string
matching `-?digits[.digits][e[+|-]digits]`; float tokens are rejected. Positive
and non-negative decimal types apply the stated bound after exact
`SimNumber.parse`. `condition` is exactly `always` or
`owned(<generator_id>) <op> <non-negative integer>` where `<op>` is one of
`>=`, `<=`, `==`, `>`, or `<`.

Table-backed fields have these types and constraints:

- `resource`: `name:text`, `dimension:id`.
- `generator`: `name:text`, `generator_type:id`, `output_resource:id`,
  `source_type:id`, `base_output:non-negative decimal`,
  `base_cost:non-negative decimal`, `cost_resource:id`,
  `cost_growth:positive decimal`, `unlock_condition:condition`.
- `activity`: `name:text`, `source_type:id`, `unlock_condition:condition`.
- `activity_output`: `activity_id:id`, `output_resource:id`,
  `amount_per_second:positive decimal`.
- `upgrade`: `name:text`, `target` matching `generator:<id>.output` or
  `generator:*.output`, `modifier_type:id`, `value:decimal`,
  `cost_resource:id`, `base_cost:non-negative decimal`,
  `unlock_condition:condition`.
- `constant`: `value:decimal`.
- `milestone`: `name:text`, `condition:condition`, `reward_resource:id`,
  `reward_amount:decimal`.
- `prestige_layer`: `name:text`, `trigger_resource:id`, `reward_resource:id`,
  `formula:id`, `divisor:positive decimal`, `exponent:positive decimal`,
  `min_gain:non-negative decimal`, `reset_resources:list[id]`,
  `unlock_condition:condition`.

YAML-backed fields have these types and constraints:

- `formula`: `args:list[id]`, `expr:text` accepted by the safe formula compiler.
- `generator_type`: `cost_formula:id`, `production_formula:id`.
- `source_type`: `description:text`.
- `modifier_type`: `stage` in `flat|add_pct|mult|exp`.
- `behavior_policy`: `type` in
  `cheap_unlock_first|fastest_payback|new_content_bias`, optional
  `lookahead_depth:non-negative integer`, optional
  `include_unlock_chain_value:boolean`.
- `session_pattern`: `offline_every_seconds:positive integer`,
  `offline_duration_seconds:non-negative integer`.
- `player_profile`: `source_efficiency:map[id, non-negative decimal]`,
  `behavior_policy:id`, `session_pattern:id`, `prestige_policy` in
  `conservative|efficient_reset|milestone_based`, optional
  `activity_weights:map[id, non-negative decimal]`, optional
  `luck:positive decimal`.
- `scenario`: `duration_hours:positive decimal`, `time_mode` in
  `tick|analytic`, `profiles:non-empty list[id]`, `start_state:new_player`,
  `record_interval_seconds:positive integer`, and `outputs:list` drawn from
  `resource_curve|purchase_timeline|unlock_timeline|prestige_timeline|bottleneck_report`.
- `rng_table`: `algorithm:rarity_score`,
  `rarities:non-empty map[id, positive decimal]` with unique denominators; the
  loader orders rarities by exact denominator and the resulting order must be
  strictly increasing.
- `rng_scenario`: `table:id`, `rolls:positive integer`,
  `trials:positive integer`, `profiles:non-empty list[id]`, and optional
  `event_threshold:id` that exists in the selected table.
- `regression_gate`: its envelope id is a scenario id; fields may contain
  `max_unlock_delay_pct:map[text, non-negative decimal]`,
  `max_payback_seconds:map[text, non-negative decimal]`, and
  `min_prestige_gain:map[id, non-negative decimal]`, with at least one non-empty
  rule map.

`model`, `modifier_pipeline`, and engine-default mappings are created by
`model init` and are not mutable through protocol version 1. YAML is written in
deterministic canonical form using UTF-8, LF, preserved insertion order, and
unquoted ids where safe. Comments are not preserved in version 1. Workbook
updates preserve marker rows, column order, styles, formulas, and unrelated
cells; new rows copy the style of the nearest data row or the template row.

### JSON command envelope

Every `--json` response uses this outer shape:

```json
{
  "schema_version": 1,
  "command": "model.apply",
  "ok": true,
  "code": "applied",
  "message": "Applied resource:gold; model is incomplete",
  "details": {},
  "result": {}
}
```

`details` contains structured validation or error context. `result` contains the
command-specific payload. Human output is rendered from the same response.

`model status` result contains `model_digest`, `structural_valid`,
`smoke_eligible`, `state`,
`entity_counts`, `missing_requirements`, `warnings`, `available_scenarios`, and
`latest_smoke_run_id`. `model apply` adds `change_id`, `entity`, `id`,
`changed_files`, `status`, and `smoke`. `model simulate` adds the serialized run
record and artifact paths.

The command-specific result contracts are:

| Command | Result fields and types |
| --- | --- |
| `model.init` | `project`, `model_id`, `config`, `datas`, `tables`, `readme`, `run_script`: strings |
| `model.status` | `model_digest`: string; `structural_valid`, `smoke_eligible`: bool; `state`: `incomplete|runnable|ready|failed`; `entity_counts`: object of integer counts; `missing_requirements`, `warnings`: ordered arrays of `{code, message, entity?, id?}`; `available_scenarios`: string array; `latest_smoke_run_id`: string or null |
| `model.apply` | `change_id`, `entity`, `id`: strings; `changed_files`: string array; `status`: complete `model.status` result; `smoke`: `{status: not_run|success, run_id: string|null, findings: array}` |
| `model.simulate` | `run_id`, `kind`, `scenario_id`, `status`, `output_dir`, `report_index`: strings; `change_id`: string or null |

An incomplete status response is still successful:

```json
{
  "schema_version": 1,
  "command": "model.status",
  "ok": true,
  "code": "status",
  "message": "Model is valid but incomplete",
  "details": {},
  "result": {
    "model_digest": "sha256:...",
    "structural_valid": true,
    "smoke_eligible": false,
    "state": "incomplete",
    "entity_counts": {"resource": 1, "generator": 0},
    "missing_requirements": [
      {"code": "resource_without_source", "message": "resource gold has no starting amount or production source", "entity": "resource", "id": "gold"}
    ],
    "warnings": [],
    "available_scenarios": ["smoke"],
    "latest_smoke_run_id": null
  }
}
```

A committed runnable change uses `code: applied`, includes the full post-change
status, and sets `smoke.status: success`. Balance warnings appear as structured
entries in `smoke.findings` without changing `ok` to false. A failure uses the
same outer envelope, an empty or partial result, and structured details:

```json
{
  "schema_version": 1,
  "command": "model.apply",
  "ok": false,
  "code": "invalid_change",
  "message": "generator:mine is missing required field cost_growth; no model files changed",
  "details": {"entity": "generator", "id": "mine", "field": "cost_growth"},
  "result": {}
}
```

The exception is `model status`: even when `ok: false`, its `result` is the full
typed status payload with `structural_valid: false`, `smoke_eligible: false`,
`state: failed`, all entity counts that could be read, ordered validation errors
in `missing_requirements`, discovered scenarios, and the latest prior smoke id.

Exit code `0` means the command completed as requested, including a valid
`incomplete` status or a committed change with simulation findings. Exit code
`1` means validation, stale input, staging, smoke execution, recovery, or commit
failed. Argparse usage errors remain exit code `2`. In JSON mode, exit code `1`
always returns `ok: false` and a stable `code` such as `invalid_change`,
`stale_model`, `model_invalid`, `smoke_failed`, or `commit_failed`.

## Mutation Transaction

`model apply` performs one recoverable transaction:

1. Parse and validate the change envelope.
2. Load current YAML and registered workbook sources.
3. Create `.igess/transactions/<change_id>/` with a `prepared` journal,
   candidate source files, candidate exports, and backups of every commit target.
4. Apply the mutation only to the candidate copy.
5. Export candidate runtime tables, validate, and derive completeness.
6. If the candidate is statically smoke-eligible, run the ten-tick probe against
   it and stage the complete run artifacts and report.
7. Recheck current source hashes against the pre-stage digest.
8. Mark the journal `committing`, replace the affected source and full export
   directory, move staged smoke artifacts into the run registry, write the
   change record, then mark the journal `committed`.
9. Remove transaction backups after the committed journal and audit record are
   durable.

Every `model` command begins with an exclusive recovery phase on
`.igess/model.lock`. While holding it, the command restores any transaction whose
journal is not `committed`, removes its staged outputs, and records a
`recovered_transaction` warning. It also removes leftover backups or staging
directories for already committed journals. A mutating command retains the
exclusive lock through staging, digest recheck, commit, and cleanup. Status and
simulation release the exclusive recovery lock and then acquire a shared lock
before loading their consistent source snapshot; a writer that wins the gap
completes before that shared snapshot is taken.

The implementation uses standard-library OS file locking (`msvcrt` on Windows
and `fcntl` on POSIX), so a crashed process releases the lock automatically and
does not leave a stale lock decision to the user. Recovery handles a process or
machine failure between multiple `os.replace` operations. The lock serializes
concurrent writers, while optimistic source digests reject an Agent proposal
created from an older model state.

Failed attempts that occur after a project and change id are known write a
record under `changes/failed/`; this audit write does not alter formal model
sources or runtime exports. Parsing, mapping, export, validation, smoke engine,
artifact, stale-write, or commit failures leave or restore formal sources and
exports to their previous consistent state. Simulation balance findings are a
successful mutation with warnings; simulator or artifact failures roll back.

## Progressive Model Status

`model status` derives state from current files rather than trusting a manually
maintained state cache.

Under its shared snapshot lock, `model status` and `model simulate` export
`Datas/` into a command-scoped temporary directory and load that export with the
current YAML. They never evaluate source workbooks against possibly stale
committed JSON. They compare the temporary export digest with
`luban_exports/`; missing or stale committed exports add an `exports_stale`
warning but do not change source-derived completeness. These read/simulation
commands do not overwrite committed exports. `model apply` is the operation that
commits synchronized source and runtime exports.

It returns one of:

- `incomplete`: existing rules are structurally valid, but the model is not yet
  executable;
- `runnable`: the partial model can run the deterministic smoke scenario;
- `ready`: the project also has at least one non-smoke scenario and the inputs
  required for reporting and tuning workflows;
- `failed`: current sources are malformed or internally inconsistent.

Structural validity means all supplied records conform to their entity schemas,
ids are unique, formula syntax is safe, and every reference that can be checked
against an existing entity resolves. Missing content needed to execute is a
completeness issue, not a structural error.

Static smoke eligibility is deterministic and requires:

- a valid smoke scenario and referenced player profiles;
- valid formula compilation;
- all referenced resources and content ids to exist;
- at least one resource row;
- at least one positive activity path: an `always` activity, a positive output,
  a positive activity weight in every smoke profile, and positive source
  efficiency; or at least one affordable positive generator path: an `always`
  generator with positive output and source efficiency whose starting
  cost-resource amount is at least its base cost.

`model status` runs an in-memory ten-tick probe when statically eligible but does
not create run artifacts. `model apply` runs the same probe against the staged
candidate and persists the probe artifacts after commit. There is no skip-smoke
flag in protocol version 1.

Observable change means a resource value, owned-generator count,
purchased-upgrade set, or prestige value differs between the initial and final
state. Elapsed time and unlock/event records alone do not count. A successful
probe with no observable change produces `state: incomplete` plus
`smoke_no_state_change`; it is not an engine failure. A build, execution, or
artifact error produces `state: failed` and prevents an apply commit.

State is `runnable` after the probe completes with observable change. State is
`ready` when runnable and at least one valid scenario other than `smoke` exists.
Reporting works for any successful run; scan, compare, gates, and advice keep
their existing command-specific preconditions rather than being folded into
`ready`.

Status includes ordered, actionable missing requirements. For example:

```text
Model valid but not runnable.
Missing:
- resource gold has no starting amount or production source
- no executable economy behavior is currently available
```

Every applied rule reruns status. Statically eligible candidates receive a fresh
short smoke run, including eligible probes that complete with no state change;
other incomplete models report what to add next without running the simulator.

## CLI Experience

All existing and new commands receive:

- command descriptions;
- argument help and defaults;
- concise examples;
- stable documented exit codes;
- domain-specific validation messages.

Protocol version 1 adds `--json` to the four `model` commands only. Existing
commands retain their current stdout and artifact contracts; their JSON, CSV,
and manifest artifacts remain the Agent-readable results. Adding a common JSON
envelope to legacy commands is deferred to avoid an unnecessary compatibility
change.

Important error behavior includes:

- unknown scenarios list available scenario ids;
- invalid scan ranges show the supported syntax and an example;
- missing paths identify whether the config, source workbook directory, runtime
  export directory, run directory, or proposal is absent;
- invalid model changes identify the entity, field, rejected value, and allowed
  form;
- mutation failures state that no project files were changed.

Human-readable output is concise. JSON output contains stable codes and exact
numeric strings so Agents do not need to parse prose. A successful incomplete
apply uses `ok: true`, `code: applied`, `result.status.state: incomplete`, and an
ordered `missing_requirements` list. A successful smoke with balance warnings
still uses `ok: true` and exposes findings under `result.smoke.findings`.

## Run and Change Records

All automatic smoke and operations launched through `model simulate` or the
Dashboard use the existing `RunRegistry`, extended with `kind` (`smoke`,
`formal`, or `advice`) and optional `change_id`. Direct legacy `run` and `advise`
CLI invocations keep their explicit `--out` behavior and are not silently added
to the registry. New authoring projects store records under
`runs/<run_id>/`; each record contains `run_status.json`, `output/`, and
`report/`. Existing Dashboard projects that use `.igess/runs` remain readable.

Run ids remain UTC timestamp based. Automatic smoke records include
`-smoke-<change_id>`. A committed change record at
`changes/<timestamp>-<change_id>.json` contains the change envelope, pre/post
model digests, affected files, status response, and correlated `run_id`.
Every run status record also stores the exact source `model_digest` used for the
simulation so reports remain attributable after later edits.

Automatic smoke retention defaults to the newest 20 successful or failed smoke
runs. Pruning occurs only after a committed change and never removes formal or
advice records. `model simulate` never prunes its own manual/formal result.

## Dashboard

The Dashboard remains lightweight and read-oriented. It adds:

- model status (`incomplete`, `runnable`, `ready`, or `failed`);
- defined-entity counts and missing requirements;
- latest applied rule and validation result;
- latest smoke summary;
- a scenario selector populated from the current model;
- actions for status refresh, smoke execution, formal run, and advice;
- unified smoke, formal-run, and advice history with artifact links.

The Dashboard reads model state through the same status service used by the CLI
and reads operation history through `RunRegistry`; it does not infer state from
HTML or scan arbitrary folders. The Dashboard does not include chat or
arbitrary rule/table editing. Rule authoring remains an Agent-to-CLI workflow.

## Reports and Human Number Formatting

Static report Overview gains decision-oriented KPIs with exact definitions:

- scenario duration: maximum `time_seconds` in the timeline, plus the manifest's
  ordered player-profile ids;
- final resources by profile: resource mapping from that profile's greatest
  `time_seconds` timeline row;
- purchase count: events whose kind starts with `buy_`;
- first key unlock: earliest event with kind `unlock_generator`,
  `unlock_upgrade`, or `unlock_activity`, excluding events at time zero; ties
  sort by `profile_id`, `kind`, then `item_id`;
- prestige reset count: events with kind `prestige_reset`;
- worst payback: `Infinity` wins; otherwise the row with maximum Decimal
  `payback_seconds`, retaining its profile, kind, and item id; infinite or equal
  rows tie-break by `profile_id`, `kind`, then `item_id`;
- counts of never-purchased and never-unlocked ids from the existing invalid
  content report;
- warning-category count: number of non-empty categories among never purchased,
  never unlocked, overpowered content, infinite payback, and bottleneck gaps.

All calculation, JSON, CSV, manifests, gates, and `--json` CLI responses retain
exact `SimNumber` strings. Human-facing CLI, Markdown, and HTML use a shared
formatter with six significant digits and scientific notation when appropriate.
HTML exposes the exact value through detail text or tooltips.

Examples:

```text
739.864019013290554... -> 739.864s
1067640000000004000   -> 1.06764e18
```

Formatting is presentation-only and never feeds calculations or tuning
decisions.

The shared human formatter parses exact decimal strings without converting to
float. Zero renders as `0`. Finite values with absolute magnitude in
`[1e-4, 1e6)` use fixed notation; other non-zero finite values use lowercase
scientific notation. Both modes round to six significant digits with
`ROUND_HALF_EVEN` and remove trailing fractional zeros and a redundant `+` or
leading exponent zeros. `Infinity`, `-Infinity`, `NaN`, empty, and missing values
render unchanged according to their source contract.

Report view-model schema version 2 represents human numeric fields as
`{"exact_value": "...", "display_value": "..."}` while retaining a separate
bounded `chart_value`. HTML uses `display_value` and exposes `exact_value` in a
tooltip or details element. JSON/CSV simulation artifacts remain unchanged.

## Compatibility

Existing commands and artifacts remain valid:

- `export-tables`;
- `lint`;
- `run`;
- `report`;
- `compare`;
- `scan`;
- `gate`;
- `advise`;
- verification and YAML-plan commands.

`run_manifest.json`, timeline/event JSON and CSV, `analysis.json`, `payback.csv`,
and report data preserve their existing exact-value contracts unless a schema
version explicitly changes in future work.

## Testing Strategy

Implementation follows test-driven development. Coverage includes:

- change protocol parsing and validation;
- entity-to-YAML and entity-to-workbook mapping;
- atomic rollback after mapping, export, lint, and persistence failures;
- derived `incomplete`, `runnable`, `ready`, and `failed` states;
- automatic smoke behavior;
- exact JSON and concise human output;
- actionable CLI errors and help text;
- authoring-ready project initialization;
- Dashboard model state and scenario selection;
- report KPI view model and number presentation;
- compatibility with existing simulation, reporting, scan, gate, advice, and
  verification tests.

External Stone workbooks are integration inputs rather than hermetic unit-test
fixtures. Their data-dependent assertions should be isolated or pinned so a
separate repository update does not make the IGESS core suite appear broken.

## Delivery Slices

The feature is one workflow but is implemented in independently testable
slices:

1. Agent-facing CLI descriptions, stable errors, shared response envelope, and
   human number formatting.
2. Authoring project initialization, change schemas, source adapters, derived
   model status, and recoverable apply transaction.
3. Smoke execution, change/run correlation, retention, and extended run
   registry.
4. Dashboard model observability and scenario selection.
5. Report KPI view model and compact human presentation.

Each slice preserves existing commands and ends with its focused tests plus the
current compatibility suite.

## Scope Boundaries

The first implementation intentionally excludes:

- Dashboard chat;
- a general no-code model editor;
- inference of arbitrary third-party workbook layouts;
- automatic acceptance of tuning recommendations;
- replacement of a production Luban pipeline;
- deletion and multi-change batch transactions without an observed need.

The Agent remains responsible for discussing intent and asking the user for the
next rule. IGESS is responsible for making each accepted rule safe, persistent,
auditable, and executable as early as possible.
