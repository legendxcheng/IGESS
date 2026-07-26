from __future__ import annotations

from pathlib import Path

from fish_test_support import _snapshot
from igess.behavior import BehaviorScheduler
from igess.fish_barbell import FishBarbellDataAdapter
from igess.fish_behavior import (
    STRENGTH_REBIRTH_BEHAVIOR_ID,
    TRASH_MAN_REBIRTH_BEHAVIOR_ID,
    FishBehaviorAdapter,
)
from igess.fish_hall import FishHallDataAdapter
from igess.fish_state import PlayerState
from igess.fish_throw_data import (
    FishThrowDataAdapter,
    ProductionThrowConfig,
)
from igess.fish_trash import FishTrashDataAdapter
from igess.loader import ConfigLoader


def _behavior_adapter(snapshot) -> FishBehaviorAdapter:
    throw_config = ProductionThrowConfig.from_mapping(
        {
            "initial_strength": "50",
            "interval_seconds": 1,
            "regular_luck_multiplier": "1",
            "bonus_base_luck": "1",
            "max_bonus_layers": 4,
        }
    )
    return FishBehaviorAdapter(
        throw_adapter=FishThrowDataAdapter(
            snapshot,
            bonus_base_luck=1,
            max_bonus_layers=4,
        ),
        hall_adapter=FishHallDataAdapter(snapshot),
        trash_adapter=FishTrashDataAdapter(snapshot),
        barbell_adapter=FishBarbellDataAdapter(snapshot),
        throw_config=throw_config,
    )


def test_available_rebirths_preempt_every_normal_behavior(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path)
    adapter = _behavior_adapter(snapshot)
    profile = ConfigLoader.load_rules_only(
        "projects/fish/economy.yaml"
    ).rules.player_profiles["default"]
    state = PlayerState.new(
        initial_torpedo_id=1,
        initial_strength=1000,
        initial_trash_man_realm_id=3,
    )
    scheduler = BehaviorScheduler(41)
    behavior_profile = adapter.behavior_profile(profile)

    first_candidates = adapter.candidates(state, profile)
    assert {
        candidate.behavior_id for candidate in first_candidates
    } == {
        STRENGTH_REBIRTH_BEHAVIOR_ID,
        TRASH_MAN_REBIRTH_BEHAVIOR_ID,
    }

    first_decision = scheduler.decide(
        first_candidates,
        behavior_profile,
        sequence_id=0,
        started_at_seconds=0,
    )
    first = adapter.complete(
        state,
        first_decision,
        root_random_seed=41,
        next_throw_id=0,
    )

    second_candidates = adapter.candidates(first.state, profile)
    assert len(second_candidates) == 1
    assert second_candidates[0].behavior_id == (
        {
            STRENGTH_REBIRTH_BEHAVIOR_ID,
            TRASH_MAN_REBIRTH_BEHAVIOR_ID,
        }
        - {first_decision.behavior_id}
    ).pop()

    second_decision = scheduler.decide(
        second_candidates,
        behavior_profile,
        sequence_id=1,
        started_at_seconds=first_decision.completes_at_seconds,
    )
    second = adapter.complete(
        first.state,
        second_decision,
        root_random_seed=41,
        next_throw_id=0,
        production_runtime=first.production_runtime,
    )

    assert second.state.rebirth.strength_completed_count == 1
    assert second.state.rebirth.trash_man_completed_count == 1
    assert {
        first.event_kind,
        second.event_kind,
    } == {"strength_reborn", "trash_man_reborn"}
