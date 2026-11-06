"""Report-only strength milestones against the run's frozen FishRandomPool table."""
from __future__ import annotations

import json
from typing import Any

from .fish_source_numbers import source_decimal
from .schema import Event


class PoolMilestones:
    def __init__(self, pools: list[dict[str, Any]], state: dict[str, Any],
                 saved: dict[str, Any] | None = None) -> None:
        # Lua QueryLuck owns pool selection. Python only labels its observed ID.
        self.pools = pools
        self.seen = set(saved["seen_pool_ids"]) if saved else set()
        current = (state.get("luck") or {}).get("fishPoolId", 1)
        self.seen.update(row["pool_id"] for row in pools
                         if current >= row["pool_id"])
        self.last_strength = state["wallet"]["strength"]
        self.scope = {"version": 1, "initial_seen_pool_ids": sorted(self.seen),
                      "pools": pools, "time_basis": "source_observation"}

    def observe(self, state: dict[str, Any], active: int, scenario: str,
                profile: str, events: list[Event]) -> None:
        if state["wallet"]["strength"] == self.last_strength:
            return
        self.last_strength = state["wallet"]["strength"]
        current = (state.get("luck") or {}).get("fishPoolId", 1)
        strength = source_decimal(state["wallet"]["strength"])
        for pool in self.pools:
            if pool["pool_id"] in self.seen or pool["pool_id"] > current:
                continue
            self.seen.add(pool["pool_id"])
            events.append(Event(scenario, profile, int(state["time"]),
                                "fish_pool_entered", str(pool["pool_id"]), {
                                    "source": "observation",
                                    "receipt": json.dumps({**pool, "strength": str(strength),
                                                           "active_time_seconds": active}, ensure_ascii=False),
                                }))

    def save(self) -> dict[str, Any]:
        return {"seen_pool_ids": sorted(self.seen)}
