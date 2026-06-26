import json
import subprocess
import sys

from igess.builder import ModelBuilder
from igess.loader import ConfigLoader
from igess.outputs import OutputWriter
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

    OutputWriter.write_all(first, tmp_path, model)
    json_bytes_1 = (tmp_path / "timeline.json").read_bytes()
    analysis_bytes_1 = (tmp_path / "analysis.json").read_bytes()
    payback_bytes_1 = (tmp_path / "payback.csv").read_bytes()
    OutputWriter.write_all(second, tmp_path, model)
    json_bytes_2 = (tmp_path / "timeline.json").read_bytes()
    analysis_bytes_2 = (tmp_path / "analysis.json").read_bytes()
    payback_bytes_2 = (tmp_path / "payback.csv").read_bytes()

    assert json_bytes_1 == json_bytes_2
    assert analysis_bytes_1 == analysis_bytes_2
    assert payback_bytes_1 == payback_bytes_2
    legacy_output = tmp_path / "legacy"
    OutputWriter.write_all(first, legacy_output)
    legacy_analysis = json.loads((legacy_output / "analysis.json").read_text(encoding="utf-8"))
    assert legacy_analysis["payback_report"] == []
    assert (tmp_path / "timeline.csv").exists()
    events = json.loads((tmp_path / "events.json").read_text(encoding="utf-8"))
    event_kinds = {event["kind"] for event in events}
    assert {"buy_generator", "unlock_generator", "prestige_reset"}.issubset(event_kinds)
    assert (tmp_path / "events.csv").exists()
    analysis_json = json.loads((tmp_path / "analysis.json").read_text(encoding="utf-8"))
    assert analysis_json["scenario_id"] == "day_1_progression"
    assert analysis_json["profile_summaries"]["casual"]["purchase_count"] > 0
    assert "bottleneck_report" in analysis_json
    assert "invalid_content_report" in analysis_json
    assert "overpowered_content_report" in analysis_json
    assert (tmp_path / "payback.csv").exists()
    payback_csv = (tmp_path / "payback.csv").read_text(encoding="utf-8")
    assert "profile_id,kind,item_id,cost,delta_cps,payback_seconds" in payback_csv
    assert "fisherman" in payback_csv
    report = (tmp_path / "analysis.md").read_text(encoding="utf-8")
    assert "# Incremental Economy Analysis" in report
    assert "## Purchase Timeline" in report
    assert "## Unlock Timeline" in report
    assert "## Prestige Timeline" in report
    assert "## Bottleneck Report" in report
    assert "## Payback Report" in report
    assert "## Invalid Content Report" in report
    assert "## Overpowered Content Report" in report
    assert "generator `fisherman`" in report
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
