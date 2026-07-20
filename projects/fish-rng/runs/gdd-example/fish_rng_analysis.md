# Fish RNG Simulation

- Scenario: `gdd_example_baseline`
- Throws: 1,000,000
- Cycle: 30 seconds
- Represented continuous play: 347.22 days
- Strength: 100.0
- Strength pool: 2 (50.0..2000.0)
- Log progress: 0.18790182
- Smooth progress: 0.09265275
- Base Fish Luck: 5.92652752
- Regular Luck multiplier: 1.0
- Fish Luck: 5.92652752
- Trash Luck: 20.0

## BonusChain validation

- First-layer observed: {'no_bonus': 0.735947, 'mutation': 0.163947, 'luck_double': 0.100106}
- First-layer theoretical: {'no_bonus': 0.736, 'mutation': 0.164, 'luck_double': 0.1}
- Any mutation: observed 0.182185, theoretical 0.182204
- Any Luck ×2: observed 0.116652, theoretical 0.1164
- E[FinalFishLuck / FishLuck]: observed 1.150646, theoretical 1.149728
- Layer reach observed: {'1': 1.0, '2': 0.264053, '3': 0.043186, '4': 0.006008}
- Layer reach theoretical: {'1': 1.0, '2': 0.264, '3': 0.0428, '4': 0.00592}

## Reward distributions

- Fish: {'common_a': 0.359649, 'rare_b': 0.572144, 'epic_c': 0.061361, 'legendary_d': 0.006122, 'mythic_e': 0.000446, 'mythic_f': 0.000271, 'secret_g': 7e-06}
- Trash: {'common': 0.0, 'rare': 0.80054, 'epic': 0.179621, 'legendary': 0.017807, 'mythic': 0.002001, 'secret': 3.1e-05}
- Mutation per throw: {'gold': 0.100006, 'diamond': 0.040012, 'plasma': 0.030387, 'molten': 0.007919, 'radioactive': 0.003072, 'shadow': 0.000516, 'electrified': 0.000204, 'rainbow': 5.1e-05, 'astral': 1.8e-05}

## Independence

- Pearson correlation of log RollPower: 0.00084637
- Pearson correlation of selected reward rank: 0.00197749
