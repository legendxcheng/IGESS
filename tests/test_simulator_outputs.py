import json
import subprocess
import sys

from igess.builder import ModelBuilder
from igess.loader import ConfigLoader
from igess.outputs import OutputWriter
from igess.schema import SimulationState
from igess.simulator import Simulator


CONFIG = "examples/shelldiver_v0/economy.yaml"
TABLES = "examples/shelldiver_v0/luban_exports"


def test_simulator_runs_all_profiles_deterministically(tmp_path):
    model = ModelBuilder.build(ConfigLoader.load(CONFIG, TABLES))
    first = Simulator(model).run_scenario("day_1_progression")
    second = Simulator(model).run_scenario("day_1_progression")

    assert [row.to_ordered_dict() for row in first.timeline] == [
        row.to_ordered_dict() for row in second.timeline
    ]
    assert {row.profile_id for row in first.timeline} == {
        "casual",
        "optimizer",
        "explorer",
    }
    assert first.events

    first_output = tmp_path / "first"
    second_output = tmp_path / "second"
    OutputWriter.write_all(first, first_output, model)
    OutputWriter.write_all(second, second_output, model)
    artifacts = [
        "timeline.json",
        "timeline.csv",
        "events.json",
        "events.csv",
        "analysis.json",
        "payback.csv",
        "analysis.md",
    ]
    for artifact in artifacts:
        first_bytes = (first_output / artifact).read_bytes()
        second_bytes = (second_output / artifact).read_bytes()
        assert first_bytes == second_bytes, artifact
        assert b"\r\n" not in first_bytes, artifact
    json_bytes_1 = (first_output / "timeline.json").read_bytes()
    json_bytes_2 = (second_output / "timeline.json").read_bytes()
    assert json_bytes_1 == json_bytes_2
    legacy_output = tmp_path / "legacy"
    OutputWriter.write_all(first, legacy_output)
    legacy_analysis = json.loads((legacy_output / "analysis.json").read_text(encoding="utf-8"))
    assert legacy_analysis["payback_report"] == []
    assert (first_output / "timeline.csv").exists()
    events = json.loads((first_output / "events.json").read_text(encoding="utf-8"))
    event_kinds = {event["kind"] for event in events}
    assert {"buy_generator", "unlock_generator", "prestige_reset"}.issubset(event_kinds)
    buy_fisherman = next(
        event
        for event in events
        if event["kind"] == "buy_generator" and event["item_id"] == "fisherman"
    )
    assert buy_fisherman["details"]["source_table"] == "generators"
    assert buy_fisherman["details"]["source_workbook"] == "generators.xlsx"
    assert buy_fisherman["details"]["source_row"] == "4"
    assert buy_fisherman["details"]["formula_trace"] == (
        "cost=exponential_cost(base_cost=10,growth=1.15,owned=0);"
        "output=generator_output(base_output=1,owned=1,multiplier=1)"
    )
    assert (first_output / "events.csv").exists()
    analysis_json = json.loads((first_output / "analysis.json").read_text(encoding="utf-8"))
    assert analysis_json["scenario_id"] == "day_1_progression"
    assert analysis_json["profile_summaries"]["casual"]["purchase_count"] > 0
    assert "bottleneck_report" in analysis_json
    assert "invalid_content_report" in analysis_json
    assert "overpowered_content_report" in analysis_json
    assert (first_output / "payback.csv").exists()
    payback_csv = (first_output / "payback.csv").read_text(encoding="utf-8")
    assert (
        "profile_id,kind,item_id,cost,delta_cps,payback_seconds,"
        "source_table,source_workbook,source_row,source_ref,formula_trace"
    ) in payback_csv
    assert "fisherman" in payback_csv
    report = (first_output / "analysis.md").read_text(encoding="utf-8")
    assert "# Incremental Economy Analysis" in report
    assert "## Purchase Timeline" in report
    assert "## Unlock Timeline" in report
    assert "## Prestige Timeline" in report
    assert "## Bottleneck Report" in report
    assert "## Payback Report" in report
    assert "## Invalid Content Report" in report
    assert "## Overpowered Content Report" in report
    assert "generator `fisherman`" in report
    assert "source `generators.xlsx:4`" in report
    assert "Never purchased" in report
    assert "purchase share" in report
    assert "casual" in report


def test_cli_lint_and_run_smoke(tmp_path):
    lint_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "igess.cli",
            "lint",
            "--config",
            CONFIG,
            "--tables",
            TABLES,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert lint_result.returncode == 0, lint_result.stderr

    run_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "igess.cli",
            "run",
            "--config",
            CONFIG,
            "--tables",
            TABLES,
            "--scenario",
            "day_1_progression",
            "--out",
            str(tmp_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert run_result.returncode == 0, run_result.stderr

    data = json.loads((tmp_path / "timeline.json").read_text(encoding="utf-8"))
    assert data[0]["scenario_id"] == "day_1_progression"
    assert "prestige_point" in data[0]["resources"]
    analysis = json.loads((tmp_path / "analysis.json").read_text(encoding="utf-8"))
    assert analysis["payback_report"]
    assert (tmp_path / "payback.csv").read_text(encoding="utf-8").count("\n") > 1


def test_timeline_total_cps_uses_profile_source_efficiency():
    model = ModelBuilder.build(ConfigLoader.load(CONFIG, TABLES))
    state = SimulationState.new(model)
    state.generators_owned["fisherman"] = 1
    simulator = Simulator(model)

    casual = simulator._timeline_row("synthetic", "casual", 10, state)
    optimizer = simulator._timeline_row("synthetic", "optimizer", 10, state)

    assert casual.total_cps == "0.9"
    assert optimizer.total_cps == "1.05"


def test_analytic_scenario_jumps_between_events_and_records():
    model = ModelBuilder.build(ConfigLoader.load(CONFIG, TABLES))
    assert model.scenarios["analytic_smoke"].time_mode == "analytic"
    result = Simulator(model).run_scenario("analytic_smoke")

    assert result.timeline[0].time_seconds == 0
    assert result.timeline[-1].time_seconds == 180
    assert {row.profile_id for row in result.timeline} == {"optimizer"}
    assert any(event.kind == "buy_generator" for event in result.events)
    assert all(0 <= event.time_seconds <= 180 for event in result.events)


def test_analytic_mode_does_not_skip_prestige_threshold():
    raw = ConfigLoader.load(CONFIG, TABLES)
    raw.rules.scenarios["day_1_progression"].time_mode = "analytic"
    model = ModelBuilder.build(raw)
    result = Simulator(model).run_scenario("day_1_progression")

    assert any(event.kind == "prestige_reset" for event in result.events)
