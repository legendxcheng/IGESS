from igess.builder import ModelBuilder
from igess.loader import ConfigLoader
from igess.outputs import OutputWriter
from igess.reporting.loader import load_report_data
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


def test_build_report_view_model_contains_chart_ready_sections(tmp_path):
    data = load_report_data(_write_sample_run(tmp_path))

    payload = build_report_view_model(data)

    assert payload["schema_version"] == 1
    assert payload["scenario"]["id"] == "day_1_progression"
    assert payload["scenario"]["profiles"] == ["casual", "explorer", "optimizer"]
    assert payload["series"]["resources"]
    assert payload["series"]["total_cps"]
    assert payload["series"]["events"]
    assert payload["diagnostics"]["payback"]
    assert "timeline.json" in payload["artifacts"]["timeline"]


def test_chart_value_preserves_display_for_unplottable_values():
    assert chart_value("Infinity") is None
    assert chart_value("1e309") is None
    assert chart_point("Infinity") == {
        "display_value": "Infinity",
        "chart_value": None,
    }


def test_chart_value_accepts_finite_decimal_strings():
    assert chart_value("123.5") == 123.5
