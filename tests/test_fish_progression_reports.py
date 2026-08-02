from __future__ import annotations

import json
from pathlib import Path

from fish_test_support import _snapshot
from igess.builder import ModelBuilder
from igess.fish_progression_reports import (
    build_core_strength_progression,
    build_persistent_progression,
)
from igess.fish_session import FishDailySessionSchedule
from igess.loader import ConfigLoader
from igess.outputs import OutputWriter
from igess.reporting.loader import load_report_data
from igess.reporting.view_model import build_report_view_model
from igess.schema import Event, SimulationResult, TimelineRow


def _model():
    raw = ConfigLoader.load(
        "projects/fish/economy.yaml",
        "projects/fish/luban_exports",
    )
    return ModelBuilder.build(raw)


def _result() -> SimulationResult:
    events = [
        Event(
            "smoke",
            "default",
            1,
            "barbell_synthesized",
            "barbell:1",
            {
                "barbell_strength_added": "0",
                "barbell_strength_per_second_before_synthesis": "0",
                "barbell_strength_per_second_after_synthesis": "2",
            },
        ),
        Event(
            "smoke",
            "default",
            2,
            "barbell_exercise_completed",
            "barbell:1",
            {"barbell_strength_added": "10"},
        ),
        Event(
            "smoke",
            "default",
            3,
            "fish_throw_resolved",
            "throw:0",
            {
                "barbell_strength_added": "0",
                "fish_hall_cps_before": "0",
                "fish_hall_cps_after": "10",
                "fish_hall_cps_delta": "10",
                "is_persistent_progression": "true",
                "trash_luck": "3",
            },
        ),
        Event(
            "smoke",
            "default",
            4,
            "fish_upgraded",
            "fish:1",
            {
                "barbell_strength_added": "0",
                "fish_income_per_second_before": "10",
                "fish_income_per_second_after": "12.5",
            },
        ),
        Event(
            "smoke",
            "default",
            5,
            "strength_reborn",
            "strength_rebirth:1",
            {
                "barbell_strength_added": "0",
                "strength_before_rebirth": "1000",
                "strength_after_rebirth": "0",
                "strength_rebirth_completed_count_after": "1",
                "strength_rebirth_material_multiplier_before": "1",
                "strength_rebirth_material_multiplier_after": "2",
            },
        ),
    ]
    timeline = [
        TimelineRow(
            "smoke",
            "default",
            time_seconds,
            resources={
                "material": "0",
                "money": "0",
                "strength": "0" if time_seconds == 10 else "50",
            },
            generators_owned={},
            upgrades_purchased=[],
            total_cps="0",
        )
        for time_seconds in (0, 10)
    ]
    return SimulationResult("smoke", timeline, events)


def test_session_schedule_converts_wall_and_active_time() -> None:
    schedule = FishDailySessionSchedule(daily_online_seconds=7200)

    assert schedule.active_seconds_at(0) == 0
    assert schedule.active_seconds_at(7200) == 7200
    assert schedule.active_seconds_at(86399) == 7200
    assert schedule.active_seconds_at(86401) == 7201
    assert schedule.wall_time_for_active_seconds(7200) == 7200
    assert schedule.wall_time_for_active_seconds(7201) == 86401
    assert schedule.wall_time_for_active_seconds(14400) == 93600


def test_core_strength_progression_tracks_peaks_resets_and_stalls(
    tmp_path: Path,
) -> None:
    report = build_core_strength_progression(
        _result(),
        _model(),
        _snapshot(tmp_path),
        sample_interval_active_seconds=2,
    )

    profile = report["profiles"]["default"]
    summary = profile["summary"]
    assert report["time_basis"] == "cumulative_active_seconds"
    assert [row["active_time_seconds"] for row in profile["rows"]] == [
        0,
        1,
        2,
        4,
        5,
        6,
        8,
        10,
    ]
    reset = next(
        row
        for row in profile["rows"]
        if row["reset_or_milestone_marker"] == "strength_reborn"
    )
    assert reset["strength_current"] == "0"
    assert reset["strength_peak"] == "1000"
    assert reset["fish_luck_current"] == "1"
    assert reset["fish_luck_peak"] > reset["fish_luck_current"]
    assert summary["trash_luck_initial"] == "3"
    assert summary["trash_luck_final"] == "3"
    assert summary["longest_trash_luck_stagnation_seconds"] == 10
    assert summary["strength_rebirth_count"] == 1


def test_persistent_progression_excludes_single_fish_upgrades() -> None:
    report = build_persistent_progression(_result(), _model())

    profile = report["profiles"]["default"]
    rows = profile["rows"]
    assert [row["source_event_kind"] for row in rows] == [
        "barbell_synthesized",
        "fish_throw_resolved",
        "strength_reborn",
    ]
    assert all(row["is_persistent"] for row in rows)
    assert [row["gap_from_previous_progression_seconds"] for row in rows] == [
        1,
        2,
        2,
    ]
    summary = profile["summary"]
    assert summary["total_progression_count"] == 3
    assert summary["max_interval_seconds"] == 2
    assert summary["tail_gap_seconds"] == 5
    assert summary["progression_category_diversity"] == 3
    assert summary["system_progression_count"] == 2
    assert summary["system_progression_max_interval_seconds"] == 4
    assert summary["system_progression_tail_gap_seconds"] == 5


def test_output_writer_registers_fish_progression_artifacts(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "output"
    second_output_dir = tmp_path / "second-output"
    model = _model()
    snapshot = _snapshot(tmp_path / "data")
    OutputWriter.write_all(
        _result(),
        output_dir,
        model,
        domain_model=snapshot,
    )
    OutputWriter.write_all(
        _result(),
        second_output_dir,
        model,
        domain_model=snapshot,
    )

    manifest = json.loads(
        (output_dir / "run_manifest.json").read_text(encoding="utf-8")
    )
    for artifact in (
        "behavior_progression.csv",
        "behavior_progression.json",
        "luck_progression.csv",
        "luck_progression.json",
    ):
        assert artifact in manifest["artifacts"]
        assert (output_dir / artifact).exists()
        assert (output_dir / artifact).read_bytes() == (
            second_output_dir / artifact
        ).read_bytes()
    assert "fish_upgraded" not in (
        output_dir / "behavior_progression.csv"
    ).read_text(encoding="utf-8")

    data = load_report_data(output_dir)
    payload = build_report_view_model(data)
    assert payload["fish_progression"]["available"] is True
    assert payload["fish_progression"]["core"]["profiles"]["default"]["rows"]
    assert payload["fish_progression"]["persistent"]["profiles"]["default"][
        "rows"
    ]


def test_week_baseline_reproduces_system_gap_and_trash_luck_stall(
    tmp_path: Path,
) -> None:
    model = _model()
    events = [
        Event(
            "week_1_growth",
            "default",
            1,
            "trash_man_reborn",
            "trash_man_rebirth:1",
            {
                "trash_man_rebirth_fish_hall_multiplier_before": "1",
                "trash_man_rebirth_fish_hall_multiplier_after": "2",
                "trash_man_rebirth_completed_count_after": "1",
            },
        ),
        Event(
            "week_1_growth",
            "default",
            8,
            "barbell_synthesized",
            "barbell:1",
            {
                "barbell_strength_per_second_before_synthesis": "0",
                "barbell_strength_per_second_after_synthesis": "2",
            },
        ),
        Event(
            "week_1_growth",
            "default",
            994,
            "strength_reborn",
            "strength_rebirth:1",
            {
                "strength_before_rebirth": "1000",
                "strength_after_rebirth": "0",
                "strength_rebirth_completed_count_after": "1",
                "strength_rebirth_material_multiplier_before": "1",
                "strength_rebirth_material_multiplier_after": "2",
            },
        ),
        Event(
            "week_1_growth",
            "default",
            1939,
            "barbell_synthesized",
            "barbell:2",
            {
                "barbell_strength_per_second_before_synthesis": "2",
                "barbell_strength_per_second_after_synthesis": "5",
            },
        ),
        Event(
            "week_1_growth",
            "default",
            5757,
            "strength_reborn",
            "strength_rebirth:2",
            {
                "strength_before_rebirth": "10000",
                "strength_after_rebirth": "0",
                "strength_rebirth_completed_count_after": "2",
                "strength_rebirth_material_multiplier_before": "2",
                "strength_rebirth_material_multiplier_after": "3",
            },
        ),
        Event(
            "week_1_growth",
            "default",
            345601,
            "barbell_synthesized",
            "barbell:4",
            {
                "barbell_strength_per_second_before_synthesis": "5",
                "barbell_strength_per_second_after_synthesis": "50",
            },
        ),
        Event(
            "week_1_growth",
            "default",
            345671,
            "strength_reborn",
            "strength_rebirth:3",
            {
                "strength_before_rebirth": "100000",
                "strength_after_rebirth": "0",
                "strength_rebirth_completed_count_after": "3",
                "strength_rebirth_material_multiplier_before": "3",
                "strength_rebirth_material_multiplier_after": "4",
            },
        ),
    ]
    result = SimulationResult(
        "week_1_growth",
        timeline=[],
        events=events,
    )

    behavior = build_persistent_progression(result, model)
    summary = behavior["profiles"]["default"]["summary"]
    assert summary["active_duration_seconds"] == 14 * 3600
    assert summary["system_progression_max_interval_seconds"] == 23044
    assert summary["system_progression_tail_gap_seconds"] == 21529
    assert (
        summary["complete_online_sessions_without_system_progression"]
        == 5
    )

    core = build_core_strength_progression(
        result,
        model,
        _snapshot(tmp_path),
    )
    core_summary = core["profiles"]["default"]["summary"]
    assert core_summary["longest_trash_luck_stagnation_seconds"] == (
        14 * 3600
    )
    assert core_summary["trash_luck_initial"] == "3"
    assert core_summary["trash_luck_final"] == "3"
