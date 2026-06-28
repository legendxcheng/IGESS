# Stone Role Level Baseline

RoleLv source: `E:\stone-oasis\data-tables\Datas\RoleLv.xlsx`
Attribute definition source: `E:\stone-oasis\data-tables\Datas\CharacterAttributeDef.xlsx`

Number backend: `bignum_log` (`igess.numbers.SimNumber`)
Level count: 300
Min level: 1
Max level: 300
Level 1 combat power: 4310
Level 300 combat power: 1067640000000004000
Cumulative exp to max level start: 3524128815480423707430567

Formula:

- `BigNumberParts = sign * coeff * 10^exp`
- `big_number/integer contribution = value * powerValue`
- `ratio_bps contribution = value / 10000 * powerValue`
- `combat_power = sum(contributions)`
