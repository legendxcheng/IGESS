"""Observation-only reports for source-executed Fish runs."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from .schema import SimulationResult


def write_source_progression_artifacts(
    result: SimulationResult, output_dir: Path,
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
            "strength": resources["strength"],
            "fish_luck": resources.get("fish_luck"),
            "trash_luck": resources.get("trash_luck"),
            "trash_realm": resources["trash_realm"],
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

    counts: dict[str, Counter[str]] = defaultdict(Counter)
    rejections: dict[str, Counter[str]] = defaultdict(Counter)
    for event in result.events:
        if event.kind == "source_rejected":
            rejections[event.profile_id][event.details["code"]] += 1
        else:
            counts[event.profile_id][event.kind] += 1
    behavior = {
        "schema_version": 1,
        "scenario_id": result.scenario_id,
        "source": "lua_command_receipts",
        "profiles": {
            profile_id: {
                "accepted_commands": dict(sorted(counts[profile_id].items())),
                "rejected_commands": dict(sorted(rejections[profile_id].items())),
            }
            for profile_id in sorted(set(counts) | set(rejections) | set(profile_rows))
        },
    }
    (output_dir / "source_behavior.json").write_text(
        json.dumps(behavior, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n",
    )
    return "source_progression.json", "source_behavior.json"
