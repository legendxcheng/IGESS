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

    assert payload["schema_version"] == 2
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
