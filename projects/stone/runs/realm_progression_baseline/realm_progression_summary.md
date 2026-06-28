# Stone Realm Progression Baseline

RoleRealm source: `E:\stone-oasis\data-tables\Datas\RoleRealm.xlsx`
Attribute definition source: `E:\stone-oasis\data-tables\Datas\CharacterAttributeDef.xlsx`

Number backend: `bignum_log` (`igess.numbers.SimNumber`)
Realm count: 31
Level combat power is not included; `level_cap` is metadata only.
First realm: 0 凡人
Last realm: 30 金仙后期
First realm combat power: 0
Last realm combat power: 3600000000000000000

Formula:

- `BigNumberParts = sign * coeff * 10^exp`
- `big_number/integer contribution = value * powerValue`
- `ratio_bps contribution = value / 10000 * powerValue`
- `realm_combat_power = sum(contributions)`
