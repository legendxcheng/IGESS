from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from .fish_state import PlayerState
from .numbers import SimNumber


_RUNTIME_VERSION = 1


@dataclass(frozen=True)
class TrashRule:
    trash_id: int
    base_decompose_seconds: int
    base_material_per_second: SimNumber


@dataclass(frozen=True)
class TrashManRealmRule:
    realm_id: int
    decompose_speed_multiplier: SimNumber
    progression_seconds_to_next_realm: int
    material_required_to_next_realm: SimNumber


@dataclass(frozen=True)
class TrashManRebirthRule:
    completed_count: int
    realm_requirement: int
    fish_hall_output_multiplier: SimNumber


@dataclass(frozen=True)
class TrashManRealmTransition:
    from_realm_id: int
    to_realm_id: int
    at_elapsed_seconds: int

    def to_dict(self) -> dict[str, int]:
        return {
            "from_realm_id": self.from_realm_id,
            "to_realm_id": self.to_realm_id,
            "at_elapsed_seconds": self.at_elapsed_seconds,
        }


@dataclass(frozen=True)
class TrashManBreakthroughCompletion:
    from_realm_id: int
    to_realm_id: int
    at_elapsed_seconds: int
    required_seconds: int
    material_cost: SimNumber

    def to_dict(self) -> dict[str, int | str]:
        return {
            "from_realm_id": self.from_realm_id,
            "to_realm_id": self.to_realm_id,
            "at_elapsed_seconds": self.at_elapsed_seconds,
            "required_seconds": self.required_seconds,
            "material_cost": self.material_cost.to_decimal_string(),
        }


@dataclass(frozen=True)
class TrashProcessingRuntime:
    """Simulation-only fractional base-work progress.

    The production archive keeps the whole number of effective base seconds in
    ``activeProgressSeconds``. This remainder makes quarter-step realm speeds
    exactly replayable without changing the production PlayerState schema.
    """

    progress_remainder: SimNumber = SimNumber.zero()

    def __post_init__(self) -> None:
        remainder = SimNumber.parse(self.progress_remainder)
        if remainder < SimNumber.zero() or remainder >= SimNumber.one():
            raise ValueError("trash progress remainder must be within [0, 1)")
        object.__setattr__(self, "progress_remainder", remainder)

    def to_dict(self) -> dict[str, int | str]:
        return {
            "version": _RUNTIME_VERSION,
            "progress_remainder": self.progress_remainder.to_decimal_string(),
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> "TrashProcessingRuntime":
        if not isinstance(payload, Mapping):
            raise TypeError("trash processing runtime must be a mapping")
        if set(payload) != {"version", "progress_remainder"}:
            raise ValueError("trash processing runtime has invalid fields")
        if payload["version"] != _RUNTIME_VERSION:
            raise ValueError("trash processing runtime version is unsupported")
        return cls(progress_remainder=SimNumber.parse(payload["progress_remainder"]))


@dataclass(frozen=True)
class TrashProcessingSettlement:
    processing: TrashProcessingState
    runtime: TrashProcessingRuntime
    elapsed_seconds: int
    realm_id: int
    decompose_speed_multiplier: SimNumber
    processing_efficiency: SimNumber
    strength_rebirth_completed_count: int
    strength_rebirth_material_multiplier: SimNumber
    work_consumed: SimNumber
    unused_work: SimNumber
    material_added: SimNumber
    completed_by_trash: tuple[tuple[int, int], ...]
    stock_count_before: int
    stock_count_after: int

    @property
    def completed_count(self) -> int:
        return sum(count for _trash_id, count in self.completed_by_trash)

    def event_details(self) -> dict[str, str]:
        completed = {
            str(trash_id): count for trash_id, count in self.completed_by_trash
        }
        return {
            "trash_processing_formula": (
                "work=elapsed_seconds*decompose_speed_multiplier"
                "*processing_efficiency;"
                "material=base_material_per_second*work_consumed"
                "*strength_rebirth_material_output_multiplier"
            ),
            "trash_processing_queue_policy": "trash_id_ascending",
            "trash_processing_elapsed_seconds": str(self.elapsed_seconds),
            "trash_processing_realm_id": str(self.realm_id),
            "trash_decompose_speed_multiplier": (
                self.decompose_speed_multiplier.to_decimal_string()
            ),
            "trash_processing_efficiency": (
                self.processing_efficiency.to_decimal_string()
            ),
            "strength_rebirth_completed_count": str(
                self.strength_rebirth_completed_count
            ),
            "strength_rebirth_material_multiplier": (
                self.strength_rebirth_material_multiplier.to_decimal_string()
            ),
            "strength_rebirth_material_multiplier_source": (
                "default_1x_not_in_table"
                if self.strength_rebirth_completed_count == 0
                else (
                    "tbstrengthrebirth"
                    f"[id={self.strength_rebirth_completed_count}]"
                    ".materialOutputMultiplier"
                )
            ),
            "trash_processing_work_consumed": (self.work_consumed.to_decimal_string()),
            "trash_processing_unused_work": (self.unused_work.to_decimal_string()),
            "trash_material_added": self.material_added.to_decimal_string(),
            "trash_completed_count": str(self.completed_count),
            "trash_completed_by_id": json.dumps(
                completed,
                sort_keys=True,
                separators=(",", ":"),
            ),
            "trash_stock_count_before": str(self.stock_count_before),
            "trash_stock_count_after": str(self.stock_count_after),
            "trash_active_id_after": str(self.processing.active_trash_id),
            "trash_active_progress_seconds_after": str(
                self.processing.active_progress_seconds
            ),
            "trash_active_progress_remainder_after": (
                self.runtime.progress_remainder.to_decimal_string()
            ),
        }


@dataclass(frozen=True)
class TrashOnlineSettlement:
    processing: TrashProcessingState
    runtime: TrashProcessingRuntime
    elapsed_seconds: int
    cultivation_elapsed_seconds: int
    settlement_mode: str
    realm_id_before: int
    realm_id_after: int
    highest_realm_id: int
    training_progress_seconds_before: int
    training_progress_seconds_after: int
    paused_by_breakthrough: bool
    breakthrough_active_after: bool
    breakthrough_target_realm_id_after: int
    breakthrough_progress_seconds_before: int
    breakthrough_progress_seconds_after: int
    segments: tuple[TrashProcessingSettlement, ...]
    transitions: tuple[TrashManRealmTransition, ...]
    breakthrough_completions: tuple[TrashManBreakthroughCompletion, ...]

    @property
    def completed_by_trash(self) -> tuple[tuple[int, int], ...]:
        completed: dict[int, int] = {}
        for segment in self.segments:
            for trash_id, count in segment.completed_by_trash:
                completed[trash_id] = completed.get(trash_id, 0) + count
        return tuple(sorted(completed.items()))

    @property
    def completed_count(self) -> int:
        return sum(count for _trash_id, count in self.completed_by_trash)

    @property
    def material_added(self) -> SimNumber:
        return sum(
            (segment.material_added for segment in self.segments),
            SimNumber.zero(),
        )

    @property
    def work_consumed(self) -> SimNumber:
        return sum(
            (segment.work_consumed for segment in self.segments),
            SimNumber.zero(),
        )

    @property
    def unused_work(self) -> SimNumber:
        return sum(
            (segment.unused_work for segment in self.segments),
            SimNumber.zero(),
        )

    @property
    def stock_count_before(self) -> int:
        return self.segments[0].stock_count_before

    @property
    def stock_count_after(self) -> int:
        return self.segments[-1].stock_count_after

    def event_details(self) -> dict[str, str]:
        first_segment = self.segments[0]
        completed = {
            str(trash_id): count for trash_id, count in self.completed_by_trash
        }
        segment_trace = [
            {
                "realm_id": segment.realm_id,
                "elapsed_seconds": segment.elapsed_seconds,
                "decompose_speed_multiplier": (
                    segment.decompose_speed_multiplier.to_decimal_string()
                ),
                "processing_efficiency": (
                    segment.processing_efficiency.to_decimal_string()
                ),
                "work_consumed": segment.work_consumed.to_decimal_string(),
                "unused_work": segment.unused_work.to_decimal_string(),
                "material_added": segment.material_added.to_decimal_string(),
            }
            for segment in self.segments
        ]
        return {
            "trash_processing_formula": (
                "work=elapsed_seconds*decompose_speed_multiplier"
                "*processing_efficiency;"
                "material=base_material_per_second*work_consumed"
                "*strength_rebirth_material_output_multiplier"
            ),
            "trash_processing_mode": self.settlement_mode,
            "trash_processing_queue_policy": "trash_id_ascending",
            "trash_processing_elapsed_seconds": str(self.elapsed_seconds),
            "trash_processing_realm_id": str(first_segment.realm_id),
            "trash_decompose_speed_multiplier": (
                first_segment.decompose_speed_multiplier.to_decimal_string()
            ),
            "trash_processing_efficiency": (
                first_segment.processing_efficiency.to_decimal_string()
            ),
            "strength_rebirth_completed_count": str(
                first_segment.strength_rebirth_completed_count
            ),
            "strength_rebirth_material_multiplier": (
                first_segment.strength_rebirth_material_multiplier
                .to_decimal_string()
            ),
            "strength_rebirth_material_multiplier_source": (
                "default_1x_not_in_table"
                if first_segment.strength_rebirth_completed_count == 0
                else (
                    "tbstrengthrebirth"
                    f"[id={first_segment.strength_rebirth_completed_count}]"
                    ".materialOutputMultiplier"
                )
            ),
            "trash_processing_work_consumed": (self.work_consumed.to_decimal_string()),
            "trash_processing_unused_work": (self.unused_work.to_decimal_string()),
            "trash_material_added": self.material_added.to_decimal_string(),
            "trash_completed_count": str(self.completed_count),
            "trash_completed_by_id": json.dumps(
                completed,
                sort_keys=True,
                separators=(",", ":"),
            ),
            "trash_stock_count_before": str(self.stock_count_before),
            "trash_stock_count_after": str(self.stock_count_after),
            "trash_active_id_after": str(self.processing.active_trash_id),
            "trash_active_progress_seconds_after": str(
                self.processing.active_progress_seconds
            ),
            "trash_active_progress_remainder_after": (
                self.runtime.progress_remainder.to_decimal_string()
            ),
            "trash_processing_realm_segments": json.dumps(
                segment_trace,
                sort_keys=True,
                separators=(",", ":"),
            ),
            "trash_man_cultivation_formula": (
                "online_elapsed advances free historical catch-up or an "
                "already-funded breakthrough; each completed current-row "
                "breakthroughSecondsToNextRealm advances one configured realm"
            ),
            "trash_man_cultivation_online_only": "true",
            "trash_man_cultivation_ceiling": "historical_highest_realm",
            "trash_man_breakthrough_policy": (
                "material_paid_once_then_online_current_row_duration"
            ),
            "trash_man_cultivation_elapsed_seconds": str(
                self.cultivation_elapsed_seconds
            ),
            "trash_man_realm_id_before": str(self.realm_id_before),
            "trash_man_realm_id_after": str(self.realm_id_after),
            "trash_man_highest_realm_id": str(self.highest_realm_id),
            "trash_man_training_progress_seconds_before": str(
                self.training_progress_seconds_before
            ),
            "trash_man_training_progress_seconds_after": str(
                self.training_progress_seconds_after
            ),
            "trash_man_cultivation_paused_by_breakthrough": str(
                self.paused_by_breakthrough
            ).lower(),
            "trash_man_breakthrough_active_after": str(
                self.breakthrough_active_after
            ).lower(),
            "trash_man_breakthrough_target_realm_id_after": str(
                self.breakthrough_target_realm_id_after
            ),
            "trash_man_breakthrough_progress_seconds_before": str(
                self.breakthrough_progress_seconds_before
            ),
            "trash_man_breakthrough_progress_seconds_after": str(
                self.breakthrough_progress_seconds_after
            ),
            "trash_man_breakthrough_completion_count": str(
                len(self.breakthrough_completions)
            ),
            "trash_man_breakthrough_completions": json.dumps(
                [
                    completion.to_dict()
                    for completion in self.breakthrough_completions
                ],
                sort_keys=True,
                separators=(",", ":"),
            ),
            "trash_man_realm_advance_count": str(len(self.transitions)),
            "trash_man_realm_transitions": json.dumps(
                [transition.to_dict() for transition in self.transitions],
                sort_keys=True,
                separators=(",", ":"),
            ),
        }
