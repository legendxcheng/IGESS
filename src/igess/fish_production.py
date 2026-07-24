from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .fish_barbell import (
    BarbellProductionSnapshot,
    FishBarbellDataAdapter,
)
from .fish_hall import FishHallDataAdapter, FishHallIncomeSnapshot
from .fish_state import BigNumberDTO, PlayerState
from .fish_trash import (
    FishTrashDataAdapter,
    TrashOnlineSettlement,
    TrashProcessingRuntime,
)
from .numbers import SimNumber


_RUNTIME_VERSION = 1


@dataclass(frozen=True)
class FishProductionRuntime:
    trash_processing: TrashProcessingRuntime = field(
        default_factory=TrashProcessingRuntime
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": _RUNTIME_VERSION,
            "trash_processing": self.trash_processing.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "FishProductionRuntime":
        if not isinstance(payload, Mapping):
            raise TypeError("Fish production runtime must be a mapping")
        if not payload:
            return cls()
        if set(payload) != {"version", "trash_processing"}:
            raise ValueError("Fish production runtime has invalid fields")
        if payload["version"] != _RUNTIME_VERSION:
            raise ValueError("Fish production runtime version is unsupported")
        return cls(
            trash_processing=TrashProcessingRuntime.from_dict(
                payload["trash_processing"]
            )
        )


@dataclass(frozen=True)
class AppliedFishProductionSettlement:
    state: PlayerState
    runtime: FishProductionRuntime
    from_time_seconds: int
    to_time_seconds: int
    elapsed_seconds: int
    money_added: SimNumber
    material_added: SimNumber
    strength_added: SimNumber
    fish_hall: FishHallIncomeSnapshot
    barbell: BarbellProductionSnapshot
    trash_processing: TrashOnlineSettlement

    def event_details(self) -> dict[str, str]:
        details = {
            "fish_production_settlement_from_seconds": str(self.from_time_seconds),
            "fish_production_settlement_to_seconds": str(self.to_time_seconds),
            "fish_production_settlement_elapsed_seconds": str(self.elapsed_seconds),
            "fish_hall_money_added": self.money_added.to_decimal_string(),
            "fish_hall_settlement_from_seconds": str(self.from_time_seconds),
            "fish_hall_settlement_to_seconds": str(self.to_time_seconds),
            "fish_hall_settlement_elapsed_seconds": str(self.elapsed_seconds),
            "barbell_strength_added": self.strength_added.to_decimal_string(),
            "barbell_settlement_from_seconds": str(self.from_time_seconds),
            "barbell_settlement_to_seconds": str(self.to_time_seconds),
            "barbell_settlement_elapsed_seconds": str(self.elapsed_seconds),
        }
        details.update(self.fish_hall.event_details(suffix="before_throw"))
        details.update(self.barbell.event_details(suffix="before_command"))
        details.update(self.trash_processing.event_details())
        return details


def settle_fish_production(
    state: PlayerState,
    to_time_seconds: int,
    *,
    hall_adapter: FishHallDataAdapter,
    trash_adapter: FishTrashDataAdapter,
    barbell_adapter: FishBarbellDataAdapter | None = None,
    runtime: FishProductionRuntime | None = None,
) -> AppliedFishProductionSettlement:
    """Atomically settle hall money, trash material, and barbell strength."""

    if not isinstance(state, PlayerState):
        raise TypeError("state must be a PlayerState")
    if type(to_time_seconds) is not int or to_time_seconds < 0:
        raise ValueError("to_time_seconds must be non-negative")
    runtime = runtime or FishProductionRuntime()
    if not isinstance(runtime, FishProductionRuntime):
        raise TypeError("runtime must be a FishProductionRuntime")
    state.validate(hall_adapter.validation_context())
    from_time_seconds = state.production.last_settled_at
    if to_time_seconds < from_time_seconds:
        raise ValueError("Fish production settlement time cannot move backwards")
    elapsed_seconds = to_time_seconds - from_time_seconds
    hall = hall_adapter.snapshot(state)
    money_added = hall.total_income_per_second * SimNumber.parse(elapsed_seconds)
    barbell = (
        BarbellProductionSnapshot(
            equipped_id=0,
            equipped_count=0,
            strength_per_exercise=SimNumber.zero(),
            time_cost_seconds=0,
            strength_per_second=SimNumber.zero(),
        )
        if barbell_adapter is None
        else barbell_adapter.production_snapshot(state)
    )
    strength_added = (
        barbell.strength_per_second * SimNumber.parse(elapsed_seconds)
    )
    trash = trash_adapter.settle_online(
        state,
        elapsed_seconds,
        runtime=runtime.trash_processing,
    )

    committed = state.copy()
    if elapsed_seconds > 0:
        committed.wallet.money = BigNumberDTO.from_value(
            state.wallet.money.to_sim_number() + money_added,
            allow_negative=False,
        )
        committed.wallet.material = BigNumberDTO.from_value(
            state.wallet.material.to_sim_number() + trash.material_added,
            allow_negative=False,
        )
        committed.wallet.strength = BigNumberDTO.from_value(
            state.wallet.strength.to_sim_number() + strength_added,
            allow_negative=False,
        )
        committed.trash_man.processing = trash.processing
        committed.trash_man.realm_id = trash.realm_id_after
        committed.trash_man.training_progress_seconds = (
            trash.training_progress_seconds_after
        )
        committed.production.last_settled_at = to_time_seconds
        committed.meta.revision += 1
    committed.validate(hall_adapter.validation_context())
    return AppliedFishProductionSettlement(
        state=committed,
        runtime=FishProductionRuntime(trash.runtime),
        from_time_seconds=from_time_seconds,
        to_time_seconds=to_time_seconds,
        elapsed_seconds=elapsed_seconds,
        money_added=money_added,
        material_added=trash.material_added,
        strength_added=strength_added,
        fish_hall=hall,
        barbell=barbell,
        trash_processing=trash,
    )
