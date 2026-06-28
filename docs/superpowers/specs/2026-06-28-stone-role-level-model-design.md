# Stone Role Level Model Design

## Purpose

Build the first `stone` project model in IGESS: a role level experience and
combat-power curve derived from the real stone-oasis Luban workbooks.

This step models only combat power. It intentionally does not analyze concrete
attribute display values beyond the minimum needed to reproduce runtime combat
power.

## Project Boundary

The game project workspace is `projects/stone/` under the IGESS repository.
Runtime outputs for this model go under:

```text
projects/stone/runs/role_level_baseline/
```

The source data remains in the external stone-oasis project:

```text
E:\stone-oasis\data-tables\Datas\RoleLv.xlsx
E:\stone-oasis\data-tables\Datas\CharacterAttributeDef.xlsx
```

The model reads those workbooks but does not modify them.

## Data Interpretation

`RoleLv.xlsx` uses Luban marker rows with nested `BigNumberParts` fields:

```text
value = sign * coeff * 10^exp
```

`CharacterAttributeDef.xlsx` supplies attribute definitions and `powerValue`
weights. Only rows with `enabled = 1` and `powerValue > 0` contribute to combat
power.

The runtime-compatible combat-power formula is:

```text
integer/big_number contribution = value * powerValue
ratio_bps contribution = value / 10000 * powerValue
combat_power = sum(contributions)
```

This matches stone-oasis Lua behavior in `AttributeAggregationService`:
`ratio_bps` values are divided by `10000` before multiplying by `powerValue`.

## Outputs

The first model run writes:

```text
role_level_curve.json
role_level_curve.csv
role_level_summary.md
source_manifest.json
```

Each level row contains:

- `level`
- `exp_req`
- `cumulative_exp_to_level_start`
- `cumulative_exp_to_next_level`
- `combat_power`
- `combat_power_delta`

The summary includes source paths, formula notes, level count, max level, and
sample checkpoints.

## Validation Targets

The implementation should lock these known values from the current source
workbooks:

- Level 1 combat power: `4310`
- Level 300 combat power: about `1.06764e18`
- Cumulative experience required to reach level 300 start: about `3.524129e24`
- Level count: `300`

## Non-Goals

- Do not edit stone-oasis source workbooks.
- Do not model realm, equipment, weapons, monsters, drops, or skills yet.
- Do not force this static curve into the existing generator/resource economy
  DSL.
- Do not produce tuning advice in this first step.
