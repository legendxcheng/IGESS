from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .behavior import BehaviorProfile
from .fish_state import PlayerState
from .numbers import SimNumber


MANUAL_THROW_BEHAVIOR_ID = "manual_throw"
MANUAL_THROW_REFILL_CONDITION = (
    "fish_hall_not_full_or_trash_processing_empty"
)
TRASH_MAN_BREAKTHROUGH_IMMEDIATE = "immediate"
TRASH_MAN_BREAKTHROUGH_WEIGHTED_DELAY = "weighted_delay"
TRASH_MAN_BREAKTHROUGH_PRESERVE_MATERIAL = "preserve_material"
TRASH_MAN_BREAKTHROUGH_POLICY_IDS = frozenset(
    {
        TRASH_MAN_BREAKTHROUGH_IMMEDIATE,
        TRASH_MAN_BREAKTHROUGH_WEIGHTED_DELAY,
        TRASH_MAN_BREAKTHROUGH_PRESERVE_MATERIAL,
    }
)


@dataclass(frozen=True)
class TrashManBreakthroughPolicy:
    """Player strategy for the explicit realm-breakthrough command."""

    mode: str = TRASH_MAN_BREAKTHROUGH_WEIGHTED_DELAY

    def __post_init__(self) -> None:
        if not isinstance(self.mode, str):
            raise TypeError("trash-man breakthrough policy must be a string")
        if self.mode not in TRASH_MAN_BREAKTHROUGH_POLICY_IDS:
            raise ValueError(
                "unknown trash-man breakthrough policy: "
                f"{self.mode}"
            )

    @classmethod
    def from_engine_settings(
        cls,
        settings: Mapping[str, Any],
    ) -> "TrashManBreakthroughPolicy":
        scheduler = settings.get("behavior_scheduler", {})
        if not isinstance(scheduler, Mapping):
            raise ValueError("engine.behavior_scheduler must be a mapping")
        mode = scheduler.get(
            "trash_man_breakthrough_policy",
            TRASH_MAN_BREAKTHROUGH_WEIGHTED_DELAY,
        )
        if not isinstance(mode, str):
            raise ValueError(
                "engine.behavior_scheduler."
                "trash_man_breakthrough_policy must be a string"
            )
        return cls(mode=mode)

    def manifest_parameters(self) -> dict[str, str]:
        return {
            "mode": self.mode,
            "command_is_explicit": "true",
            "state_machine_auto_funds": "false",
        }


@dataclass(frozen=True)
class ManualThrowRefillRule:
    """Increase throw selection pressure while either source queue needs filling."""

    weight_multiplier: SimNumber = SimNumber.one()

    def __post_init__(self) -> None:
        multiplier = SimNumber.parse(self.weight_multiplier)
        if multiplier < SimNumber.one():
            raise ValueError(
                "manual throw refill weight_multiplier must be at least 1"
            )
        object.__setattr__(self, "weight_multiplier", multiplier)

    @classmethod
    def from_engine_settings(
        cls,
        settings: Mapping[str, Any],
    ) -> "ManualThrowRefillRule":
        scheduler = settings.get("behavior_scheduler", {})
        if not isinstance(scheduler, Mapping):
            raise ValueError("engine.behavior_scheduler must be a mapping")
        refill = scheduler.get("manual_throw_refill", {})
        if not isinstance(refill, Mapping):
            raise ValueError(
                "engine.behavior_scheduler.manual_throw_refill must be a mapping"
            )
        unknown = set(refill) - {"weight_multiplier"}
        if unknown:
            raise ValueError(
                "manual throw refill contains unknown settings: "
                + ", ".join(sorted(unknown))
            )
        return cls(
            weight_multiplier=SimNumber.parse(
                refill.get("weight_multiplier", SimNumber.one())
            )
        )

    @property
    def enabled(self) -> bool:
        return self.weight_multiplier > SimNumber.one()

    def condition_state(
        self,
        state: PlayerState,
        *,
        fish_hall_capacity: int,
    ) -> tuple[bool, bool]:
        if not isinstance(state, PlayerState):
            raise TypeError("state must be a PlayerState")
        if type(fish_hall_capacity) is not int or fish_hall_capacity <= 0:
            raise ValueError("fish_hall_capacity must be a positive integer")
        hall_not_full = len(state.fish.items) < fish_hall_capacity
        trash_processing_empty = not state.trash_man.processing.stocks
        return hall_not_full, trash_processing_empty

    def is_active(
        self,
        state: PlayerState,
        *,
        fish_hall_capacity: int,
    ) -> bool:
        hall_not_full, trash_processing_empty = self.condition_state(
            state,
            fish_hall_capacity=fish_hall_capacity,
        )
        return self.enabled and (hall_not_full or trash_processing_empty)

    def effective_profile(
        self,
        state: PlayerState,
        profile: BehaviorProfile,
        *,
        fish_hall_capacity: int,
    ) -> BehaviorProfile:
        if not isinstance(profile, BehaviorProfile):
            raise TypeError("profile must be a BehaviorProfile")
        if not self.is_active(
            state,
            fish_hall_capacity=fish_hall_capacity,
        ):
            return profile
        base_weight = profile.weights.get(
            MANUAL_THROW_BEHAVIOR_ID,
            SimNumber.zero(),
        )
        if base_weight <= SimNumber.zero():
            return profile
        weights = dict(profile.weights)
        weights[MANUAL_THROW_BEHAVIOR_ID] = (
            base_weight * self.weight_multiplier
        )
        return BehaviorProfile(profile.profile_id, weights)

    def manifest_parameters(self) -> dict[str, str]:
        return {
            "behavior_id": MANUAL_THROW_BEHAVIOR_ID,
            "condition": MANUAL_THROW_REFILL_CONDITION,
            "weight_multiplier": self.weight_multiplier.to_decimal_string(),
        }
