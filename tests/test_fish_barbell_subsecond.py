from decimal import Decimal
from pathlib import Path

import pytest

from fish_test_support import _snapshot
from igess.behavior import BehaviorRuntimeState
from igess.builder import ModelBuilder
from igess.fish_barbell import FishBarbellDataAdapter
from igess.fish_behavior_simulator import FishBehaviorSimulator
from igess.fish_data import FishDataError
from igess.fish_hall import FishHallDataAdapter
from igess.fish_production import FishProductionRuntime, settle_fish_production
from igess.fish_rewards import FishRewardMultipliers
from igess.fish_state import FishCheckpointCodec, OwnedBarbell, PlayerState
from igess.fish_trash import FishTrashDataAdapter
from igess.loader import ConfigLoader
from igess.numbers import SimNumber


@pytest.mark.parametrize("duration", [1, 1.0, 0.5, 0.25, 0.001, Decimal("0.125")])
def test_barbell_duration_preserves_millisecond_precision(tmp_path: Path, duration) -> None:
    snapshot = _snapshot(tmp_path)
    snapshot.table("tbbarbell")[0].timeCost = duration
    rule = FishBarbellDataAdapter(snapshot).rule(1)
    assert rule.time_cost_seconds == Decimal(str(duration))
    assert rule.strength_per_second == SimNumber.parse(2) / SimNumber.parse(duration)


@pytest.mark.parametrize("duration", [
    0, -0.5, True, "0.5", None, float("nan"), float("inf"),
    Decimal("sNaN"), 0.0005, 0.5001, 9007199254741,
])
def test_barbell_rejects_invalid_duration(tmp_path: Path, duration) -> None:
    snapshot = _snapshot(tmp_path)
    snapshot.table("tbbarbell")[0].timeCost = duration
    with pytest.raises(FishDataError, match=r"tbbarbell\.1\.timeCost"):
        FishBarbellDataAdapter(snapshot)


@pytest.mark.parametrize("elapsed", [1, 60])
@pytest.mark.parametrize("online,training", [(True, True), (True, False), (False, False)])
@pytest.mark.parametrize("multiplier", ["1", "1.2"])
def test_half_second_repetitions_only_produce_during_online_training(
    tmp_path: Path, elapsed: int, online: bool, training: bool, multiplier: str,
) -> None:
    snapshot = _snapshot(tmp_path)
    row = snapshot.table("tbbarbell")[0]
    row.timeCost, row.strengthPerExercise = 0.5, 1
    state = PlayerState.new(initial_torpedo_id=1, initial_strength=10, initial_trash_man_realm_id=1)
    state.barbell.owned = [OwnedBarbell(1, 3)]
    state.barbell.equipped_id = 1
    settlement = settle_fish_production(
        state, elapsed,
        hall_adapter=FishHallDataAdapter(snapshot),
        trash_adapter=FishTrashDataAdapter(snapshot),
        barbell_adapter=FishBarbellDataAdapter(snapshot),
        online=online, barbell_training_active=training,
        reward_multipliers=FishRewardMultipliers(barbell_strength=SimNumber.parse(multiplier)),
    )
    expected_base = SimNumber.parse(2 * elapsed if training else 0)
    assert settlement.strength_base_added == expected_base
    assert settlement.strength_added == expected_base * SimNumber.parse(multiplier)
    assert settlement.state.wallet.strength.to_sim_number() == 10 + settlement.strength_added.decimal
    assert settlement.event_details()["barbell_time_cost_seconds_before_command"] == "0.5"
    assert state.wallet.strength.to_sim_number() == 10


@pytest.mark.parametrize("mutate", [False, True])
def test_half_second_training_replays_from_mid_behavior_checkpoint(tmp_path: Path, mutate: bool) -> None:
    snapshot = _snapshot(tmp_path)
    row = snapshot.table("tbbarbell")[0]
    row.timeCost, row.strengthPerExercise = 0.5, 1
    model = ModelBuilder.build(ConfigLoader.load("projects/fish/economy.yaml", "projects/fish/luban_exports"))
    model.scenarios["smoke"].duration_hours = 120 / 3600
    model.scenarios["smoke"].record_interval_seconds = 1
    profile = model.player_profiles["default"]
    profile.behavior_weights = {"exercise_barbell": SimNumber.one()}
    profile.behavior_durations = {"exercise_barbell": {"type": "fixed", "seconds": 60}}
    profile.behavior_target_policies = {}
    digest = "sha256:" + "a" * 64
    state = PlayerState.new(initial_torpedo_id=1, initial_strength=10, initial_trash_man_realm_id=1)
    state.barbell.owned = [OwnedBarbell(1, 1)]
    state.barbell.equipped_id = 1
    initial = FishCheckpointCodec.new(
        state, model_digest=digest, scenario_id="smoke", profile_id="default",
        root_random_seed=7, behavior_state=BehaviorRuntimeState().to_dict(),
        engine_runtime_state=FishProductionRuntime().to_dict(),
        context=FishHallDataAdapter(snapshot).validation_context(),
    )

    def simulator():
        return FishBehaviorSimulator(model, snapshot, model_digest=digest, _mutate_state=mutate)

    continuous, expected = simulator().run_scenario("smoke", initial)
    first, checkpoint = simulator().run_scenario("smoke", initial, until_seconds=31)
    assert checkpoint.behavior_state["active"]["completes_at_seconds"] == 60
    assert SimNumber.parse(first.timeline[-1].resources["strength"]) == 72
    # A record/checkpoint boundary does not commit a second production transaction.
    assert checkpoint.engine_state["production"]["lastSettledAt"] == 0
    path = tmp_path / "mid_training.json"
    FishCheckpointCodec.write(checkpoint, path, expected_model_digest=digest)
    restored, _ = FishCheckpointCodec.read(path, expected_model_digest=digest)
    resumed, actual = simulator().run_scenario("smoke", restored)
    assert actual == expected
    assert SimNumber.parse(continuous.timeline[-1].resources["strength"]) == 250
    assert [e for e in first.events + resumed.events if e.kind != "fish_engine_ready"] == [
        e for e in continuous.events if e.kind != "fish_engine_ready"
    ]
    completed = [e for e in continuous.events if e.kind == "barbell_exercise_completed"]
    assert len(completed) == 2
    assert all(e.details["barbell_strength_added"] == "120" for e in completed)
