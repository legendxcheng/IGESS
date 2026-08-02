from __future__ import annotations

from typing import TYPE_CHECKING

from .fish_data import FishDataError
from .fish_state import PlayerState, TrashProcessingState, TrashStock
from .fish_trash_model import (
    TrashManBreakthroughCompletion,
    TrashManRealmTransition,
    TrashOnlineSettlement,
    TrashProcessingRuntime,
    TrashProcessingSettlement,
)
from .numbers import SimNumber

if TYPE_CHECKING:
    from .fish_trash_rules import FishTrashDataAdapter


def settle_trash(
    adapter: "FishTrashDataAdapter",
    state: PlayerState,
    elapsed_seconds: int,
    *,
    runtime: TrashProcessingRuntime | None = None,
    processing_efficiency: SimNumber = SimNumber.one(),
) -> TrashProcessingSettlement:
    if not isinstance(state, PlayerState):
        raise TypeError("state must be a PlayerState")
    if type(elapsed_seconds) is not int or elapsed_seconds < 0:
        raise ValueError("elapsed_seconds must be non-negative")
    runtime = runtime or TrashProcessingRuntime()
    if not isinstance(runtime, TrashProcessingRuntime):
        raise TypeError("runtime must be a TrashProcessingRuntime")
    processing_efficiency = SimNumber.parse(processing_efficiency)
    if processing_efficiency < SimNumber.zero():
        raise ValueError("processing_efficiency must be non-negative")

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
    speed = adapter.realm_speed(realm_id)
    strength_rebirth_count = state.rebirth.strength_completed_count
    output_multiplier = adapter.strength_material_output_multiplier(
        strength_rebirth_count
    )
    available_work = (
        SimNumber.parse(elapsed_seconds)
        * speed
        * processing_efficiency
    )
    work_consumed = SimNumber.zero()
    material_added = SimNumber.zero()
    completed: dict[int, int] = {}

    def consume_work(trash_id: int, amount: SimNumber) -> None:
        nonlocal work_consumed, material_added
        rule = adapter.trash_rule(trash_id)
        work_consumed += amount
        material_added += rule.base_material_per_second * amount * output_multiplier

    if active_id != 0 and available_work > SimNumber.zero():
        rule = adapter.trash_rule(active_id)
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
        rule = adapter.trash_rule(active_id)
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
        processing_efficiency=processing_efficiency,
        strength_rebirth_completed_count=strength_rebirth_count,
        strength_rebirth_material_multiplier=output_multiplier,
        work_consumed=work_consumed,
        unused_work=available_work,
        material_added=material_added,
        completed_by_trash=tuple(sorted(completed.items())),
        stock_count_before=stock_before,
        stock_count_after=sum(stocks.values()),
    )


def settle_trash_online(
    adapter: "FishTrashDataAdapter",
    state: PlayerState,
    elapsed_seconds: int,
    *,
    runtime: TrashProcessingRuntime | None = None,
    _mutate: bool = False,
) -> TrashOnlineSettlement:
    """Settle trash processing, historical catch-up, and paid breakthroughs."""
    if not isinstance(state, PlayerState):
        raise TypeError("state must be a PlayerState")
    if type(elapsed_seconds) is not int or elapsed_seconds < 0:
        raise ValueError("elapsed_seconds must be non-negative")
    if type(_mutate) is not bool:
        raise TypeError("_mutate must be a bool")
    runtime = runtime or TrashProcessingRuntime()
    if not isinstance(runtime, TrashProcessingRuntime):
        raise TypeError("runtime must be a TrashProcessingRuntime")

    realm_before = state.trash_man.realm_id
    highest_realm = state.trash_man.highest_realm_id
    progress_before = state.trash_man.training_progress_seconds
    breakthrough = state.trash_man.breakthrough
    breakthrough_progress_before = breakthrough.progress_seconds
    try:
        realm_index = adapter._realm_indexes[realm_before]
        highest_index = adapter._realm_indexes[highest_realm]
    except KeyError as exc:
        raise FishDataError(
            "trash-man realm state references unknown production data"
        ) from exc
    if realm_index > highest_index:
        raise FishDataError(
            "trash-man current realm exceeds historical highest realm"
        )

    working = state if _mutate else state.copy()
    current_realm = realm_before
    progress = progress_before
    breakthrough_active = breakthrough.active
    breakthrough_target = breakthrough.target_realm_id
    breakthrough_progress = breakthrough.progress_seconds
    remaining_elapsed = elapsed_seconds
    elapsed_offset = 0
    current_runtime = runtime
    segments: list[TrashProcessingSettlement] = []
    transitions: list[TrashManRealmTransition] = []
    breakthrough_completions: list[TrashManBreakthroughCompletion] = []
    paused = breakthrough.active

    def process_segment(seconds: int) -> None:
        nonlocal current_runtime
        if seconds <= 0:
            return
        working.trash_man.realm_id = current_realm
        settlement = adapter.settle(
            working,
            seconds,
            runtime=current_runtime,
        )
        working.trash_man.processing = settlement.processing
        current_runtime = settlement.runtime
        segments.append(settlement)

    while remaining_elapsed > 0:
        if breakthrough_active:
            next_realm = adapter.next_realm_id(current_realm)
            if current_realm != highest_realm or next_realm is None:
                raise FishDataError(
                    "active trash-man breakthrough must start at the "
                    "historical highest non-final realm"
                )
            if breakthrough_target != next_realm:
                raise FishDataError(
                    "active trash-man breakthrough target must be the next "
                    "configured realm"
                )
            requirement = adapter.progression_seconds_to_next_realm(
                current_realm
            )
            if breakthrough_progress > requirement:
                raise FishDataError(
                    "trash-man breakthrough progress exceeds current realm "
                    "cultivation requirement"
                )
            required_elapsed = requirement - breakthrough_progress
            if required_elapsed > remaining_elapsed:
                process_segment(remaining_elapsed)
                breakthrough_progress += remaining_elapsed
                elapsed_offset += remaining_elapsed
                remaining_elapsed = 0
                break

            process_segment(required_elapsed)
            remaining_elapsed -= required_elapsed
            elapsed_offset += required_elapsed
            transition = TrashManRealmTransition(
                from_realm_id=current_realm,
                to_realm_id=breakthrough_target,
                at_elapsed_seconds=elapsed_offset,
            )
            transitions.append(transition)
            breakthrough_completions.append(
                TrashManBreakthroughCompletion(
                    from_realm_id=current_realm,
                    to_realm_id=breakthrough_target,
                    at_elapsed_seconds=elapsed_offset,
                    required_seconds=requirement,
                    material_cost=adapter.material_required_to_next_realm(
                        current_realm
                    ),
                )
            )
            current_realm = breakthrough_target
            highest_realm = current_realm
            progress = 0
            breakthrough_active = False
            breakthrough_target = 0
            breakthrough_progress = 0
            continue

        if current_realm == highest_realm:
            process_segment(remaining_elapsed)
            elapsed_offset += remaining_elapsed
            remaining_elapsed = 0
            break

        next_realm = adapter.next_realm_id(current_realm)
        if next_realm is None:
            raise FishDataError("trash-man historical highest realm is unreachable")
        requirement = adapter.progression_seconds_to_next_realm(current_realm)
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
            adapter.settle(
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
        cultivation_elapsed_seconds=elapsed_seconds,
        settlement_mode="online",
        realm_id_before=realm_before,
        realm_id_after=current_realm,
        highest_realm_id=highest_realm,
        training_progress_seconds_before=progress_before,
        training_progress_seconds_after=progress,
        paused_by_breakthrough=paused,
        breakthrough_active_after=breakthrough_active,
        breakthrough_target_realm_id_after=breakthrough_target,
        breakthrough_progress_seconds_before=(
            breakthrough_progress_before
        ),
        breakthrough_progress_seconds_after=breakthrough_progress,
        segments=tuple(segments),
        transitions=tuple(transitions),
        breakthrough_completions=tuple(breakthrough_completions),
    )


def settle_trash_offline(
    adapter: "FishTrashDataAdapter",
    state: PlayerState,
    elapsed_seconds: int,
    *,
    runtime: TrashProcessingRuntime | None = None,
    processing_efficiency: SimNumber = SimNumber.parse("0.5"),
) -> TrashOnlineSettlement:
    """Process stocked trash offline without advancing cultivation."""

    if not isinstance(state, PlayerState):
        raise TypeError("state must be a PlayerState")
    if type(elapsed_seconds) is not int or elapsed_seconds < 0:
        raise ValueError("elapsed_seconds must be non-negative")
    runtime = runtime or TrashProcessingRuntime()
    if not isinstance(runtime, TrashProcessingRuntime):
        raise TypeError("runtime must be a TrashProcessingRuntime")
    segment = adapter.settle(
        state,
        elapsed_seconds,
        runtime=runtime,
        processing_efficiency=processing_efficiency,
    )
    return TrashOnlineSettlement(
        processing=segment.processing,
        runtime=segment.runtime,
        elapsed_seconds=elapsed_seconds,
        cultivation_elapsed_seconds=0,
        settlement_mode="offline",
        realm_id_before=state.trash_man.realm_id,
        realm_id_after=state.trash_man.realm_id,
        highest_realm_id=state.trash_man.highest_realm_id,
        training_progress_seconds_before=(
            state.trash_man.training_progress_seconds
        ),
        training_progress_seconds_after=(
            state.trash_man.training_progress_seconds
        ),
        paused_by_breakthrough=state.trash_man.breakthrough.active,
        breakthrough_active_after=state.trash_man.breakthrough.active,
        breakthrough_target_realm_id_after=(
            state.trash_man.breakthrough.target_realm_id
        ),
        breakthrough_progress_seconds_before=(
            state.trash_man.breakthrough.progress_seconds
        ),
        breakthrough_progress_seconds_after=(
            state.trash_man.breakthrough.progress_seconds
        ),
        segments=(segment,),
        transitions=(),
        breakthrough_completions=(),
    )
