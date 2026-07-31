from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .fish_barbell import (
    BarbellProductionSnapshot,
    FishBarbellDataAdapter,
)
from .fish_hall import FishHallDataAdapter, FishHallIncomeSnapshot
from .fish_rewards import FishRewardMultipliers
from .fish_state import BigNumberDTO, PlayerState
from .fish_trash import (
    FishTrashDataAdapter,
    TrashOnlineSettlement,
    TrashProcessingRuntime,
)
from .numbers import SimNumber


_RUNTIME_VERSION = 1
FISH_OFFLINE_EFFICIENCY = SimNumber.parse("0.5")


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
    online: bool
    passive_efficiency: SimNumber
    barbell_training_active: bool
    reward_multipliers: FishRewardMultipliers
    money_base_added: SimNumber
    money_added: SimNumber
    material_base_added: SimNumber
    material_added: SimNumber
    strength_base_added: SimNumber
    strength_added: SimNumber
    strength_before: SimNumber
    strength_after: SimNumber
    fish_hall: FishHallIncomeSnapshot
    barbell: BarbellProductionSnapshot
    trash_processing: TrashOnlineSettlement

    def event_details(self) -> dict[str, str]:
        details = {
            "fish_production_settlement_from_seconds": str(self.from_time_seconds),
            "fish_production_settlement_to_seconds": str(self.to_time_seconds),
            "fish_production_settlement_elapsed_seconds": str(self.elapsed_seconds),
            "fish_production_mode": (
                "online" if self.online else "offline"
            ),
            "fish_passive_production_efficiency": (
                self.passive_efficiency.to_decimal_string()
            ),
            "fish_hall_settlement_from_seconds": str(self.from_time_seconds),
            "fish_hall_settlement_to_seconds": str(self.to_time_seconds),
            "fish_hall_settlement_elapsed_seconds": str(self.elapsed_seconds),
            "strength_before_settlement": (
                self.strength_before.to_decimal_string()
            ),
            "strength_after_settlement": (
                self.strength_after.to_decimal_string()
            ),
            "barbell_training_active": str(
                self.barbell_training_active
            ).lower(),
            "barbell_strength_online_only": "true",
            "barbell_settlement_from_seconds": str(self.from_time_seconds),
            "barbell_settlement_to_seconds": str(self.to_time_seconds),
            "barbell_settlement_elapsed_seconds": str(self.elapsed_seconds),
        }
        details.update(self.fish_hall.event_details(suffix="before_throw"))
        details.update(self.barbell.event_details(suffix="before_command"))
        details.update(self.trash_processing.event_details())
        details.update(
            {
                "fish_hall_money_base_added": (
                    self.money_base_added.to_decimal_string()
                ),
                "fish_hall_money_reward_multiplier": (
                    self.reward_multipliers.fish_hall_money
                    .to_decimal_string()
                ),
                "fish_hall_money_added": (
                    self.money_added.to_decimal_string()
                ),
                "trash_material_base_added": (
                    self.material_base_added.to_decimal_string()
                ),
                "trash_material_reward_multiplier": (
                    self.reward_multipliers.trash_material
                    .to_decimal_string()
                ),
                "trash_material_added": (
                    self.material_added.to_decimal_string()
                ),
                "barbell_strength_base_added": (
                    self.strength_base_added.to_decimal_string()
                ),
                "barbell_strength_reward_multiplier": (
                    self.reward_multipliers.barbell_strength
                    .to_decimal_string()
                ),
                "barbell_strength_added": (
                    self.strength_added.to_decimal_string()
                ),
            }
        )
        return details


def settle_fish_production(
    state: PlayerState,
    to_time_seconds: int,
    *,
    hall_adapter: FishHallDataAdapter,
    trash_adapter: FishTrashDataAdapter,
    barbell_adapter: FishBarbellDataAdapter | None = None,
    runtime: FishProductionRuntime | None = None,
    online: bool = True,
    barbell_training_active: bool = False,
    reward_multipliers: FishRewardMultipliers | None = None,
    _mutate: bool = False,
) -> AppliedFishProductionSettlement:
    """Atomically settle one uninterrupted Fish production interval.

    Hall and trash processing are passive. Equipped barbells produce strength
    only while the foreground ``exercise_barbell`` behavior is active online.
    """

    if not isinstance(state, PlayerState):
        raise TypeError("state must be a PlayerState")
    if type(to_time_seconds) is not int or to_time_seconds < 0:
        raise ValueError("to_time_seconds must be non-negative")
    if type(online) is not bool:
        raise TypeError("online must be a bool")
    if type(barbell_training_active) is not bool:
        raise TypeError("barbell_training_active must be a bool")
    if type(_mutate) is not bool:
        raise TypeError("_mutate must be a bool")
    if barbell_training_active and not online:
        raise ValueError("barbell training cannot produce while offline")
    runtime = runtime or FishProductionRuntime()
    if not isinstance(runtime, FishProductionRuntime):
        raise TypeError("runtime must be a FishProductionRuntime")
    reward_multipliers = reward_multipliers or FishRewardMultipliers()
    if not isinstance(reward_multipliers, FishRewardMultipliers):
        raise TypeError(
            "reward_multipliers must be a FishRewardMultipliers"
        )
    if not _mutate:
        state.validate(hall_adapter.validation_context())
    from_time_seconds = state.production.last_settled_at
    if to_time_seconds < from_time_seconds:
        raise ValueError("Fish production settlement time cannot move backwards")
    elapsed_seconds = to_time_seconds - from_time_seconds
    passive_efficiency = (
        SimNumber.one() if online else FISH_OFFLINE_EFFICIENCY
    )
    hall = hall_adapter.snapshot(state, use_cache=_mutate)
    money_base_added = (
        hall.total_income_per_second
        * SimNumber.parse(elapsed_seconds)
        * passive_efficiency
    )
    money_added = (
        money_base_added * reward_multipliers.fish_hall_money
    )
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
    strength_base_added = (
        barbell.strength_per_second * SimNumber.parse(elapsed_seconds)
        if barbell_training_active
        else SimNumber.zero()
    )
    trash = (
        trash_adapter.settle_online(
            state,
            elapsed_seconds,
            runtime=runtime.trash_processing,
            _mutate=_mutate,
        )
        if online
        else trash_adapter.settle_offline(
            state,
            elapsed_seconds,
            runtime=runtime.trash_processing,
            processing_efficiency=passive_efficiency,
        )
    )
    material_base_added = trash.material_added
    material_added = (
        material_base_added * reward_multipliers.trash_material
    )
    strength_added = (
        strength_base_added * reward_multipliers.barbell_strength
    )

    strength_before = state.wallet.strength.to_sim_number()
    committed = state if _mutate else state.copy()
    if elapsed_seconds > 0:
        committed.wallet.money = BigNumberDTO.from_value(
            state.wallet.money.to_sim_number() + money_added,
            allow_negative=False,
        )
        committed.wallet.material = BigNumberDTO.from_value(
            state.wallet.material.to_sim_number() + material_added,
            allow_negative=False,
        )
        committed.wallet.strength = BigNumberDTO.from_value(
            state.wallet.strength.to_sim_number() + strength_added,
            allow_negative=False,
        )
        committed.trash_man.processing = trash.processing
        committed.trash_man.realm_id = trash.realm_id_after
        committed.trash_man.highest_realm_id = trash.highest_realm_id
        committed.trash_man.training_progress_seconds = (
            trash.training_progress_seconds_after
        )
        committed.trash_man.breakthrough.active = (
            trash.breakthrough_active_after
        )
        committed.trash_man.breakthrough.target_realm_id = (
            trash.breakthrough_target_realm_id_after
        )
        committed.trash_man.breakthrough.progress_seconds = (
            trash.breakthrough_progress_seconds_after
        )
        committed.production.last_settled_at = to_time_seconds
        committed.meta.revision += 1
    if not _mutate:
        committed.validate(hall_adapter.validation_context())
    return AppliedFishProductionSettlement(
        state=committed,
        runtime=FishProductionRuntime(trash.runtime),
        from_time_seconds=from_time_seconds,
        to_time_seconds=to_time_seconds,
        elapsed_seconds=elapsed_seconds,
        online=online,
        passive_efficiency=passive_efficiency,
        barbell_training_active=barbell_training_active,
        reward_multipliers=reward_multipliers,
        money_base_added=money_base_added,
        money_added=money_added,
        material_base_added=material_base_added,
        material_added=material_added,
        strength_base_added=strength_base_added,
        strength_added=strength_added,
        strength_before=strength_before,
        strength_after=committed.wallet.strength.to_sim_number(),
        fish_hall=hall,
        barbell=barbell,
        trash_processing=trash,
    )
