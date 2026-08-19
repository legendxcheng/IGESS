from __future__ import annotations

from pathlib import Path

from fish_test_support import _snapshot
from igess.behavior import BehaviorProfile
from igess.builder import ModelBuilder
from igess.fish_behavior_weights import ManualThrowRefillRule
from igess.fish_simulator import FishEconomySimulator
from igess.fish_state import FishInstance, PlayerState, TrashStock
from igess.loader import ConfigLoader
from igess.numbers import SimNumber


def _full_hall_state(*, with_trash: bool) -> PlayerState:
    state = PlayerState.new(
        initial_torpedo_id=1,
        initial_strength=50,
        initial_trash_man_realm_id=1,
    )
    state.fish.items = [
        FishInstance(1, 101, 7, 1, 100, 1),
        FishInstance(2, 101, 7, 1, 100, 2),
    ]
    state.fish.next_instance_id = 3
    if with_trash:
        state.trash_man.processing.active_trash_id = 1
        state.trash_man.processing.stocks = [TrashStock(1, 1)]
    return state


def test_manual_throw_refill_weight_uses_or_condition() -> None:
    rule = ManualThrowRefillRule(SimNumber.parse(10))
    base = BehaviorProfile(
        "default",
        {"idle": SimNumber.one(), "manual_throw": SimNumber.one()},
    )

    empty = PlayerState.new(
        initial_torpedo_id=1,
        initial_strength=50,
        initial_trash_man_realm_id=1,
    )
    hall_not_full_with_trash = empty.copy()
    hall_not_full_with_trash.trash_man.processing.active_trash_id = 1
    hall_not_full_with_trash.trash_man.processing.stocks = [TrashStock(1, 1)]
    full_hall_without_trash = _full_hall_state(with_trash=False)
    full_hall_with_trash = _full_hall_state(with_trash=True)

    assert rule.effective_profile(
        empty,
        base,
        fish_hall_capacity=2,
    ).weights["manual_throw"] == SimNumber.parse(10)
    assert rule.effective_profile(
        hall_not_full_with_trash,
        base,
        fish_hall_capacity=2,
    ).weights["manual_throw"] == SimNumber.parse(10)
    assert rule.effective_profile(
        full_hall_without_trash,
        base,
        fish_hall_capacity=2,
    ).weights["manual_throw"] == SimNumber.parse(10)
    assert rule.effective_profile(
        full_hall_with_trash,
        base,
        fish_hall_capacity=2,
    ) is base
    assert base.weights["manual_throw"] == SimNumber.one()


def _run_refill_scenario(
    tmp_path: Path,
    *,
    multiplier: int,
    until_seconds: int | None = None,
    checkpoint=None,
):
    raw = ConfigLoader.load(
        "projects/fish/economy.yaml",
        "projects/fish/luban_exports",
    )
    model = ModelBuilder.build(raw)
    model.scenarios["smoke"].duration_hours = 100 / 3600
    profile = model.player_profiles["default"]
    profile.behavior_weights = {
        "idle": SimNumber.one(),
        "manual_throw": SimNumber.one(),
    }
    profile.behavior_durations = {
        "idle": {"type": "fixed", "seconds": 1},
        "manual_throw": {"type": "fixed", "seconds": 1},
    }
    profile.behavior_target_policies = {}
    model.engine_settings["behavior_scheduler"] = {
        "manual_throw_refill": {"weight_multiplier": str(multiplier)}
    }
    simulator = FishEconomySimulator(
        model,
        _snapshot(tmp_path, trash_duration=1),
        model_digest="sha256:" + (str(multiplier)[0] * 64),
    )
    return simulator.run_scenario(
        "smoke",
        checkpoint,
        until_seconds=until_seconds,
    )


def test_manual_throw_refill_increases_throws_and_replays_checkpoint(
    tmp_path: Path,
) -> None:
    baseline = _run_refill_scenario(
        tmp_path / "baseline",
        multiplier=1,
    )
    boosted = _run_refill_scenario(
        tmp_path / "boosted",
        multiplier=10,
    )
    first = _run_refill_scenario(
        tmp_path / "boosted",
        multiplier=10,
        until_seconds=37,
    )
    resumed = _run_refill_scenario(
        tmp_path / "boosted",
        multiplier=10,
        checkpoint=first.checkpoint,
    )

    assert (
        boosted.checkpoint.event_counters["manual_throw_completed"]
        > baseline.checkpoint.event_counters["manual_throw_completed"]
    )
    assert resumed.checkpoint.engine_state == boosted.checkpoint.engine_state
    assert (
        resumed.checkpoint.behavior_state
        == boosted.checkpoint.behavior_state
    )
    assert (
        resumed.checkpoint.event_counters
        == boosted.checkpoint.event_counters
    )
    assert (
        first.result.timeline + resumed.result.timeline[1:]
        == boosted.result.timeline
    )
