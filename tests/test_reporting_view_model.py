from __future__ import annotations

from pathlib import Path
from typing import Any

from igess.builder import ModelBuilder
from igess.loader import ConfigLoader
from igess.outputs import OutputWriter
from igess.reporting.loader import ReportData, load_report_data
from igess.reporting.view_model import build_report_view_model, chart_point, chart_value
from igess.simulator import Simulator


CONFIG = "examples/shelldiver_v0/economy.yaml"
TABLES = "examples/shelldiver_v0/luban_exports"


def _write_sample_run(tmp_path):
    model = ModelBuilder.build(ConfigLoader.load(CONFIG, TABLES))
    result = Simulator(model).run_scenario("day_1_progression")
    run_dir = tmp_path / "run"
    OutputWriter.write_all(result, run_dir, model)
    return run_dir


def _assert_numeric_point(point: dict[str, Any], exact: str) -> None:
    assert set(point) == {"exact_value", "display_value", "chart_value"}
    assert point["exact_value"] == exact


def _synthetic_report_data(tmp_path: Path) -> ReportData:
    return ReportData(
        run_dir=tmp_path,
        manifest={
            "scenario_id": "fixture",
            "model_id": "model",
            "model_digest": "sha256:fixture",
            "profiles": ["beta", "alpha"],
        },
        timeline=[
            {
                "profile_id": "alpha",
                "time_seconds": 3,
                "resources": {"gold": "1000000", "huge": "1e309"},
                "total_cps": "Infinity",
            },
            {
                "profile_id": "beta",
                "time_seconds": 5,
                "resources": {"gold": "2", "huge": "3"},
                "total_cps": "2.5",
            },
        ],
        events=[
            {
                "profile_id": "alpha",
                "time_seconds": 2,
                "kind": "unlock_activity",
                "item_id": "gather",
            },
            {
                "profile_id": "beta",
                "time_seconds": 4,
                "kind": "buy_generator",
                "item_id": "mine",
            },
        ],
        analysis={
            "invalid_content_report": {
                "never_purchased": ["generator:quarry"],
                "never_unlocked": [],
            },
            "overpowered_content_report": [],
            "bottleneck_report": {},
        },
        payback_rows=[
            {
                "profile_id": "alpha",
                "kind": "generator",
                "item_id": "mine",
                "cost": "1e309",
                "delta_cps": "2.5",
                "payback_seconds": "Infinity",
                "source_ref": "generators:mine",
            }
        ],
        missing_artifacts=[],
    )


def test_build_report_view_model_contains_chart_ready_sections(tmp_path):
    data = load_report_data(_write_sample_run(tmp_path))

    payload = build_report_view_model(data)

    assert payload["schema_version"] == 5
    assert payload["scenario"]["id"] == "day_1_progression"
    assert payload["scenario"]["profiles"] == ["casual", "explorer", "optimizer"]
    assert payload["series"]["resources"]
    assert payload["series"]["total_cps"]
    assert payload["series"]["events"]
    assert payload["diagnostics"]["payback"]
    assert "timeline.json" in payload["artifacts"]["timeline"]


def test_report_view_model_wraps_every_human_numeric_field(tmp_path):
    payload = build_report_view_model(_synthetic_report_data(tmp_path))

    assert payload["scenario"]["model_digest"] == "sha256:fixture"

    overview = payload["overview"]
    for field, exact in {
        "duration_seconds": "5",
        "timeline_rows": "2",
        "event_count": "2",
        "purchase_count": "1",
        "prestige_reset_count": "0",
        "never_purchased_count": "1",
        "never_unlocked_count": "0",
        "warning_category_count": "2",
    }.items():
        _assert_numeric_point(overview[field], exact)

    _assert_numeric_point(overview["first_key_unlock"]["time_seconds"], "2")
    _assert_numeric_point(overview["final_resources"]["alpha"]["gold"], "1000000")
    assert overview["final_resources"]["alpha"]["gold"]["display_value"] == "1e6"
    _assert_numeric_point(overview["final_resources"]["alpha"]["huge"], "1e309")
    assert overview["final_resources"]["alpha"]["huge"]["chart_value"] is None

    worst = overview["worst_payback"]
    _assert_numeric_point(worst["payback_seconds"], "Infinity")
    _assert_numeric_point(worst["cost"], "1e309")
    _assert_numeric_point(worst["delta_cps"], "2.5")
    assert worst["payback_seconds"]["chart_value"] is None
    assert worst["payback_seconds"]["display_value"] == "Infinity"

    for row in payload["series"]["resources"]:
        _assert_numeric_point(row["time"], str(row["time_seconds"]))
        _assert_numeric_point(
            {key: row[key] for key in ("exact_value", "display_value", "chart_value")},
            row["exact_value"],
        )
    for row in payload["series"]["total_cps"]:
        _assert_numeric_point(row["time"], str(row["time_seconds"]))
        _assert_numeric_point(
            {key: row[key] for key in ("exact_value", "display_value", "chart_value")},
            row["exact_value"],
        )
    for row in payload["series"]["events"]:
        _assert_numeric_point(row["time"], str(row["time_seconds"]))

    payback = payload["diagnostics"]["payback"][0]
    for field, exact in {
        "payback_seconds": "Infinity",
        "cost": "1e309",
        "delta_cps": "2.5",
    }.items():
        _assert_numeric_point(payback[field], exact)


def test_report_view_model_preserves_profile_order_and_resource_controls(tmp_path):
    payload = build_report_view_model(_synthetic_report_data(tmp_path))

    assert payload["overview"]["profiles"] == ["beta", "alpha"]
    assert payload["overview"]["resource_ids"] == ["gold", "huge"]
    assert list(payload["overview"]["final_resources"]) == ["beta", "alpha"]


def test_fish_balance_curves_use_online_gross_output_and_daily_growth(
    tmp_path: Path,
) -> None:
    data = ReportData(
        run_dir=tmp_path,
        manifest={
            "scenario_id": "fish_fixture",
            "model_id": "fish",
            "profiles": ["default"],
            "strategy": {
                "parameters": {
                    "behavior_scheduler": {
                        "profiles": {
                            "default": {
                                "session": {"daily_online_seconds": 300}
                            }
                        }
                    }
                }
            },
        },
        timeline=[
            {
                "profile_id": "default",
                "time_seconds": 0,
                "resources": {"money": "0", "material": "0"},
                "total_cps": "0",
            }
        ],
        events=[
            {
                "profile_id": "default",
                "time_seconds": 60,
                "kind": "fish_throw_resolved",
                "item_id": "throw:0",
                "details": {
                    "trash_id": "1",
                    "fish_hall_money_added": "600",
                    "trash_material_added": "30",
                },
            },
            {
                "profile_id": "default",
                "time_seconds": 500,
                "kind": "fish_offline_settled",
                "item_id": "offline:0",
                "details": {
                    "fish_hall_money_added": "999999",
                    "trash_material_added": "999999",
                },
            },
            {
                "profile_id": "default",
                "time_seconds": 86460,
                "kind": "fish_throw_resolved",
                "item_id": "throw:1",
                "details": {
                    "trash_id": "2",
                    "fish_hall_money_added": "1200",
                    "trash_material_added": "300",
                },
            },
        ],
        analysis={
            "invalid_content_report": {},
            "overpowered_content_report": [],
            "bottleneck_report": {},
        },
        payback_rows=[],
        missing_artifacts=[],
        luck_progression={
            "time_basis": "cumulative_active_seconds",
            "sample_interval_active_seconds": 300,
            "profiles": {
                "default": {
                    "summary": {"active_duration_seconds": 600},
                    "rows": [
                        {
                            "active_time_seconds": 0,
                            "wall_time_seconds": 0,
                            "fish_luck_current": "3",
                            "fish_luck_peak": "3",
                            "trash_luck_current": "3",
                            "trash_luck_peak": "3",
                        }
                    ],
                }
            },
        },
        behavior_progression={
            "time_basis": "cumulative_active_seconds",
            "profiles": {
                "default": {
                    "summary": {},
                    "rows": [
                        {
                            "active_time_seconds": 120,
                            "wall_time_seconds": 120,
                            "stage_id": "online_day_1",
                            "source_event_kind": "fish_throw_resolved",
                            "progression_category": "best_hall_fish",
                            "item_id": "throw:0",
                            "metric_id": "fish_hall_cps",
                            "metric_before": "0",
                            "metric_after": "2",
                            "metric_delta": "2",
                            "relative_delta": "2",
                            "gap_from_previous_progression_seconds": 120,
                        },
                        {
                            "active_time_seconds": 360,
                            "wall_time_seconds": 86460,
                            "stage_id": "online_day_2",
                            "source_event_kind": "torpedo_purchased",
                            "progression_category": "torpedo",
                            "item_id": "torpedo:2",
                            "metric_id": "trash_luck",
                            "metric_before": "3",
                            "metric_after": "4",
                            "metric_delta": "1",
                            "relative_delta": "0.3333333333333333",
                            "gap_from_previous_progression_seconds": 240,
                        },
                    ],
                }
            },
        },
    )

    fish = build_report_view_model(data)["fish_progression"]

    balance = fish["balance"]["profiles"]["default"]
    assert fish["balance"]["rate_definition"] == (
        "online_gross_acquisition_per_active_sample_window"
    )
    assert [row["active_time_seconds"] for row in balance["rate_rows"]] == [
        300,
        600,
    ]
    assert balance["rate_rows"][0]["resource_per_second"][
        "exact_value"
    ] == "0.1"
    assert balance["rate_rows"][0]["resource_acquired"][
        "exact_value"
    ] == "30"
    assert balance["rate_rows"][0]["money_per_second"]["exact_value"] == "2"
    assert balance["cumulative_rows"][-1]["money_acquired_cumulative"][
        "exact_value"
    ] == "1800"
    assert balance["cumulative_rows"][-1]["resource_acquired_cumulative"][
        "exact_value"
    ] == "330"

    days = fish["persistent"]["profiles"]["default"]["days"]
    assert [day["day_index"] for day in days] == [1, 2]
    assert [day["event_count"]["exact_value"] for day in days] == ["1", "1"]
    assert days[0]["rows"][0]["day_active_time_seconds"] == 120
    assert days[1]["rows"][0]["day_active_time_seconds"] == 60


def test_fish_progression_groups_each_seven_online_days_into_a_week(
    tmp_path: Path,
) -> None:
    data = ReportData(
        run_dir=tmp_path,
        manifest={
            "scenario_id": "fish_fixture",
            "model_id": "fish",
            "profiles": ["default"],
            "strategy": {
                "parameters": {
                    "behavior_scheduler": {
                        "profiles": {
                            "default": {
                                "session": {"daily_online_seconds": 100}
                            }
                        }
                    }
                }
            },
        },
        timeline=[],
        events=[],
        analysis={},
        payback_rows=[],
        missing_artifacts=[],
        luck_progression={
            "profiles": {
                "default": {
                    "summary": {"active_duration_seconds": 750},
                    "rows": [],
                }
            }
        },
        behavior_progression={
            "profiles": {
                "default": {
                    "summary": {},
                    "rows": [
                        {
                            "active_time_seconds": 50,
                            "stage_id": "online_day_1",
                            "progression_category": "best_hall_fish",
                        },
                        {
                            "active_time_seconds": 700,
                            "stage_id": "online_day_7",
                            "progression_category": "barbell",
                        },
                        {
                            "active_time_seconds": 725,
                            "stage_id": "online_day_8",
                            "progression_category": "torpedo",
                        },
                    ],
                }
            }
        },
    )

    profile = build_report_view_model(data)["fish_progression"]["persistent"][
        "profiles"
    ]["default"]

    assert [week["week_index"] for week in profile["weeks"]] == [1, 2]
    assert [week["duration_seconds"]["exact_value"] for week in profile["weeks"]] == [
        "700",
        "50",
    ]
    assert [week["event_count"]["exact_value"] for week in profile["weeks"]] == [
        "2",
        "1",
    ]
    assert [
        row["week_active_time_seconds"]
        for week in profile["weeks"]
        for row in week["rows"]
    ] == [50, 700, 25]


def test_report_view_model_wraps_sorted_bottleneck_gap_counts(tmp_path):
    data = _synthetic_report_data(tmp_path)
    data.analysis["bottleneck_report"] = {
        "z<profile>": [{"duration": 1}, {"duration": 2}],
        "a&profile": [{"duration": 3}],
    }

    diagnostics = build_report_view_model(data)["diagnostics"]

    assert list(diagnostics["bottleneck_gap_counts"]) == ["a&profile", "z<profile>"]
    _assert_numeric_point(diagnostics["bottleneck_gap_counts"]["a&profile"], "1")
    _assert_numeric_point(diagnostics["bottleneck_gap_counts"]["z<profile>"], "2")
    assert diagnostics["bottlenecks"] == data.analysis["bottleneck_report"]


def test_chart_value_preserves_display_for_unplottable_values():
    assert chart_value("Infinity") is None
    assert chart_value("1e309") is None
    assert chart_point("Infinity") == {
        "exact_value": "Infinity",
        "display_value": "Infinity",
        "chart_value": None,
    }
    assert chart_point("1e309") == {
        "exact_value": "1e309",
        "display_value": "1e309",
        "chart_value": None,
    }


def test_chart_value_accepts_finite_decimal_strings():
    assert chart_value("123.5") == 123.5


def test_chart_value_rejects_nonzero_values_that_underflow_to_float_zero():
    assert chart_value("1e-400") is None
    assert chart_value("-1e-400") is None


def test_chart_value_keeps_exact_zero_plottable():
    assert chart_value("0") == 0.0
    assert chart_value("-0") == 0.0
