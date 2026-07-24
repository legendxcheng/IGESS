from __future__ import annotations

from .fish_command_results import AppliedStrengthRebirth, FishCommandError
from .fish_data import FishDataError
from .fish_hall import FishHallDataAdapter
from .fish_state import BigNumberDTO, PlayerState
from .numbers import SimNumber


def apply_strength_rebirth(
    state: PlayerState,
    *,
    hall_adapter: FishHallDataAdapter,
) -> AppliedStrengthRebirth:
    """Atomically reset strength and earn the next permanent hall multiplier.

    Callers must settle continuous production to the command timestamp before
    invoking this transaction.
    """

    if not isinstance(state, PlayerState):
        raise FishCommandError("state must be a PlayerState")
    if not isinstance(hall_adapter, FishHallDataAdapter):
        raise FishCommandError("hall_adapter must be a FishHallDataAdapter")
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

    fish_hall_before = hall_adapter.snapshot(state)
    committed = state.copy()
    committed.wallet.strength = BigNumberDTO.from_value(
        SimNumber.zero(),
        allow_negative=False,
    )
    committed.rebirth.strength_completed_count = rule.completed_count
    committed.meta.revision += 1
    committed.validate(hall_adapter.validation_context())
    fish_hall_after = hall_adapter.snapshot(committed)
    return AppliedStrengthRebirth(
        state=committed,
        from_completed_count=from_completed_count,
        to_completed_count=rule.completed_count,
        strength_requirement=rule.strength_requirement,
        strength_before=strength_before,
        strength_after=committed.wallet.strength.to_sim_number(),
        fish_hall_before=fish_hall_before,
        fish_hall_after=fish_hall_after,
    )
