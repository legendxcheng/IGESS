from __future__ import annotations

import pytest

from igess.behavior import (
    IDLE_BEHAVIOR_ID,
    BehaviorCandidate,
    BehaviorProfile,
    BehaviorRuntimeState,
    BehaviorScheduler,
    BehaviorTarget,
    FixedDuration,
    NoAvailableBehaviorError,
    UniformIntDuration,
)
from igess.numbers import SimNumber


def _profile(**weights: int | str) -> BehaviorProfile:
    return BehaviorProfile(profile_id="casual", weights=weights)


def test_candidates_are_filtered_and_player_weights_are_normalized() -> None:
    scheduler = BehaviorScheduler(root_seed=17)
    candidates = [
        BehaviorCandidate("throw", FixedDuration(4)),
        BehaviorCandidate("upgrade", FixedDuration(2), available=False),
        BehaviorCandidate("shop", FixedDuration(3)),
        BehaviorCandidate(
            "targeted",
            FixedDuration(1),
            targets=(
                BehaviorTarget("locked", weight=10, available=False),
                BehaviorTarget("ignored", weight=0),
            ),
        ),
        BehaviorCandidate.idle(FixedDuration(5)),
    ]

    weighted = scheduler.normalized_candidates(
        candidates,
        _profile(throw=3, upgrade=100, shop=0, targeted=50, idle=1),
    )

    assert [item.candidate.behavior_id for item in weighted] == ["idle", "throw"]
    assert [item.weight for item in weighted] == [
        SimNumber.parse(1),
        SimNumber.parse(3),
    ]
    assert [item.probability for item in weighted] == [
        SimNumber.parse("0.25"),
        SimNumber.parse("0.75"),
    ]


def test_idle_is_a_regular_targetless_behavior() -> None:
    scheduler = BehaviorScheduler(root_seed=1)
    idle = BehaviorCandidate.idle(FixedDuration(7))

    decision = scheduler.decide(
        [idle],
        _profile(idle=1),
        sequence_id=0,
        started_at_seconds=12,
    )

    assert idle.behavior_id == IDLE_BEHAVIOR_ID
    assert decision.behavior_id == "idle"
    assert decision.target_id is None
    assert decision.duration_seconds == 7
    assert decision.started_at_seconds == 12
    assert decision.completes_at_seconds == 19


def test_decision_is_replayable_by_profile_seed_and_sequence_id() -> None:
    scheduler = BehaviorScheduler(root_seed=991)
    profile = _profile(throw=5, upgrade=3, idle=1)
    candidates = [
        BehaviorCandidate(
            "throw",
            UniformIntDuration(2, 8),
            targets=(BehaviorTarget("left"), BehaviorTarget("right")),
        ),
        BehaviorCandidate("upgrade", UniformIntDuration(1, 4)),
        BehaviorCandidate.idle(UniformIntDuration(3, 9)),
    ]

    first = scheduler.decide(
        candidates,
        profile,
        sequence_id=42,
        started_at_seconds=100,
    )
    replay = scheduler.decide(
        list(reversed(candidates)),
        profile,
        sequence_id=42,
        started_at_seconds=100,
    )

    assert replay == first
    assert first.sequence_id == 42
    assert first.profile_id == "casual"
    assert first.completes_at_seconds == 100 + first.duration_seconds


def test_uniform_integer_duration_is_inclusive_and_sequence_driven() -> None:
    scheduler = BehaviorScheduler(root_seed=123)
    profile = _profile(wait=1)
    candidates = [BehaviorCandidate("wait", UniformIntDuration(3, 5))]

    durations = {
        scheduler.decide(
            candidates,
            profile,
            sequence_id=sequence_id,
            started_at_seconds=0,
        ).duration_seconds
        for sequence_id in range(100)
    }

    assert durations == {3, 4, 5}


def test_behavior_duration_and_target_use_independent_random_domains() -> None:
    scheduler = BehaviorScheduler(root_seed=31)
    profile = _profile(play=1)
    candidates = [
        BehaviorCandidate(
            "play",
            UniformIntDuration(1, 2),
            targets=(BehaviorTarget("a"), BehaviorTarget("b")),
        )
    ]

    decisions = [
        scheduler.decide(
            candidates,
            profile,
            sequence_id=sequence_id,
            started_at_seconds=0,
        )
        for sequence_id in range(32)
    ]
    duration_bits = [decision.duration_seconds - 1 for decision in decisions]
    target_bits = [int(decision.target_id == "b") for decision in decisions]

    assert duration_bits != target_bits
    assert {decision.target_id for decision in decisions} == {"a", "b"}


def test_changing_target_pool_does_not_shift_behavior_or_duration_streams() -> None:
    scheduler = BehaviorScheduler(root_seed=2026)
    profile = _profile(play=3, idle=2)
    common = [
        BehaviorCandidate(
            "play",
            UniformIntDuration(2, 12),
            targets=(BehaviorTarget("a"), BehaviorTarget("b")),
        ),
        BehaviorCandidate.idle(UniformIntDuration(2, 12)),
    ]
    changed_targets = [
        BehaviorCandidate(
            "play",
            UniformIntDuration(2, 12),
            targets=(
                BehaviorTarget("a", weight=100),
                BehaviorTarget("b"),
                BehaviorTarget("c"),
            ),
        ),
        common[1],
    ]

    for sequence_id in range(30):
        before = scheduler.decide(
            common,
            profile,
            sequence_id=sequence_id,
            started_at_seconds=0,
        )
        after = scheduler.decide(
            changed_targets,
            profile,
            sequence_id=sequence_id,
            started_at_seconds=0,
        )
        assert after.behavior_id == before.behavior_id
        assert after.duration_seconds == before.duration_seconds


def test_profiles_have_independent_behavior_streams_and_weights() -> None:
    scheduler = BehaviorScheduler(root_seed=44)
    candidates = [
        BehaviorCandidate("throw", FixedDuration(1)),
        BehaviorCandidate("upgrade", FixedDuration(1)),
    ]
    thrower = BehaviorProfile("thrower", {"throw": 1, "upgrade": 0})
    upgrader = BehaviorProfile("upgrader", {"throw": 0, "upgrade": 1})

    assert scheduler.decide(
        candidates,
        thrower,
        sequence_id=8,
        started_at_seconds=0,
    ).behavior_id == "throw"
    assert scheduler.decide(
        candidates,
        upgrader,
        sequence_id=8,
        started_at_seconds=0,
    ).behavior_id == "upgrade"


def test_no_available_positive_weight_behavior_is_explicit() -> None:
    scheduler = BehaviorScheduler(root_seed=0)

    with pytest.raises(NoAvailableBehaviorError, match="no available"):
        scheduler.decide(
            [BehaviorCandidate("locked", FixedDuration(1), available=False)],
            _profile(locked=1),
            sequence_id=0,
            started_at_seconds=0,
        )


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (lambda: FixedDuration(0), "positive integer"),
        (lambda: UniformIntDuration(5, 4), "greater than or equal"),
        (lambda: BehaviorProfile("p", {"idle": -1}), "non-negative"),
        (
            lambda: BehaviorCandidate(
                "play",
                FixedDuration(1),
                targets=(BehaviorTarget("same"), BehaviorTarget("same")),
            ),
            "duplicate target_id",
        ),
    ],
)
def test_invalid_behavior_configuration_is_rejected(factory, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        factory()


def test_duplicate_behavior_ids_are_rejected_before_selection() -> None:
    scheduler = BehaviorScheduler(root_seed=0)

    with pytest.raises(ValueError, match="duplicate behavior_id"):
        scheduler.normalized_candidates(
            [
                BehaviorCandidate("same", FixedDuration(1)),
                BehaviorCandidate("same", FixedDuration(2)),
            ],
            _profile(same=1),
        )


def test_active_behavior_runtime_round_trips_without_reselection() -> None:
    decision = BehaviorScheduler(root_seed=91).decide(
        [BehaviorCandidate("play", UniformIntDuration(4, 9))],
        _profile(play=1),
        sequence_id=6,
        started_at_seconds=20,
    )
    runtime = BehaviorRuntimeState(next_sequence_id=7, active=decision)

    assert BehaviorRuntimeState.from_dict(runtime.to_dict()) == runtime


def test_runtime_cursor_must_follow_active_sequence() -> None:
    decision = BehaviorScheduler(root_seed=1).decide(
        [BehaviorCandidate.idle(FixedDuration(2))],
        _profile(idle=1),
        sequence_id=3,
        started_at_seconds=0,
    )

    with pytest.raises(ValueError, match="immediately follow"):
        BehaviorRuntimeState(next_sequence_id=3, active=decision)
