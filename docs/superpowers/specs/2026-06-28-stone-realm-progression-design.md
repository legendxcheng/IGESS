# Stone Realm Progression Design

## Purpose

Build the second `stone` project model in IGESS: a role realm combat-power
curve derived from the real stone-oasis Luban workbooks.

This step models only combat power contributed by realm. It intentionally keeps
realm combat power separate from level combat power because the same role level
can exist at different realms.

## Project Boundary

The game project workspace is `projects/stone/` under the IGESS repository.
Runtime outputs for this model go under:

```text
projects/stone/runs/realm_progression_baseline/
```

The source data remains in the external stone-oasis project:

```text
E:\stone-oasis\data-tables\Datas\RoleRealm.xlsx
E:\stone-oasis\data-tables\Datas\CharacterAttributeDef.xlsx
```

The model reads those workbooks but does not modify them.

## Data Interpretation

`RoleRealm.xlsx` uses Luban marker rows with nested `BigNumberParts` fields:

```text
value = sign * coeff * 10^exp
```

`CharacterAttributeDef.xlsx` supplies attribute definitions and `powerValue`
weights. Only fields whose names exist in the attribute definition table, have
`enabled = 1`, and have `powerValue > 0` contribute to combat power.

Realm fields such as `powerReq`, `success`, `costItem`, `selfreward`, and
`areareward` are progression requirements or rewards, not combat-power
attributes, so they are not included.

The runtime-compatible combat-power formula is:

```text
integer/big_number contribution = value * powerValue
ratio_bps contribution = value / 10000 * powerValue
realm_combat_power = sum(contributions)
```

## Outputs

The realm model run writes:

```text
realm_progression_curve.json
realm_progression_curve.csv
realm_progression_summary.md
source_manifest.json
```

Each row contains:

- `realm_id`
- `realm_name`
- `level_cap`
- `realm_combat_power`
- `realm_combat_power_delta`

`level_cap` is copied from `RoleRealm.lvl_up` only as metadata. It is not used
to combine level and realm combat power in this model.

## Validation Targets

The implementation should lock these known values from the current source
workbooks:

- Realm count: `31`
- Realm 0 `凡人` combat power: `0`
- Realm 1 `炼气` combat power: `360000`
- Realm 29 `金仙中期` combat power: `5400000000000000000`
- Realm 30 `金仙后期` combat power: `3600000000000000000`

Realm 30 preserves the source-table edge case where `atk.sign` exports as `0`,
so attack contributes no combat power for that row.

## Non-Goals

- Do not edit stone-oasis source workbooks.
- Do not add level combat power into realm combat power.
- Do not model tribulation success probability, costs, rewards, equipment,
  weapons, monsters, drops, or skills yet.
- Do not produce tuning advice in this step.
