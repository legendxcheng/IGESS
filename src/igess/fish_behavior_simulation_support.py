from __future__ import annotations

from .behavior import (
    BehaviorCandidate,
    BehaviorDecision,
    BehaviorRuntimeState,
    FixedDuration,
    UniformIntDuration,
)
from .fish_barbell import FishBarbellDataAdapter
from .fish_behavior import (
    EXERCISE_BARBELL_BEHAVIOR_ID,
    FUND_TRASH_MAN_BREAKTHROUGH_BEHAVIOR_ID,
    FISH_BEHAVIOR_IDS,
    MANUAL_THROW_BEHAVIOR_ID,
    PURCHASE_TORPEDO_BEHAVIOR_ID,
    STRENGTH_REBIRTH_BEHAVIOR_ID,
    SYNTHESIZE_BARBELL_BEHAVIOR_ID,
    TRASH_MAN_REBIRTH_BEHAVIOR_ID,
    UPGRADE_FISH_BEHAVIOR_ID,
    UPGRADE_FISH_HALL_BEHAVIOR_ID,
)
from .fish_hall import FishHallDataAdapter
from .fish_production import FishProductionRuntime, settle_fish_production
from .fish_rewards import FishRewardMultipliers
from .fish_state import PlayerState
from .fish_trash import FishTrashDataAdapter
from .schema import EconomyModel, TimelineRow


_COMPACT_EVENT_DETAIL_KEYS = frozenset(
    {
        "barbell_count_after",
        "barbell_count_before",
        "barbell_equipped_id_after_synthesis",
        "barbell_id",
        "barbell_strength_base_added",
        "barbell_strength_added",
        "barbell_strength_reward_multiplier",
        "barbell_strength_per_second_after_synthesis",
        "barbell_strength_per_second_before_synthesis",
        "behavior_completes_at_seconds",
        "behavior_duration_seconds",
        "behavior_id",
        "behavior_sequence_id",
        "behavior_started_at_seconds",
        "behavior_target_id",
        "fish_hall_income_per_second_before_throw",
        "fish_hall_income_per_second_after_throw",
        "fish_hall_cps_before",
        "fish_hall_cps_after",
        "fish_hall_cps_delta",
        "changed_best_hall_layout",
        "is_persistent_progression",
        "fish_hall_money_base_added",
        "fish_hall_money_added",
        "fish_hall_money_reward_multiplier",
        "fish_hall_upgrade_level_after",
        "fish_hall_upgrade_level_before",
        "fish_hall_upgrade_price",
        "fish_id",
        "fish_income_per_second_after",
        "fish_income_per_second_before",
        "fish_instance_id",
        "fish_level_after",
        "fish_level_before",
        "fish_luck",
        "fish_mutation_id",
        "fish_rarity_id",
        "fish_roll_power",
        "fish_upgrade_price",
        "fish_weight_gram",
        "input_strength",
        "money_after_barbell_synthesis",
        "material_after_fish_hall_upgrade",
        "material_after_fish_upgrade",
        "money_before_barbell_synthesis",
        "material_before_fish_hall_upgrade",
        "material_before_fish_upgrade",
        "player_state_revision",
        "strength_after_settlement",
        "strength_before_settlement",
        "throw_id",
        "trash_id",
        "trash_luck",
        "trash_material_base_added",
        "trash_material_added",
        "trash_material_reward_multiplier",
        "trash_rarity_id",
        "trash_roll_power",
        "trash_stock_count",
    }
)


def display_state(
    state: PlayerState,
    time_seconds: int,
    production_runtime: FishProductionRuntime,
    *,
    online: bool,
    active_behavior_id: str | None,
    hall_adapter: FishHallDataAdapter,
    trash_adapter: FishTrashDataAdapter,
    barbell_adapter: FishBarbellDataAdapter,
    reward_multipliers: FishRewardMultipliers | None = None,
) -> PlayerState:
    if state.production.last_settled_at >= time_seconds:
        return state
    return settle_fish_production(
        state,
        time_seconds,
        hall_adapter=hall_adapter,
        trash_adapter=trash_adapter,
        barbell_adapter=barbell_adapter,
        runtime=production_runtime,
        online=online,
        barbell_training_active=(
            online and active_behavior_id == EXERCISE_BARBELL_BEHAVIOR_ID
        ),
        reward_multipliers=reward_multipliers,
    ).state


def fit_candidates_to_online_window(
    candidates: tuple[BehaviorCandidate, ...],
    remaining_seconds: int,
) -> tuple[BehaviorCandidate, ...]:
    """Keep actions that can finish before the strict logout boundary."""

    if type(remaining_seconds) is not int or remaining_seconds <= 0:
        return ()
    fitted: list[BehaviorCandidate] = []
    for candidate in candidates:
        if not candidate.available:
            continue
        duration = candidate.duration
        if isinstance(duration, FixedDuration):
            if duration.seconds > remaining_seconds:
                continue
            fitted_duration = duration
        elif isinstance(duration, UniformIntDuration):
            if duration.min_seconds > remaining_seconds:
                continue
            fitted_duration = UniformIntDuration(
                duration.min_seconds,
                min(duration.max_seconds, remaining_seconds),
            )
        else:
            raise TypeError("unsupported behavior duration")
        fitted.append(
            BehaviorCandidate(
                behavior_id=candidate.behavior_id,
                duration=fitted_duration,
                available=candidate.available,
                targets=candidate.targets,
            )
        )
    return tuple(fitted)


def record_production_counters(
    event_counters: dict[str, int],
    elapsed_seconds: int,
    completed_trash: int,
) -> None:
    if elapsed_seconds <= 0:
        return
    event_counters["fish_hall_settled"] = (
        event_counters.get("fish_hall_settled", 0) + 1
    )
    if completed_trash > 0:
        event_counters["trash_processed"] = (
            event_counters.get("trash_processed", 0) + completed_trash
        )


def timeline_row(
    scenario_id: str,
    profile_id: str,
    time_seconds: int,
    state: PlayerState,
    *,
    model: EconomyModel,
    hall_adapter: FishHallDataAdapter,
) -> TimelineRow:
    hall = hall_adapter.snapshot(state)
    reward_multipliers = FishRewardMultipliers.from_profile(
        model.player_profiles[profile_id]
    )
    return TimelineRow(
        scenario_id=scenario_id,
        profile_id=profile_id,
        time_seconds=time_seconds,
        resources={
            "material": state.wallet.material.to_decimal_string(),
            "money": state.wallet.money.to_decimal_string(),
            "strength": state.wallet.strength.to_decimal_string(),
        },
        generators_owned={
            generator_id: 0 for generator_id in model.generators
        },
        upgrades_purchased=[],
        total_cps=(
            hall.total_income_per_second
            * reward_multipliers.fish_hall_money
        ).to_decimal_string(),
    )


def output_event_details(
    event_kind: str,
    details: dict[str, str],
    *,
    compact: bool,
) -> dict[str, str]:
    if (
        not compact
        or event_kind
        in {
            "strength_reborn",
            "torpedo_purchased",
            "trash_man_reborn",
            "trash_man_breakthrough_funded",
            "trash_man_realm_broken_through",
        }
    ):
        return details
    return {
        key: value
        for key, value in details.items()
        if key in _COMPACT_EVENT_DETAIL_KEYS
    }


def validate_checkpoint(
    state: PlayerState,
    runtime: BehaviorRuntimeState,
    *,
    profile_id: str,
    simulated_time_seconds: int,
    next_throw_id: int,
    event_counters: dict[str, int],
    barbell_adapter: FishBarbellDataAdapter,
) -> None:
    active = runtime.active
    completed = event_counters.get("behavior_completed", 0)
    started = event_counters.get("behavior_decisions_started", 0)
    manual_throws = event_counters.get(
        f"{MANUAL_THROW_BEHAVIOR_ID}_completed",
        0,
    )
    upgrades = event_counters.get(
        f"{UPGRADE_FISH_BEHAVIOR_ID}_completed",
        0,
    )
    hall_upgrades = event_counters.get(
        f"{UPGRADE_FISH_HALL_BEHAVIOR_ID}_completed",
        0,
    )
    torpedo_purchases = event_counters.get(
        f"{PURCHASE_TORPEDO_BEHAVIOR_ID}_completed",
        0,
    )
    barbell_syntheses = event_counters.get(
        f"{SYNTHESIZE_BARBELL_BEHAVIOR_ID}_completed",
        0,
    )
    barbell_exercises = event_counters.get(
        f"{EXERCISE_BARBELL_BEHAVIOR_ID}_completed",
        0,
    )
    strength_rebirths = event_counters.get(
        f"{STRENGTH_REBIRTH_BEHAVIOR_ID}_completed",
        0,
    )
    trash_man_rebirths = event_counters.get(
        f"{TRASH_MAN_REBIRTH_BEHAVIOR_ID}_completed",
        0,
    )
    trash_man_breakthrough_fundings = event_counters.get(
        f"{FUND_TRASH_MAN_BREAKTHROUGH_BEHAVIOR_ID}_completed",
        0,
    )
    idle = event_counters.get("idle_completed", 0)
    counters = (
        completed,
        started,
        manual_throws,
        upgrades,
        hall_upgrades,
        torpedo_purchases,
        barbell_syntheses,
        barbell_exercises,
        strength_rebirths,
        trash_man_rebirths,
        trash_man_breakthrough_fundings,
        idle,
    )
    if any(type(value) is not int or value < 0 for value in counters):
        raise ValueError(
            "weighted behavior checkpoint has invalid event counters"
        )
    trash_count = sum(
        stock.count for stock in state.trash_man.processing.stocks
    )
    trash_processed = event_counters.get("trash_processed", 0)
    if type(trash_processed) is not int or trash_processed < 0:
        raise ValueError(
            "weighted behavior checkpoint has invalid trash counter"
        )
    owned_barbell_count = sum(item.count for item in state.barbell.owned)
    if (
        completed
        != (
            manual_throws
            + upgrades
            + hall_upgrades
            + torpedo_purchases
            + barbell_syntheses
            + barbell_exercises
            + strength_rebirths
            + trash_man_rebirths
            + trash_man_breakthrough_fundings
            + idle
        )
        or started != completed + int(active is not None)
        or runtime.next_sequence_id != started
        or next_throw_id != manual_throws
        or state.statistics.total_throws != manual_throws
        or state.statistics.total_fish_caught != manual_throws
        or len(state.fish.items) != manual_throws
        or state.fish.next_instance_id != manual_throws + 1
        or trash_count + trash_processed != manual_throws
        or state.fish_hall.upgrade_level != hall_upgrades
        or owned_barbell_count < barbell_syntheses
        or state.rebirth.strength_completed_count != strength_rebirths
        or state.rebirth.trash_man_completed_count
        != trash_man_rebirths
        or state.barbell.equipped_id
        != barbell_adapter.best_owned_id(state)
        or state.production.last_settled_at > simulated_time_seconds
    ):
        raise ValueError(
            "weighted behavior checkpoint does not match committed state"
        )
    if active is not None and (
        active.profile_id != profile_id
        or active.behavior_id not in FISH_BEHAVIOR_IDS
        or active.sequence_id != completed
        or not (
            active.started_at_seconds
            <= simulated_time_seconds
            < active.completes_at_seconds
        )
    ):
        raise ValueError(
            "weighted behavior checkpoint has an invalid active behavior"
        )


def increment_counter(counters: dict[str, int], name: str) -> None:
    counters[name] = counters.get(name, 0) + 1


def decision_details(decision: BehaviorDecision) -> dict[str, str]:
    return {
        "behavior_sequence_id": str(decision.sequence_id),
        "behavior_id": decision.behavior_id,
        "behavior_target_id": decision.target_id or "",
        "behavior_duration_seconds": str(decision.duration_seconds),
        "behavior_started_at_seconds": str(decision.started_at_seconds),
        "behavior_completes_at_seconds": str(
            decision.completes_at_seconds
        ),
    }
