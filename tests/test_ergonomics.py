import subprocess
import sys

from igess.builder import ModelBuilder
from igess.doctor import run_doctor
from igess.explain import explain_event
from igess.loader import ConfigLoader
from igess.outputs import OutputWriter
from igess.simulator import Simulator
from igess.templates import init_project


CONFIG = "examples/shelldiver_v0/economy.yaml"
TABLES = "examples/shelldiver_v0/luban_exports"


def _write_sample_run(tmp_path):
    model = ModelBuilder.build(ConfigLoader.load(CONFIG, TABLES))
    result = Simulator(model).run_scenario("day_1_progression")
    run_dir = tmp_path / "run"
    OutputWriter.write_all(result, run_dir, model)
    return run_dir


def test_doctor_reports_actionable_sample_project_status():
    report = run_doctor(".", CONFIG, TABLES)

    assert report.ok
    assert any(check["name"] == "config_exists" for check in report.checks)
    assert any(check["name"] == "lint" and check["status"] == "ok" for check in report.checks)
    assert "Config OK" in report.summary


def test_explain_event_returns_source_and_trace(tmp_path):
    run_dir = _write_sample_run(tmp_path)

    explanation = explain_event(run_dir, "0")

    assert explanation["event_index"] == 0
    assert explanation["kind"].startswith("unlock_")
    assert "source" in explanation


def test_init_project_copies_usable_sample(tmp_path):
    target = tmp_path / "new_project"

    created = init_project("incremental-basic", target)

    assert created == target
    assert (target / "economy.yaml").exists()
    assert (target / "luban_exports" / "generators.json").exists()
    report = run_doctor(target, target / "economy.yaml", target / "luban_exports")
    assert report.ok


def test_cli_doctor_explain_and_init(tmp_path):
    run_dir = _write_sample_run(tmp_path)
    target = tmp_path / "cli_project"

    init_result = subprocess.run(
        [sys.executable, "-m", "igess.cli", "init", "--out", str(target)],
        check=False,
        capture_output=True,
        text=True,
    )
    doctor_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "igess.cli",
            "doctor",
            "--project",
            str(target),
            "--config",
            str(target / "economy.yaml"),
            "--tables",
            str(target / "luban_exports"),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    explain_result = subprocess.run(
        [sys.executable, "-m", "igess.cli", "explain", "--run", str(run_dir), "--event", "0"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert init_result.returncode == 0, init_result.stderr
    assert doctor_result.returncode == 0, doctor_result.stderr
    assert explain_result.returncode == 0, explain_result.stderr
    assert "Initialized IGESS project" in init_result.stdout
    assert "Config OK" in doctor_result.stdout
    assert "Event 0" in explain_result.stdout
