from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .behavior import (
    IDLE_BEHAVIOR_ID,
    BehaviorCandidate,
    BehaviorDecision,
    BehaviorProfile,
    BehaviorTarget,
    DurationSpec,
    FixedDuration,
    UniformIntDuration,
)
from .fish_barbell import FishBarbellDataAdapter
from .fish_commands import (
    apply_fish_hall_upgrade,
    apply_strength_rebirth,
    apply_throw_resolution,
    lock_throw_request,
    synthesize_barbell,
    upgrade_fish,
)
from .fish_hall import FishHallDataAdapter
from .fish_production import (
    FishProductionRuntime,
    settle_fish_production,
)
from .fish_state import FISH_MAX_LEVEL, PlayerState
from .fish_trash import FishTrashDataAdapter
from .fish_throw_data import FishThrowDataAdapter, ProductionThrowConfig
from .numbers import SimNumber
from .schema import PlayerProfile


MANUAL_THROW_BEHAVIOR_ID = "manual_throw"
UPGRADE_FISH_BEHAVIOR_ID = "upgrade_fish"
UPGRADE_FISH_HALL_BEHAVIOR_ID = "upgrade_fish_hall"
SYNTHESIZE_BARBELL_BEHAVIOR_ID = "synthesize_barbell"
STRENGTH_REBIRTH_BEHAVIOR_ID = "strength_rebirth"
RANDOM_AFFORDABLE_POLICY_ID = "random_affordable"
FISH_BEHAVIOR_IDS = frozenset(
    {
        MANUAL_THROW_BEHAVIOR_ID,
        UPGRADE_FISH_BEHAVIOR_ID,
        UPGRADE_FISH_HALL_BEHAVIOR_ID,
        SYNTHESIZE_BARBELL_BEHAVIOR_ID,
        STRENGTH_REBIRTH_BEHAVIOR_ID,
        IDLE_BEHAVIOR_ID,
    }
)


class FishBehaviorConfigError(ValueError):
    """Raised when a player behavior profile cannot drive the Fish domain."""


@dataclass(frozen=True)
class FishBehaviorCompletion:
    state: PlayerState
    production_runtime: FishProductionRuntime
    next_throw_id: int
    event_kind: str
    item_id: str
    details: dict[str, str]


class FishBehaviorAdapter:
    """Connect the generic behavior scheduler to Fish domain commands."""

    def __init__(
        self,
        *,
        throw_adapter: FishThrowDataAdapter,
        hall_adapter: FishHallDataAdapter,
        trash_adapter: FishTrashDataAdapter,
        barbell_adapter: FishBarbellDataAdapter,
        throw_config: ProductionThrowConfig,
    ) -> None:
        self.throw_adapter = throw_adapter
        self.hall_adapter = hall_adapter
        self.trash_adapter = trash_adapter
        self.barbell_adapter = barbell_adapter
        self.throw_config = throw_config

    def behavior_profile(self, profile: PlayerProfile) -> BehaviorProfile:
        unknown = set(profile.behavior_weights) - FISH_BEHAVIOR_IDS
        if unknown:
            raise FishBehaviorConfigError(
                "Fish behavior profile contains unknown behaviors: "
                + ", ".join(sorted(unknown))
            )
        positive_ids = {
            behavior_id
            for behavior_id, weight in profile.behavior_weights.items()
            if weight > SimNumber.zero()
        }
        missing_durations = positive_ids - set(profile.behavior_durations)
        if missing_durations:
            raise FishBehaviorConfigError(
                "Fish behavior profile is missing durations for: "
                + ", ".join(sorted(missing_durations))
            )
        unknown_durations = set(profile.behavior_durations) - FISH_BEHAVIOR_IDS
        if unknown_durations:
            raise FishBehaviorConfigError(
                "Fish behavior profile contains durations for unknown behaviors: "
                + ", ".join(sorted(unknown_durations))
            )

        upgrade_weight = profile.behavior_weights.get(
            UPGRADE_FISH_BEHAVIOR_ID
        )
        if upgrade_weight is not None and upgrade_weight > SimNumber.zero():
            policy = profile.behavior_target_policies.get(
                UPGRADE_FISH_BEHAVIOR_ID
            )
            if policy is None:
                raise FishBehaviorConfigError(
                    "upgrade_fish requires an explicit target policy"
                )
            if policy != RANDOM_AFFORDABLE_POLICY_ID:
                raise FishBehaviorConfigError(
                    f"unknown Fish upgrade target policy: {policy}"
                )
        synthesis_weight = profile.behavior_weights.get(
            SYNTHESIZE_BARBELL_BEHAVIOR_ID
        )
        if (
            synthesis_weight is not None
            and synthesis_weight > SimNumber.zero()
        ):
            policy = profile.behavior_target_policies.get(
                SYNTHESIZE_BARBELL_BEHAVIOR_ID
            )
            if policy is None:
                raise FishBehaviorConfigError(
                    "synthesize_barbell requires an explicit target policy"
                )
            if policy != RANDOM_AFFORDABLE_POLICY_ID:
                raise FishBehaviorConfigError(
                    f"unknown Barbell synthesis target policy: {policy}"
                )
        extra_policies = (
            set(profile.behavior_target_policies)
            - {
                UPGRADE_FISH_BEHAVIOR_ID,
                SYNTHESIZE_BARBELL_BEHAVIOR_ID,
            }
        )
        if extra_policies:
            raise FishBehaviorConfigError(
                "Fish behavior profile contains unsupported target policies for: "
                + ", ".join(sorted(extra_policies))
            )
        return BehaviorProfile(
            profile_id=profile.id,
            weights=profile.behavior_weights,
        )

    def candidates(
        self,
        state: PlayerState,
        profile: PlayerProfile,
    ) -> tuple[BehaviorCandidate, ...]:
        """Return current foreground actions; Fish hall income stays passive."""

        state.validate(self.hall_adapter.validation_context())
        candidates: list[BehaviorCandidate] = []
        for behavior_id, weight in sorted(profile.behavior_weights.items()):
            if weight <= SimNumber.zero():
                continue
            duration = self._duration(
                profile.behavior_durations[behavior_id],
                behavior_id,
            )
            if behavior_id == MANUAL_THROW_BEHAVIOR_ID:
                candidates.append(
                    BehaviorCandidate(
                        behavior_id=behavior_id,
                        duration=duration,
                        available=(
                            state.torpedo.selected_id > 0
                            and state.wallet.strength.to_sim_number() > 0
                        ),
                    )
                )
            elif behavior_id == UPGRADE_FISH_BEHAVIOR_ID:
                targets = self._upgrade_targets(state, profile)
                candidates.append(
                    BehaviorCandidate(
                        behavior_id=behavior_id,
                        duration=duration,
                        available=bool(targets),
                        targets=targets,
                    )
                )
            elif behavior_id == UPGRADE_FISH_HALL_BEHAVIOR_ID:
                hall_level = state.fish_hall.upgrade_level
                can_upgrade = self.hall_adapter.can_upgrade_hall(hall_level)
                candidates.append(
                    BehaviorCandidate(
                        behavior_id=behavior_id,
                        duration=duration,
                        available=(
                            can_upgrade
                            and self.hall_adapter.hall_upgrade_price(
                                hall_level
                            )
                            <= state.wallet.material.to_sim_number()
                        ),
                    )
                )
            elif behavior_id == SYNTHESIZE_BARBELL_BEHAVIOR_ID:
                targets = self._barbell_synthesis_targets(state, profile)
                candidates.append(
                    BehaviorCandidate(
                        behavior_id=behavior_id,
                        duration=duration,
                        available=bool(targets),
                        targets=targets,
                    )
                )
            elif behavior_id == STRENGTH_REBIRTH_BEHAVIOR_ID:
                candidates.append(
                    BehaviorCandidate(
                        behavior_id=behavior_id,
                        duration=duration,
                        available=self.hall_adapter.can_strength_rebirth(
                            state
                        ),
                    )
                )
            elif behavior_id == IDLE_BEHAVIOR_ID:
                candidates.append(BehaviorCandidate.idle(duration))
        return tuple(candidates)

    def complete(
        self,
        state: PlayerState,
        decision: BehaviorDecision,
        *,
        root_random_seed: int,
        next_throw_id: int,
        production_runtime: FishProductionRuntime | None = None,
    ) -> FishBehaviorCompletion:
        if decision.completes_at_seconds < state.production.last_settled_at:
            raise ValueError("behavior completion precedes Fish hall settlement")
        settlement = settle_fish_production(
            state,
            decision.completes_at_seconds,
            hall_adapter=self.hall_adapter,
            trash_adapter=self.trash_adapter,
            barbell_adapter=self.barbell_adapter,
            runtime=production_runtime,
        )
        committed = settlement.state
        details = self._decision_details(decision)
        details.update(settlement.event_details())

        if decision.behavior_id == MANUAL_THROW_BEHAVIOR_ID:
            request = lock_throw_request(
                committed,
                adapter=self.throw_adapter,
                root_random_seed=root_random_seed,
                throw_id=next_throw_id,
                regular_luck_multiplier=(
                    self.throw_config.regular_luck_multiplier
                ),
            )
            resolution = self.throw_adapter.resolve(request)
            application = apply_throw_resolution(
                committed,
                resolution,
                adapter=self.throw_adapter,
                hall_adapter=self.hall_adapter,
            )
            details.update(resolution.event_details())
            details.update(application.event_details())
            details["strength_source"] = "player_state_snapshot"
            return FishBehaviorCompletion(
                state=application.state,
                production_runtime=settlement.runtime,
                next_throw_id=next_throw_id + 1,
                event_kind="fish_throw_resolved",
                item_id=f"throw:{next_throw_id}",
                details=details,
            )

        if decision.behavior_id == UPGRADE_FISH_BEHAVIOR_ID:
            try:
                instance_id = int(decision.target_id or "")
            except ValueError as exc:
                raise ValueError(
                    "upgrade_fish behavior has an invalid target id"
                ) from exc
            application = upgrade_fish(
                committed,
                instance_id,
                hall_adapter=self.hall_adapter,
            )
            details.update(application.event_details())
            return FishBehaviorCompletion(
                state=application.state,
                production_runtime=settlement.runtime,
                next_throw_id=next_throw_id,
                event_kind="fish_upgraded",
                item_id=f"fish:{instance_id}",
                details=details,
            )

        if decision.behavior_id == UPGRADE_FISH_HALL_BEHAVIOR_ID:
            application = apply_fish_hall_upgrade(
                committed,
                hall_adapter=self.hall_adapter,
            )
            details.update(application.event_details())
            return FishBehaviorCompletion(
                state=application.state,
                production_runtime=settlement.runtime,
                next_throw_id=next_throw_id,
                event_kind="fish_hall_upgraded",
                item_id=f"fish_hall:{application.to_level}",
                details=details,
            )

        if decision.behavior_id == SYNTHESIZE_BARBELL_BEHAVIOR_ID:
            try:
                barbell_id = int(decision.target_id or "")
            except ValueError as exc:
                raise ValueError(
                    "synthesize_barbell behavior has an invalid target id"
                ) from exc
            application = synthesize_barbell(
                committed,
                barbell_id,
                hall_adapter=self.hall_adapter,
                barbell_adapter=self.barbell_adapter,
            )
            details.update(application.event_details())
            return FishBehaviorCompletion(
                state=application.state,
                production_runtime=settlement.runtime,
                next_throw_id=next_throw_id,
                event_kind="barbell_synthesized",
                item_id=f"barbell:{barbell_id}",
                details=details,
            )

        if decision.behavior_id == STRENGTH_REBIRTH_BEHAVIOR_ID:
            application = apply_strength_rebirth(
                committed,
                hall_adapter=self.hall_adapter,
            )
            details.update(application.event_details())
            return FishBehaviorCompletion(
                state=application.state,
                production_runtime=settlement.runtime,
                next_throw_id=next_throw_id,
                event_kind="strength_reborn",
                item_id=(
                    "strength_rebirth:"
                    f"{application.to_completed_count}"
                ),
                details=details,
            )

        if decision.behavior_id == IDLE_BEHAVIOR_ID:
            return FishBehaviorCompletion(
                state=committed,
                production_runtime=settlement.runtime,
                next_throw_id=next_throw_id,
                event_kind="fish_behavior_idle_completed",
                item_id=f"idle:{decision.sequence_id}",
                details=details,
            )

        raise ValueError(f"unsupported Fish behavior: {decision.behavior_id}")

    def _upgrade_targets(
        self,
        state: PlayerState,
        profile: PlayerProfile,
    ) -> tuple[BehaviorTarget, ...]:
        policy = profile.behavior_target_policies.get(
            UPGRADE_FISH_BEHAVIOR_ID
        )
        if policy != RANDOM_AFFORDABLE_POLICY_ID:
            return ()
        money = state.wallet.money.to_sim_number()
        targets = []
        for item in sorted(
            state.fish.items,
            key=lambda value: value.instance_id,
        ):
            if item.level >= FISH_MAX_LEVEL:
                continue
            if self.hall_adapter.upgrade_price(item) <= money:
                targets.append(BehaviorTarget(str(item.instance_id)))
        return tuple(targets)

    def _barbell_synthesis_targets(
        self,
        state: PlayerState,
        profile: PlayerProfile,
    ) -> tuple[BehaviorTarget, ...]:
        policy = profile.behavior_target_policies.get(
            SYNTHESIZE_BARBELL_BEHAVIOR_ID
        )
        if policy != RANDOM_AFFORDABLE_POLICY_ID:
            return ()
        material = state.wallet.material.to_sim_number()
        owned_ids = {
            item.barbell_id
            for item in state.barbell.owned
            if item.count > 0
        }
        return tuple(
            BehaviorTarget(str(rule.barbell_id))
            for rule in self.barbell_adapter.rules
            if rule.barbell_id not in owned_ids
            and rule.price <= material
        )

    @staticmethod
    def _duration(
        payload: Mapping[str, Any],
        behavior_id: str,
    ) -> DurationSpec:
        try:
            duration_type = payload["type"]
            if duration_type == "fixed":
                return FixedDuration(payload["seconds"])
            if duration_type == "uniform":
                return UniformIntDuration(
                    payload["min_seconds"],
                    payload["max_seconds"],
                )
        except (KeyError, TypeError, ValueError) as exc:
            raise FishBehaviorConfigError(
                f"invalid duration for Fish behavior '{behavior_id}'"
            ) from exc
        raise FishBehaviorConfigError(
            f"invalid duration type for Fish behavior '{behavior_id}'"
        )

    @staticmethod
    def _decision_details(
        decision: BehaviorDecision,
    ) -> dict[str, str]:
        return {
            "behavior_sequence_id": str(decision.sequence_id),
            "behavior_id": decision.behavior_id,
            "behavior_target_id": decision.target_id or "",
            "behavior_duration_seconds": str(decision.duration_seconds),
            "behavior_started_at_seconds": str(
                decision.started_at_seconds
            ),
            "behavior_completes_at_seconds": str(
                decision.completes_at_seconds
            ),
        }
