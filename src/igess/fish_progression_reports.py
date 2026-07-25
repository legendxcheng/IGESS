from __future__ import annotations

import csv
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .fish_core_progression import (
    DEFAULT_ACTIVE_SAMPLE_SECONDS,
    build_core_strength_progression,
)
from .fish_data import FishDataSnapshot
from .fish_persistent_progression import build_persistent_progression
from .schema import EconomyModel, SimulationResult


CORE_STRENGTH_ARTIFACTS = (
    "luck_progression.csv",
    "luck_progression.json",
)
PERSISTENT_PROGRESSION_ARTIFACTS = (
    "behavior_progression.csv",
    "behavior_progression.json",
)
FISH_PROGRESSION_ARTIFACTS = (
    *PERSISTENT_PROGRESSION_ARTIFACTS,
    *CORE_STRENGTH_ARTIFACTS,
)

_CORE_CSV_FIELDS = (
    "scenario_id",
    "profile_id",
    "wall_time_seconds",
    "active_time_seconds",
    "sample_kind",
    "strength_current",
    "strength_peak",
    "strength_delta",
    "fish_luck_current",
    "fish_luck_peak",
    "fish_luck_delta",
    "trash_luck_current",
    "trash_luck_peak",
    "trash_luck_delta",
    "fish_luck_delta_per_active_hour",
    "trash_luck_delta_per_active_hour",
    "time_since_fish_luck_growth_seconds",
    "time_since_trash_luck_growth_seconds",
    "strength_rebirth_count",
    "trash_man_rebirth_count",
    "reset_or_milestone_marker",
)
_BEHAVIOR_CSV_FIELDS = (
    "scenario_id",
    "profile_id",
    "wall_time_seconds",
    "active_time_seconds",
    "stage_id",
    "source_event_kind",
    "progression_category",
    "item_id",
    "is_persistent",
    "metric_id",
    "metric_before",
    "metric_after",
    "metric_delta",
    "relative_delta",
    "gap_from_previous_progression_seconds",
)


def write_fish_progression_artifacts(
    result: SimulationResult,
    model: EconomyModel,
    data: FishDataSnapshot,
    output_dir: str | Path,
    *,
    sample_interval_active_seconds: int = DEFAULT_ACTIVE_SAMPLE_SECONDS,
) -> tuple[str, ...]:
    if model.config.engine_id != "fish":
        return ()
    if not isinstance(data, FishDataSnapshot):
        raise TypeError(
            "Fish progression reports require a FishDataSnapshot"
        )
    if (
        type(sample_interval_active_seconds) is not int
        or sample_interval_active_seconds <= 0
    ):
        raise ValueError("sample interval must be a positive integer")

    output_dir = Path(output_dir)
    core = build_core_strength_progression(
        result,
        model,
        data,
        sample_interval_active_seconds=sample_interval_active_seconds,
    )
    behavior = build_persistent_progression(result, model)
    _write_json(output_dir / "luck_progression.json", core)
    _write_csv(
        output_dir / "luck_progression.csv",
        _flatten_profile_rows(core),
        _CORE_CSV_FIELDS,
    )
    _write_json(output_dir / "behavior_progression.json", behavior)
    _write_csv(
        output_dir / "behavior_progression.csv",
        _flatten_profile_rows(behavior),
        _BEHAVIOR_CSV_FIELDS,
    )
    return FISH_PROGRESSION_ARTIFACTS


def _flatten_profile_rows(
    payload: Mapping[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for profile_id in sorted(payload.get("profiles", {})):
        rows.extend(payload["profiles"][profile_id].get("rows", []))
    return rows


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_csv(
    path: Path,
    rows: list[dict[str, Any]],
    fieldnames: tuple[str, ...],
) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)
