# Fish RNG phase 1

> 当前统一进度请查看 [`../fish/RoadMap.md`](../fish/RoadMap.md)。本目录只保留 RNG、存档模型和架构参考，不再单独维护项目阶段状态。

This directory validates the current rules in
`E:\fish-oasis\gdd\05-核心随机算法.md` independently from the economy model.

The 2026-07-20 historical handoff is preserved in [HANDOFF.md](HANDOFF.md), and
the detailed architecture background remains in
[FISH_ECONOMY_SIMULATOR_PLAN.md](FISH_ECONOMY_SIMULATOR_PLAN.md).

The player-save foundation is implemented in `igess.fish_state`. Its mapping to
the production Lua archive schema and checkpoint boundary is documented in
[PLAYER_STATE_MODEL.md](PLAYER_STATE_MODEL.md).

`gdd-example.json` intentionally uses the seven-fish example pool and the
six-tier trash pool from the GDD. It is not the production fish table. The
authoritative production snapshot is `E:\fish-oasis\igess_export`; its
`json\tbfish.json` now exports the `Denominator` field, while this example
remains a mechanism-only fixture.

The Probe now repeats the same authoritative `resolve_throw()` used by the Fish
domain. FishLuck is interpolated directly from strength and
`tbfishrandompool`: each row's `strengthUpperBound` is the inclusive endpoint
of that region, not its start. Row 1 covers `[1, R1]`; every later row covers
`(R(n-1), Rn]`. The torpedo trajectory is reverse-derived presentation and is
not an input to economy settlement.

Run:

```powershell
.\.venv\Scripts\python.exe -m igess.cli fish-rng-run `
  --config projects\fish-rng\gdd-example.json `
  --out projects\fish-rng\runs\gdd-example
```
