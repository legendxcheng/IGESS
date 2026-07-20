# Fish RNG phase 1

This directory validates the current rules in
`E:\fish-oasis\gdd\05-核心随机算法.md` independently from the economy model.

`gdd-example.json` intentionally uses the seven-fish example pool and the
six-tier trash pool from the GDD. It is not the production fish table:
`E:\fish-oasis\gdd\data\tbfish.json` does not yet contain per-item
`FishDenominator` values.

For economy simulation, `strength` is mapped directly to `FishLuck`: locate the
configured strength interval, calculate logarithmic progress, apply smoothstep,
then interpolate between that pool's `start_luck` and `end_luck`. This is the
simulation shortcut selected for IGESS; it does not run the game's projectile
physics.

Run:

```powershell
.\.venv\Scripts\python.exe -m igess.cli fish-rng-run `
  --config projects\fish-rng\gdd-example.json `
  --out projects\fish-rng\runs\gdd-example
```
