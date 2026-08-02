from __future__ import annotations

from pathlib import Path

from fish_test_support import _snapshot
from igess.fish_hall import FishHallDataAdapter
from igess.fish_state import FishInstance, PlayerState
from igess.numbers import SimNumber


def test_internal_hall_cache_invalidates_on_every_hall_input(
    tmp_path: Path,
) -> None:
    adapter = FishHallDataAdapter(_snapshot(tmp_path))
    state = PlayerState.new(
        initial_torpedo_id=1,
        initial_strength=50,
        initial_trash_man_realm_id=1,
    )
    state.fish.items = [FishInstance(1, 1, 7, 1, 100, 1)]
    state.fish.next_instance_id = 2

    first = adapter.snapshot(state)
    assert adapter.snapshot(state, use_cache=True) is first

    state.fish.items[0].level = 2
    changed_fish = adapter.snapshot(state)
    assert changed_fish is not first
    assert changed_fish.total_income_per_second > (
        first.total_income_per_second
    )
    assert adapter.snapshot(state, use_cache=True) is changed_fish

    state.rebirth.trash_man_completed_count = 1
    changed_rebirth = adapter.snapshot(state, use_cache=True)
    assert changed_rebirth is not changed_fish
    assert changed_rebirth.trash_man_rebirth_multiplier == SimNumber.parse(2)

    state.fish_hall.upgrade_level = 1
    changed_level = adapter.snapshot(state, use_cache=True)
    assert changed_level is not changed_rebirth
    assert changed_level.capacity == 3


def test_incremental_layout_matches_full_ranking_after_appends_and_upgrades(
    tmp_path: Path,
) -> None:
    incremental = FishHallDataAdapter(_snapshot(tmp_path / "incremental"))
    verification = FishHallDataAdapter(_snapshot(tmp_path / "verification"))
    state = PlayerState.new(
        initial_torpedo_id=1,
        initial_strength=50,
        initial_trash_man_realm_id=1,
    )
    assert incremental.snapshot(state) == verification.snapshot(state)

    for instance_id in range(1, 401):
        item = FishInstance(
            instance_id=instance_id,
            fish_id=1 if instance_id % 3 else 2,
            mutation_id=2 if instance_id % 5 == 0 else 7,
            level=1,
            weight_gram=100,
        )
        state.fish.items.append(item)
        state.fish.next_instance_id += 1
        actual = incremental.apply_cached_layout(state)

        if instance_id % 11 == 0:
            changed = state.fish.items[(instance_id * 7) % len(state.fish.items)]
            changed.level += 1
            actual = incremental.apply_cached_layout(
                state,
                changed_item=changed,
            )

        expected = verification.snapshot(state)
        assert actual == expected

    state.rebirth.trash_man_completed_count = 1
    assert incremental.snapshot(
        state,
        use_cache=True,
    ) == verification.snapshot(state)
