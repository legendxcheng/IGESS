"""Observation-only reports for source-executed Fish runs."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from typing import Any
from pathlib import Path

from .schema import SimulationResult
from .fish_source_tides import tide_report_rows


def write_source_progression_artifacts(
    result: SimulationResult, output_dir: Path, source_profiles: dict | None = None,
) -> tuple[str, str]:
    progression = {
        "schema_version": 1,
        "scenario_id": result.scenario_id,
        "source": "lua_session_observation",
        "unavailable_metrics": [],
        "generated_money_definition": "source_collected_slot_receipts_plus_current_unclaimed",
        "profiles": {},
    }
    profile_rows: dict[str, list[dict[str, str | int | None]]] = defaultdict(list)
    for row in result.timeline:
        resources = row.resources
        profile_rows[row.profile_id].append({
            "time_seconds": row.time_seconds,
            "spendable_money": resources["money"],
            "unclaimed_money": resources["unclaimed_money"],
            "collected_money": resources["collected_money"],
            "generated_money": resources["generated_money"],
            "material": resources["material"],
            **{field: resources.get(field) for field in (
                "online_money_acquired_cumulative", "online_resource_acquired_cumulative",
                "online_fish_sale_material_cumulative",
                "egg_inventory_count", "egg_hatched_count", "egg_capacity_blocked",
                "fish_inventory_count", "fish_inventory_capacity",
                "online_tide_reload_material_cumulative", "online_codex_money_cumulative", "online_codex_material_cumulative",
                "codex_unlocked_count", "codex_claimed_count",
            )},
            "strength": resources["strength"],
            "fish_luck": resources.get("fish_luck"),
            "trash_luck": resources.get("trash_luck"),
            "trash_realm": resources["trash_realm"],
            "treasure_beast_unlocked": resources.get("treasure_beast_unlocked"),
            "total_throws": resources["total_throws"],
            "strength_rebirth_count": resources["strength_rebirth_count"],
            "trash_man_rebirth_count": resources["trash_man_rebirth_count"],
            "deployed_fish": row.generators_owned["deployed_fish"],
        })
    progression["profiles"] = dict(sorted(profile_rows.items()))
    if any("fish_luck" not in row.resources for row in result.timeline):
        progression["unavailable_metrics"].extend(["fish_luck", "trash_luck"])
    (output_dir / "source_progression.json").write_text(
        json.dumps(progression, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n",
    )

    profile_events = defaultdict(list)
    for event in result.events:
        profile_events[event.profile_id].append({
            "kind": event.kind, "time_seconds": event.time_seconds, "details": event.details,
        })
    behavior = {
        "schema_version": 1,
        "scenario_id": result.scenario_id,
        "source": "lua_command_receipts",
        "profiles": {
            profile_id: project_source_behavior(
                profile_events[profile_id], (source_profiles or {}).get(profile_id, {}),
            )
            for profile_id in sorted(set(profile_events) | set(profile_rows))
        },
    }
    (output_dir / "source_behavior.json").write_text(
        json.dumps(behavior, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n",
    )
    return "source_progression.json", "source_behavior.json"


def project_source_behavior(
    events: Iterable[Mapping[str, Any]], scope: Mapping[str, Any],
) -> dict[str, Any]:
    """Project one profile's segment receipts and saved lifecycle observations."""
    accepted, rejected = Counter(), Counter()
    gun_milestones, egg_events, tide_rounds = [], [], {}
    for event in events:
        kind, details = event["kind"], event.get("details", {})
        if kind == "tide_observed":
            row = json.loads(details["receipt"])
            tide_rounds[row["roundId"]] = row
        elif kind in {"egg_admitted", "egg_hatched"}:
            egg_events.append({"time_seconds": event["time_seconds"], "kind": kind, **details})
        elif kind == "gun_milestone":
            gun_milestones.append({"time_seconds": event["time_seconds"], **details})
        elif kind == "source_rejected":
            rejected[details.get("code", "unknown")] += 1
        elif kind != "treasure_beast_unlocked" and details.get("source") != "observation":
            accepted[kind] += 1
    return {
        "collection_growth": scope.get("collection_growth"),
        "first_times": scope.get("first_times", {}),
        "lifecycle_gun_milestones": scope.get("lifecycle_gun_milestones", []),
        "gun_milestones": gun_milestones,
        "egg_events": egg_events,
        "tide_rounds": tide_report_rows(tide_rounds.values(), egg_events),
        "accepted_commands": dict(sorted(accepted.items())),
        "rejected_commands": dict(sorted(rejected.items())),
    }
