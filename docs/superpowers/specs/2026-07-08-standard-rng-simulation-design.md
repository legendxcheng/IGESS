# Standard RNG Simulation Design

## Context

IGESS currently simulates deterministic incremental economies from YAML rules and
Luban-style table exports. The README lists probability gates as deferred. This
feature adds a standard RNG simulation path for Roblox-style RNG games without
changing the existing incremental simulation loop.

The approved first version models rarity-score rolls:

```text
roll_power = luck / u
```

where `u` is a deterministic random number in `(0, 1]`. A roll reaches rarity
denominator `D` when `roll_power >= D`, so the theoretical probability is
`min(1, luck / D)`.

## Approaches Considered

1. Add expected-value approximations to the existing economy run.
   This is fast but cannot show lucky/unlucky spread, first-hit percentiles, or
   rare-event distribution.

2. Add an independent RNG simulation command.
   This is recommended. It keeps the first version small, deterministic, and
   easy to test while preserving existing incremental behavior.

3. Build a full Roblox-like RNG progression model with inventory, crafting,
   trading value, potions, quests, and rebirth luck.
   This is useful later but too broad for the first pass.

## Scope

The first version adds:

- YAML `rng_tables` with `rarity_score` algorithm definitions.
- YAML `rng_scenarios` that select a table, profiles, roll count, trial count,
  and optional event threshold.
- Optional profile `luck`, defaulting to `1`.
- A deterministic RNG simulator using `model.random_seed`.
- Log-space rarity checks:
  `log_power = log(luck) - log(max(u, 1e-16))`.
- Output artifacts:
  `rng_summary.json`, `rng_distribution.csv`, `rng_events.json`,
  `rng_events.csv`, `rng_analysis.md`, and `rng_manifest.json`.
- CLI command:
  `igess rng-run --config <yaml> --scenario <rng_scenario> --out <dir>`.

The first version defers:

- Inventory limits and duplicate conversion.
- Dynamic luck from upgrades, potions, activity, or rebirth.
- Weighted item pools inside each rarity.
- Integration with existing resource production.
- Static HTML report integration.

## Architecture

`schema.py` gains dataclasses for RNG tables, RNG scenarios, and profile luck.
`loader.py` reads the new YAML sections. `linter.py` validates algorithm names,
positive denominators, ascending rarity thresholds, profile references, and
positive roll/trial counts. `builder.py` carries the RNG definitions into
`EconomyModel`.

A new `rng.py` module owns the RNG algorithm and Monte Carlo run. It returns
small dataclasses independent of the existing `SimulationResult`, because the
artifact shape is different from resource timelines.

A new `rng_outputs.py` module writes deterministic JSON, CSV, and Markdown
artifacts. `cli.py` wires the `rng-run` command.

## Data Flow

1. CLI loads the normal YAML config.
2. Linter validates existing economy sections plus RNG sections.
3. Builder creates an `EconomyModel` containing RNG definitions.
4. `RngSimulator` runs each configured profile for each trial using a stable
   seed derived from model seed, scenario id, profile id, and trial index.
5. Every roll picks the highest denominator whose log threshold is reached.
6. The simulator records per-profile rarity counts, first-hit roll indexes,
   trial best rarity, and optional high-rarity events.
7. `RngOutputWriter` writes deterministic artifacts.

## Error Handling

Invalid RNG config fails before simulation with actionable `ConfigError`
messages. Runtime clamps `u` to at least `1e-16`. Luck must be positive before
simulation; profile luck defaults to `1` when omitted.

## Testing

Tests follow TDD:

- Rarity-score selection reaches the highest eligible denominator.
- Theoretical probabilities are `min(1, luck / denominator)`.
- RNG runs are deterministic with the same seed.
- CLI `rng-run` writes all expected artifacts.
- Linter rejects invalid algorithm names, non-positive denominators, and invalid
  RNG scenario references.
