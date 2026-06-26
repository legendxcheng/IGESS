# Luban Workflow

The simulator reads Luban export output, not hand-edited Excel files at runtime.

The sample authoring workbooks live in:

```text
data-tables/Datas/
  __tables__.xlsx
  resources.xlsx
  generators.xlsx
  upgrades.xlsx
  constants.xlsx
  milestones.xlsx
  prestige_layers.xlsx
```

Regenerate the sample source workbooks with:

```powershell
.\.venv\Scripts\python tools/create_sample_luban_sources.py
```

For v0.1, the sample runtime data lives in:

```text
examples/shelldiver_v0/luban_exports/
  resources.json
  generators.json
  upgrades.json
  constants.json
  milestones.json
  prestige_layers.json
```

These JSON files model the shape expected from a Luban export. In a production project, the source tables should be maintained in the project's normal Luban Excel directory and registered through its `__tables__.xlsx`, with shared beans/enums in `__beans__.xlsx` and `__enums__.xlsx` when needed.

## Required Export Tables

### resources

Required fields:

- `id`
- `name`

### generators

Required fields:

- `id`
- `name`
- `generator_type`
- `output_resource`
- `source_type`
- `base_output`
- `base_cost`
- `cost_resource`
- `cost_growth`
- `unlock_condition`

### upgrades

Required fields:

- `id`
- `name`
- `target`
- `modifier_type`
- `value`
- `cost_resource`
- `base_cost`
- `unlock_condition`

### constants

Required fields:

- `id`
- `value`

The simulator currently recognizes `starting_<resource_id>` constants, such as `starting_fish`.

### milestones

Optional fields:

- `id`
- `name`
- `condition`
- `reward_resource`
- `reward_amount`

### prestige_layers

Optional fields:

- `id`
- `name`
- `trigger_resource`
- `reward_resource`
- `formula`
- `divisor`
- `exponent`
- `min_gain`
- `reset_resources`
- `unlock_condition`

## Export Command Contract

Use the existing project Luban export command and point its JSON output directory at the CLI `--tables` argument.

Example placeholder:

```powershell
# Replace this with the real project Luban command once integrated.
.\Tools\Luban\luban.exe `
  -t client `
  -d json `
  --conf .\data-tables\luban.conf `
  --outputDataDir .\examples\shelldiver_v0\luban_exports
```

Then run:

```powershell
.\.venv\Scripts\python -m igess.cli lint --config examples/shelldiver_v0/economy.yaml --tables examples/shelldiver_v0/luban_exports
```

The linter should run before any simulation so broken ids, formulas, modifier targets, source types, profile references, and deterministic seed issues fail fast.
