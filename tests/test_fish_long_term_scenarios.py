from __future__ import annotations

from pathlib import Path

from fish_test_support import _snapshot
from igess.builder import ModelBuilder
from igess.fish_behavior_simulator import FishBehaviorSimulator
from igess.loader import ConfigLoader


def test_production_growth_scenarios_cover_one_day_and_one_week() -> None:
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
    ).run_scenario("week_1_growth", until_seconds=20)

    trash_rebirth = next(
        event for event in result.events if event.kind == "trash_man_reborn"
    )
    throw = next(
        event for event in result.events if event.kind == "fish_throw_resolved"
    )

    assert "fish_hall_formula_trace_before_throw" in trash_rebirth.details
    assert "fish_hall_formula_trace_before_throw" not in throw.details
    assert {"fish_id", "trash_id", "throw_id"} <= set(throw.details)
