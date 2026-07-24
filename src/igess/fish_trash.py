from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from .fish_data import FishDataError, FishDataSnapshot
from .fish_state import PlayerState, TrashProcessingState, TrashStock
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
    cultivation_seconds_to_next_realm: int


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
    material_output_multiplier: SimNumber
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
                "work=elapsed_seconds*decompose_speed_multiplier;"
                "material=base_material_per_second*work_consumed"
                "*trash_to_treasure_output_multiplier"
            ),
            "trash_processing_queue_policy": "trash_id_ascending",
            "trash_processing_elapsed_seconds": str(self.elapsed_seconds),
            "trash_processing_realm_id": str(self.realm_id),
            "trash_decompose_speed_multiplier": (
                self.decompose_speed_multiplier.to_decimal_string()
            ),
            "trash_material_output_multiplier": (
                self.material_output_multiplier.to_decimal_string()
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
    realm_id_before: int
    realm_id_after: int
    highest_realm_id: int
    training_progress_seconds_before: int
    training_progress_seconds_after: int
    paused_by_breakthrough: bool
    segments: tuple[TrashProcessingSettlement, ...]
    transitions: tuple[TrashManRealmTransition, ...]

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
                "work_consumed": segment.work_consumed.to_decimal_string(),
                "unused_work": segment.unused_work.to_decimal_string(),
                "material_added": segment.material_added.to_decimal_string(),
            }
            for segment in self.segments
        ]
        return {
            "trash_processing_formula": (
                "work=elapsed_seconds*decompose_speed_multiplier;"
                "material=base_material_per_second*work_consumed"
                "*trash_to_treasure_output_multiplier"
            ),
            "trash_processing_queue_policy": "trash_id_ascending",
            "trash_processing_elapsed_seconds": str(self.elapsed_seconds),
            "trash_processing_realm_id": str(first_segment.realm_id),
            "trash_decompose_speed_multiplier": (
                first_segment.decompose_speed_multiplier.to_decimal_string()
            ),
            "trash_material_output_multiplier": (
                first_segment.material_output_multiplier.to_decimal_string()
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
                "online_elapsed advances current realm cultivation until "
                "historical_highest_realm; each completed current-row "
                "cultivationSecondsToNextRealm advances one configured realm"
            ),
            "trash_man_cultivation_online_only": "true",
            "trash_man_cultivation_ceiling": "historical_highest_realm",
            "trash_man_cultivation_elapsed_seconds": str(self.elapsed_seconds),
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
            "trash_man_realm_advance_count": str(len(self.transitions)),
            "trash_man_realm_transitions": json.dumps(
                [transition.to_dict() for transition in self.transitions],
                sort_keys=True,
                separators=(",", ":"),
            ),
        }


class FishTrashDataAdapter:
    """Authoritative Trash/TrashMan tables and analytical queue settlement."""

    def __init__(self, snapshot: FishDataSnapshot) -> None:
        self.data = snapshot
        self._trash = self._trash_rows()
        self._realms, self._realm_order = self._realm_rows()
        self._realm_indexes = {
            realm_id: index for index, realm_id in enumerate(self._realm_order)
        }
        self.initial_realm_id = self._realm_order[0]
        self._rebirth_output = self._rebirth_rows()

    def trash_rule(self, trash_id: int) -> TrashRule:
        try:
            return self._trash[trash_id]
        except KeyError as exc:
            raise FishDataError(f"unknown production trash id: {trash_id}") from exc

    def initialize_realm(self, state: PlayerState) -> PlayerState:
        """Explicitly migrate the pre-Phase-5 ``realmId=0`` new-player state."""

        if not isinstance(state, PlayerState):
            raise TypeError("state must be a PlayerState")
        if state.trash_man.realm_id != 0 or state.trash_man.highest_realm_id != 0:
            return state
        migrated = state.copy()
        migrated.trash_man.realm_id = self.initial_realm_id
        migrated.trash_man.highest_realm_id = self.initial_realm_id
        return migrated

    def realm_speed(self, realm_id: int) -> SimNumber:
        try:
            return self._realms[realm_id].decompose_speed_multiplier
        except KeyError as exc:
            raise FishDataError(
                f"unknown production trash-man realm id: {realm_id}"
            ) from exc

    def cultivation_seconds_to_next_realm(self, realm_id: int) -> int:
        try:
            return self._realms[realm_id].cultivation_seconds_to_next_realm
        except KeyError as exc:
            raise FishDataError(
                f"unknown production trash-man realm id: {realm_id}"
            ) from exc

    def next_realm_id(self, realm_id: int) -> int | None:
        try:
            index = self._realm_indexes[realm_id]
        except KeyError as exc:
            raise FishDataError(
                f"unknown production trash-man realm id: {realm_id}"
            ) from exc
        if index + 1 >= len(self._realm_order):
            return None
        return self._realm_order[index + 1]

    def material_output_multiplier(
        self,
        completed_rebirth_count: int,
    ) -> SimNumber:
        if type(completed_rebirth_count) is not int or completed_rebirth_count < 0:
            raise FishDataError(
                "trash-man completed rebirth count must be non-negative"
            )
        if completed_rebirth_count == 0:
            return SimNumber.one()
        row_id = completed_rebirth_count - 1
        try:
            return self._rebirth_output[row_id]
        except KeyError as exc:
            raise FishDataError(
                "trash-man completed rebirth count exceeds production data: "
                f"{completed_rebirth_count}"
            ) from exc

    def settle(
        self,
        state: PlayerState,
        elapsed_seconds: int,
        *,
        runtime: TrashProcessingRuntime | None = None,
    ) -> TrashProcessingSettlement:
        if not isinstance(state, PlayerState):
            raise TypeError("state must be a PlayerState")
        if type(elapsed_seconds) is not int or elapsed_seconds < 0:
            raise ValueError("elapsed_seconds must be non-negative")
        runtime = runtime or TrashProcessingRuntime()
        if not isinstance(runtime, TrashProcessingRuntime):
            raise TypeError("runtime must be a TrashProcessingRuntime")

        processing = state.trash_man.processing
        stocks = {stock.trash_id: stock.count for stock in processing.stocks}
        stock_before = sum(stocks.values())
        active_id = processing.active_trash_id
        progress = processing.active_progress_seconds
        remainder = runtime.progress_remainder
        if active_id == 0:
            if progress != 0 or not remainder.is_zero():
                raise FishDataError("inactive trash processing must have zero progress")
        elif active_id not in stocks:
            raise FishDataError("active trash processing target is missing from stocks")

        realm_id = state.trash_man.realm_id
        speed = self.realm_speed(realm_id)
        output_multiplier = self.material_output_multiplier(
            state.rebirth.trash_man_completed_count
        )
        available_work = SimNumber.parse(elapsed_seconds) * speed
        work_consumed = SimNumber.zero()
        material_added = SimNumber.zero()
        completed: dict[int, int] = {}

        def consume_work(trash_id: int, amount: SimNumber) -> None:
            nonlocal work_consumed, material_added
            rule = self.trash_rule(trash_id)
            work_consumed += amount
            material_added += rule.base_material_per_second * amount * output_multiplier

        if active_id != 0 and available_work > SimNumber.zero():
            rule = self.trash_rule(active_id)
            if progress >= rule.base_decompose_seconds:
                raise FishDataError(
                    "active trash progress must be below its base duration"
                )
            remaining = (
                SimNumber.parse(rule.base_decompose_seconds - progress) - remainder
            )
            if available_work < remaining:
                consume_work(active_id, available_work)
                total_progress = SimNumber.parse(progress) + remainder + available_work
                progress = int(total_progress.floor().decimal)
                remainder = total_progress - SimNumber.parse(progress)
                available_work = SimNumber.zero()
            else:
                consume_work(active_id, remaining)
                available_work -= remaining
                stocks[active_id] -= 1
                completed[active_id] = completed.get(active_id, 0) + 1
                if stocks[active_id] == 0:
                    del stocks[active_id]
                active_id = 0
                progress = 0
                remainder = SimNumber.zero()

        while available_work > SimNumber.zero() and stocks:
            active_id = min(stocks)
            rule = self.trash_rule(active_id)
            duration = SimNumber.parse(rule.base_decompose_seconds)
            full_possible = int((available_work / duration).floor().decimal)
            full_count = min(stocks[active_id], full_possible)
            if full_count > 0:
                bulk_work = duration * SimNumber.parse(full_count)
                consume_work(active_id, bulk_work)
                available_work -= bulk_work
                stocks[active_id] -= full_count
                completed[active_id] = completed.get(active_id, 0) + full_count
                if stocks[active_id] == 0:
                    del stocks[active_id]
                    active_id = 0
                if not stocks:
                    break
                if active_id == 0:
                    continue

            if available_work > SimNumber.zero():
                partial = min(available_work, duration)
                consume_work(active_id, partial)
                available_work -= partial
                progress = int(partial.floor().decimal)
                remainder = partial - SimNumber.parse(progress)
                if partial == duration:
                    stocks[active_id] -= 1
                    completed[active_id] = completed.get(active_id, 0) + 1
                    if stocks[active_id] == 0:
                        del stocks[active_id]
                    active_id = 0
                    progress = 0
                    remainder = SimNumber.zero()

        if not stocks:
            active_id = 0
            progress = 0
            remainder = SimNumber.zero()
        elif active_id == 0:
            active_id = min(stocks)

        next_processing = TrashProcessingState(
            active_trash_id=active_id,
            active_progress_seconds=progress,
            stocks=[
                TrashStock(trash_id=trash_id, count=count)
                for trash_id, count in sorted(stocks.items())
            ],
        )
        return TrashProcessingSettlement(
            processing=next_processing,
            runtime=TrashProcessingRuntime(remainder),
            elapsed_seconds=elapsed_seconds,
            realm_id=realm_id,
            decompose_speed_multiplier=speed,
            material_output_multiplier=output_multiplier,
            work_consumed=work_consumed,
            unused_work=available_work,
            material_added=material_added,
            completed_by_trash=tuple(sorted(completed.items())),
            stock_count_before=stock_before,
            stock_count_after=sum(stocks.values()),
        )

    def settle_online(
        self,
        state: PlayerState,
        elapsed_seconds: int,
        *,
        runtime: TrashProcessingRuntime | None = None,
    ) -> TrashOnlineSettlement:
        """Settle trash processing while replaying confirmed online catch-up.

        Cultivation is deliberately capped at ``highestRealmId``. Progress
        beyond the historical maximum, bottlenecks, paid breakthroughs, and
        offline cultivation remain outside this confirmed rule slice.
        """

        if not isinstance(state, PlayerState):
            raise TypeError("state must be a PlayerState")
        if type(elapsed_seconds) is not int or elapsed_seconds < 0:
            raise ValueError("elapsed_seconds must be non-negative")
        runtime = runtime or TrashProcessingRuntime()
        if not isinstance(runtime, TrashProcessingRuntime):
            raise TypeError("runtime must be a TrashProcessingRuntime")

        realm_before = state.trash_man.realm_id
        highest_realm = state.trash_man.highest_realm_id
        progress_before = state.trash_man.training_progress_seconds
        try:
            realm_index = self._realm_indexes[realm_before]
            highest_index = self._realm_indexes[highest_realm]
        except KeyError as exc:
            raise FishDataError(
                "trash-man realm state references unknown production data"
            ) from exc
        if realm_index > highest_index:
            raise FishDataError(
                "trash-man current realm exceeds historical highest realm"
            )

        working = state.copy()
        current_realm = realm_before
        progress = progress_before
        remaining_elapsed = elapsed_seconds
        elapsed_offset = 0
        current_runtime = runtime
        segments: list[TrashProcessingSettlement] = []
        transitions: list[TrashManRealmTransition] = []
        paused = state.trash_man.breakthrough.active

        def process_segment(seconds: int) -> None:
            nonlocal current_runtime
            if seconds <= 0:
                return
            working.trash_man.realm_id = current_realm
            settlement = self.settle(
                working,
                seconds,
                runtime=current_runtime,
            )
            working.trash_man.processing = settlement.processing
            current_runtime = settlement.runtime
            segments.append(settlement)

        while remaining_elapsed > 0:
            if paused or current_realm == highest_realm:
                process_segment(remaining_elapsed)
                elapsed_offset += remaining_elapsed
                remaining_elapsed = 0
                break

            next_realm = self.next_realm_id(current_realm)
            if next_realm is None:
                raise FishDataError("trash-man historical highest realm is unreachable")
            requirement = self.cultivation_seconds_to_next_realm(current_realm)
            if progress > requirement:
                raise FishDataError(
                    "trash-man training progress exceeds current realm "
                    "cultivation requirement"
                )
            required_elapsed = requirement - progress
            if required_elapsed > remaining_elapsed:
                process_segment(remaining_elapsed)
                progress += remaining_elapsed
                elapsed_offset += remaining_elapsed
                remaining_elapsed = 0
                break

            process_segment(required_elapsed)
            remaining_elapsed -= required_elapsed
            elapsed_offset += required_elapsed
            transitions.append(
                TrashManRealmTransition(
                    from_realm_id=current_realm,
                    to_realm_id=next_realm,
                    at_elapsed_seconds=elapsed_offset,
                )
            )
            current_realm = next_realm
            progress = 0

        if not segments:
            segments.append(
                self.settle(
                    working,
                    0,
                    runtime=current_runtime,
                )
            )
            current_runtime = segments[-1].runtime

        return TrashOnlineSettlement(
            processing=segments[-1].processing,
            runtime=current_runtime,
            elapsed_seconds=elapsed_seconds,
            realm_id_before=realm_before,
            realm_id_after=current_realm,
            highest_realm_id=highest_realm,
            training_progress_seconds_before=progress_before,
            training_progress_seconds_after=progress,
            paused_by_breakthrough=paused,
            segments=tuple(segments),
            transitions=tuple(transitions),
        )

    def _trash_rows(self) -> dict[int, TrashRule]:
        result: dict[int, TrashRule] = {}
        for row in self.data.table("tbtrash"):
            row_id = _positive_int(_field(row, "id", "tbtrash"), "tbtrash.id")
            if row_id in result:
                raise FishDataError(f"tbtrash contains duplicate id: {row_id}")
            result[row_id] = TrashRule(
                trash_id=row_id,
                base_decompose_seconds=_positive_int(
                    _field(row, "baseDecomposeSeconds", "tbtrash"),
                    f"tbtrash.{row_id}.baseDecomposeSeconds",
                ),
                base_material_per_second=_positive_sim_number(
                    _field(row, "baseMaterialPerSecond", "tbtrash"),
                    f"tbtrash.{row_id}.baseMaterialPerSecond",
                ),
            )
        if not result:
            raise FishDataError("tbtrash must not be empty")
        return result

    def _realm_rows(
        self,
    ) -> tuple[dict[int, TrashManRealmRule], tuple[int, ...]]:
        result: dict[int, TrashManRealmRule] = {}
        for row in self.data.table("tbtrashmanrealm"):
            row_id = _positive_int(
                _field(row, "id", "tbtrashmanrealm"),
                "tbtrashmanrealm.id",
            )
            if row_id in result:
                raise FishDataError(f"tbtrashmanrealm contains duplicate id: {row_id}")
            result[row_id] = TrashManRealmRule(
                realm_id=row_id,
                decompose_speed_multiplier=_positive_sim_number(
                    _field(
                        row,
                        "decomposeSpeedMultiplier",
                        "tbtrashmanrealm",
                    ),
                    ("tbtrashmanrealm." f"{row_id}.decomposeSpeedMultiplier"),
                ),
                cultivation_seconds_to_next_realm=_nonnegative_int(
                    _field(
                        row,
                        "cultivationSecondsToNextRealm",
                        "tbtrashmanrealm",
                    ),
                    ("tbtrashmanrealm." f"{row_id}.cultivationSecondsToNextRealm"),
                ),
            )
        if not result:
            raise FishDataError("tbtrashmanrealm must not be empty")
        return result, tuple(sorted(result))

    def _rebirth_rows(self) -> dict[int, SimNumber]:
        result: dict[int, SimNumber] = {}
        for row in self.data.table("tbtrashmanrebirth"):
            row_id = _nonnegative_int(
                _field(row, "id", "tbtrashmanrebirth"),
                "tbtrashmanrebirth.id",
            )
            if row_id in result:
                raise FishDataError(
                    f"tbtrashmanrebirth contains duplicate id: {row_id}"
                )
            result[row_id] = _positive_sim_number(
                _field(
                    row,
                    "trashToTreasureOutputMultiplier",
                    "tbtrashmanrebirth",
                ),
                ("tbtrashmanrebirth." f"{row_id}.trashToTreasureOutputMultiplier"),
            )
        return result


def _field(row: Any, name: str, table_name: str) -> Any:
    try:
        return getattr(row, name)
    except AttributeError as exc:
        raise FishDataError(
            f"generated {table_name} row is missing field: {name}"
        ) from exc


def _positive_int(value: Any, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise FishDataError(f"{field} must be a positive integer")
    return value


def _nonnegative_int(value: Any, field: str) -> int:
    if type(value) is not int or value < 0:
        raise FishDataError(f"{field} must be a non-negative integer")
    return value


def _positive_sim_number(value: Any, field: str) -> SimNumber:
    raw: Any
    if hasattr(value, "sign") and hasattr(value, "digits") and hasattr(value, "scale"):
        sign = getattr(value, "sign")
        digits = getattr(value, "digits")
        scale = getattr(value, "scale")
        if sign not in {-1, 0, 1} or not isinstance(digits, str):
            raise FishDataError(f"{field} must be a positive number")
        try:
            raw = Decimal(digits) * (Decimal(10) ** int(scale))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise FishDataError(f"{field} must be a positive number") from exc
        if sign < 0:
            raw = -raw
        elif sign == 0:
            raw = Decimal(0)
    else:
        raw = value
    try:
        parsed = SimNumber.parse(raw)
    except (ArithmeticError, TypeError, ValueError) as exc:
        raise FishDataError(f"{field} must be a positive number") from exc
    if parsed <= SimNumber.zero():
        raise FishDataError(f"{field} must be a positive number")
    return parsed
