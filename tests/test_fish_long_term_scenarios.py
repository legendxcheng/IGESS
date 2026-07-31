from __future__ import annotations

from pathlib import Path

from fish_test_support import _snapshot
from igess import fish_state_validation
from igess.builder import ModelBuilder
from igess.fish_behavior import (
    EXERCISE_BARBELL_BEHAVIOR_ID,
    FUND_TRASH_MAN_BREAKTHROUGH_BEHAVIOR_ID,
    MANUAL_THROW_BEHAVIOR_ID,
)
from igess.fish_behavior_simulator import FishBehaviorSimulator
from igess.loader import ConfigLoader
from igess.numbers import SimNumber


def test_production_growth_scenarios_cover_day_week_and_month() -> None:
    rules = ConfigLoader.load_rules_only(
        "projects/fish/economy.yaml"
    ).rules

    day = rules.scenarios["day_1_growth"]
    assert day.duration_hours == 24
    assert day.record_interval_seconds == 3600
    assert day.profiles == ["default"]
    assert day.start_state == "new_player"

    week = rules.scenarios["week_1_growth"]
    assert week.duration_hours == 168
    assert week.record_interval_seconds == 86400
    assert week.profiles == ["default"]
    assert week.start_state == "new_player"
    assert "compact_event_details" in week.outputs

    month = rules.scenarios["month_1_growth"]
    assert month.duration_hours == 720
    assert month.record_interval_seconds == 86400
    assert month.profiles == ["default"]
    assert month.start_state == "new_player"
    assert "compact_event_details" in month.outputs

    profile = rules.player_profiles["default"]
    assert profile.behavior_weights[
        FUND_TRASH_MAN_BREAKTHROUGH_BEHAVIOR_ID
    ] == SimNumber.parse("1e100")
    assert profile.behavior_durations[
        FUND_TRASH_MAN_BREAKTHROUGH_BEHAVIOR_ID
    ] == {"type": "fixed", "seconds": 10}
    assert profile.behavior_durations[
        EXERCISE_BARBELL_BEHAVIOR_ID
    ] == {"type": "fixed", "seconds": 60}


def test_owned_state_mutation_matches_copy_on_commit(
    tmp_path: Path,
) -> None:
    raw = ConfigLoader.load(
        "projects/fish/economy.yaml",
        "projects/fish/luban_exports",
    )
    model = ModelBuilder.build(raw)
    model.scenarios["smoke"].duration_hours = 100 / 3600
    model_digest = "sha256:" + ("9" * 64)

    copied_result, copied_checkpoint = FishBehaviorSimulator(
        model,
        _snapshot(tmp_path / "copied"),
        model_digest=model_digest,
        _mutate_state=False,
    ).run_scenario("smoke")
    owned_result, owned_checkpoint = FishBehaviorSimulator(
        model,
        _snapshot(tmp_path / "owned"),
        model_digest=model_digest,
        _mutate_state=True,
    ).run_scenario("smoke")

    assert owned_result == copied_result
    assert owned_checkpoint == copied_checkpoint


def test_owned_state_full_validation_stays_at_scenario_boundaries(
    tmp_path: Path,
    monkeypatch,
) -> None:
    raw = ConfigLoader.load(
        "projects/fish/economy.yaml",
        "projects/fish/luban_exports",
    )
    model = ModelBuilder.build(raw)
    model.scenarios["smoke"].duration_hours = 8 / 3600
    profile = model.player_profiles["default"]
    profile.behavior_weights = {MANUAL_THROW_BEHAVIOR_ID: SimNumber.one()}
    profile.behavior_durations = {
        MANUAL_THROW_BEHAVIOR_ID: {"type": "fixed", "seconds": 1}
    }
    validated_fish_counts: list[int] = []
    original = fish_state_validation.validate_player_state

    def track_validation(state, *, context=None) -> None:
        validated_fish_counts.append(len(state.fish.items))
        original(state, context=context)

    monkeypatch.setattr(
        fish_state_validation,
        "validate_player_state",
        track_validation,
    )
    simulator = FishBehaviorSimulator(
        model,
        _snapshot(tmp_path),
        model_digest="sha256:" + ("7" * 64),
    )
    _first_result, first_checkpoint = simulator.run_scenario(
        "smoke",
        until_seconds=4,
    )
    _result, checkpoint = simulator.run_scenario(
        "smoke",
        first_checkpoint,
    )

    assert checkpoint.next_throw_id == 8
    assert validated_fish_counts == [0, 0, 4, 4, 8]


def test_week_scenario_compacts_ordinary_events_but_keeps_rebirth_trace(
    tmp_path: Path,
) -> None:
    raw = ConfigLoader.load(
        "projects/fish/economy.yaml",
        "projects/fish/luban_exports",
    )
    model = ModelBuilder.build(raw)
    result, _checkpoint = FishBehaviorSimulator(
        model,
        _snapshot(tmp_path),
        model_digest="sha256:" + ("8" * 64),
    ).run_scenario("week_1_growth", until_seconds=40)

    trash_rebirth = next(
        event for event in result.events if event.kind == "trash_man_reborn"
    )
    throw = next(
        event for event in result.events if event.kind == "fish_throw_resolved"
    )

    assert "fish_hall_formula_trace_before_throw" in trash_rebirth.details
    assert "fish_hall_formula_trace_before_throw" not in throw.details
    assert {"fish_id", "trash_id", "throw_id"} <= set(throw.details)
