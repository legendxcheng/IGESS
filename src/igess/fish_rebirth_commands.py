from __future__ import annotations

from .fish_command_results import (
    AppliedStrengthRebirth,
    AppliedTrashManRebirth,
    FishCommandError,
)
from .fish_data import FishDataError
from .fish_hall import FishHallDataAdapter
from .fish_state import BigNumberDTO, PlayerState
from .fish_trash import FishTrashDataAdapter
from .numbers import SimNumber


def apply_strength_rebirth(
    state: PlayerState,
    *,
    hall_adapter: FishHallDataAdapter,
    _mutate: bool = False,
) -> AppliedStrengthRebirth:
    """Atomically reset strength and earn a permanent material multiplier.

    Callers must settle continuous production to the command timestamp before
    invoking this transaction.
    """

    if not isinstance(state, PlayerState):
        raise FishCommandError("state must be a PlayerState")
    if not isinstance(hall_adapter, FishHallDataAdapter):
        raise FishCommandError("hall_adapter must be a FishHallDataAdapter")
    if type(_mutate) is not bool:
        raise FishCommandError("_mutate must be a bool")
    if not _mutate:
        state.validate(hall_adapter.validation_context())

    from_completed_count = state.rebirth.strength_completed_count
    try:
        rule = hall_adapter.next_strength_rebirth_rule(
            from_completed_count
        )
    except FishDataError as exc:
        raise FishCommandError(str(exc)) from exc
    strength_before = state.wallet.strength.to_sim_number()
    if strength_before < rule.strength_requirement:
        raise FishCommandError(
            "insufficient strength for strength rebirth: "
            f"need {rule.strength_requirement.to_decimal_string()}, "
            f"have {strength_before.to_decimal_string()}"
        )

    multiplier_before = hall_adapter.strength_material_output_multiplier(
        from_completed_count
    )
    committed = state if _mutate else state.copy()
    committed.wallet.strength = BigNumberDTO.from_value(
        SimNumber.zero(),
        allow_negative=False,
    )
    committed.rebirth.strength_completed_count = rule.completed_count
    committed.meta.revision += 1
    if not _mutate:
        committed.validate(hall_adapter.validation_context())
    multiplier_after = hall_adapter.strength_material_output_multiplier(
        rule.completed_count
    )
    return AppliedStrengthRebirth(
        state=committed,
        from_completed_count=from_completed_count,
        to_completed_count=rule.completed_count,
        strength_requirement=rule.strength_requirement,
        strength_before=strength_before,
        strength_after=committed.wallet.strength.to_sim_number(),
        material_multiplier_before=multiplier_before,
        material_multiplier_after=multiplier_after,
    )


def apply_trash_man_rebirth(
    state: PlayerState,
    *,
    trash_adapter: FishTrashDataAdapter,
    _mutate: bool = False,
) -> AppliedTrashManRebirth:
    """Reset current realm and earn a permanent Fish Hall multiplier.

    Callers must settle continuous production to the command timestamp before
    invoking this transaction.
    """

    if not isinstance(state, PlayerState):
        raise FishCommandError("state must be a PlayerState")
    if not isinstance(trash_adapter, FishTrashDataAdapter):
        raise FishCommandError(
            "trash_adapter must be a FishTrashDataAdapter"
        )
    if type(_mutate) is not bool:
        raise FishCommandError("_mutate must be a bool")
    if not _mutate:
        state.validate()

    from_completed_count = state.rebirth.trash_man_completed_count
    realm_before = state.trash_man.realm_id
    try:
        rule = trash_adapter.next_trash_man_rebirth_rule(
            from_completed_count
        )
        trash_adapter.realm_speed(realm_before)
    except FishDataError as exc:
        raise FishCommandError(str(exc)) from exc
    if state.trash_man.breakthrough.active:
        raise FishCommandError(
            "trash-man rebirth is unavailable during an active breakthrough"
        )
    if realm_before < rule.realm_requirement:
        raise FishCommandError(
            "insufficient realm for trash-man rebirth: "
            f"need {rule.realm_requirement}, have {realm_before}"
        )

    multiplier_before = trash_adapter.fish_hall_output_multiplier(
        from_completed_count
    )
    training_progress_seconds_before = (
        state.trash_man.training_progress_seconds
    )
    committed = state if _mutate else state.copy()
    committed.trash_man.realm_id = trash_adapter.initial_realm_id
    committed.trash_man.training_progress_seconds = 0
    committed.rebirth.trash_man_completed_count = rule.completed_count
    committed.meta.revision += 1
    if not _mutate:
        committed.validate()
    multiplier_after = trash_adapter.fish_hall_output_multiplier(
        rule.completed_count
    )
    return AppliedTrashManRebirth(
        state=committed,
        from_completed_count=from_completed_count,
        to_completed_count=rule.completed_count,
        realm_requirement=rule.realm_requirement,
        realm_before=realm_before,
        realm_after=committed.trash_man.realm_id,
        highest_realm_id=committed.trash_man.highest_realm_id,
        training_progress_seconds_before=training_progress_seconds_before,
        training_progress_seconds_after=(
            committed.trash_man.training_progress_seconds
        ),
        fish_hall_multiplier_before=multiplier_before,
        fish_hall_multiplier_after=multiplier_after,
    )
