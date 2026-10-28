"""Collection identities projected from saved source facts, never inventory guesses."""
from __future__ import annotations

from typing import Any
from collections.abc import Iterator
from itertools import groupby


# The source collection / fishing contract uses mutation 1 for ordinary fish.
NORMAL_MUTATION_ID = 1
GUN_GROWTH_KINDS = {"normal_codex_completed", "gun_owned", "gun_upgraded", "fish_tide_unlocked"}


def ordered_observations(events: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    """Only legacy consecutive observations without batch metadata lack ordering."""
    def batch_key(event: dict[str, Any]) -> tuple[bool, int]:
        legacy = event["kind"] == "codex_fish_unlocked" and "observation_batch_size" not in event["details"]
        return legacy, event["time_seconds"]

    for (legacy, _), group in groupby(events, key=batch_key):
        batch = list(group)
        if legacy:
            batch.sort(key=lambda event: (int(event["receipt"]["fishId"]), int(event["receipt"]["mutationId"])))
        for event in batch:
            if event["kind"] == "codex_fish_unlocked":
                size = int(event["details"].get("observation_batch_size", len(batch)))
                event = {**event, "same_observation_batch": size > 1}
            yield event


class CollectionGrowth:
    def __init__(self, scope: dict[str, Any], *, full_history: bool,
                 has_collection_records: bool) -> None:
        baseline = scope.get("collection_growth", {})
        known = baseline.get("version") == 1
        entries = baseline.get("initial_unlocked_entries", [])
        self.species = {int(entry["fishId"]) for entry in entries}
        self.combinations = {f"{entry['fishId']}:{entry['mutationId']}" for entry in entries}
        self.gun_facts = set(baseline.get("initial_gun_facts", []))
        self.names = baseline.get("display_names", {})
        self.first_species_complete = known or (full_history and has_collection_records)
        self.coverage = {
            "first_species_complete": self.first_species_complete,
            "note": ("收集成长按历史解锁去重；双标签只计一次成长事件。"
                     if self.first_species_complete else
                     "起始解锁历史或收集事件未记录，新鱼种首次覆盖不完整；仅展示可证明的成长，缺失不等于零。"),
        }

    def project(self, event: dict[str, Any]) -> dict[str, Any] | None:
        if event["kind"] == "gun_milestone":
            details = event["details"]
            kind, identity = details["kind"], details["identity"]
            if kind not in GUN_GROWTH_KINDS or identity in self.gun_facts:
                return None
            self.gun_facts.add(identity)
            target = identity.split(":", 1)[1]
            return {"event_identity": identity, "item_id": identity,
                    "progression_categories": [kind], "progression_category": kind,
                    **({"gun_id": int(target), "display_name": self.names.get("gun", {}).get(target, "")}
                       if kind == "gun_owned" else {}),
                    **({"reward_id": int(target)} if kind == "normal_codex_completed" else {}),
                    "metric_id": kind}
        if event["kind"] != "codex_fish_unlocked":
            return None
        receipt = event["receipt"]
        fish, mutation = int(receipt["fishId"]), int(receipt["mutationId"])
        combination = f"{fish}:{mutation}"
        if combination in self.combinations:
            return None
        categories = []
        if self.first_species_complete and fish not in self.species:
            categories.append("new_fish_species")
        if mutation != NORMAL_MUTATION_ID:
            categories.append("new_fish_variant")
        self.species.add(fish)
        self.combinations.add(combination)
        if not categories:
            return None
        return {"event_identity": f"fish_collection:{combination}",
                "item_id": f"fish_collection:{combination}",
                "fish_id": fish, "mutation_id": mutation,
                "display_name": " · ".join(filter(None, (
                    self.names.get("fish", {}).get(str(fish)), self.names.get("mutation", {}).get(str(mutation))))),
                "same_observation_batch": event.get("same_observation_batch", False),
                "progression_categories": categories, "progression_category": categories[0],
                "metric_id": "collection_unlocked"}
