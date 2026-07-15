from __future__ import annotations

import subprocess
import sys
from pathlib import Path


CONFIG = "examples/shelldiver_v0/economy.yaml"
TABLES = "examples/shelldiver_v0/luban_exports"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "igess.cli", *args],
        check=False,
        capture_output=True,
        text=True,
    )


def assert_path_error(
    result: subprocess.CompletedProcess[str], role: str, supplied_path: Path
) -> None:
    assert result.returncode == 1
    assert result.stderr.strip() == f"igess: {role} not found: {supplied_path}"
    assert "Traceback" not in result.stderr


def test_lint_names_missing_config_file(tmp_path):
    missing = tmp_path / "missing-economy.yaml"

    result = run_cli(
        "lint",
        "--config",
        str(missing),
        "--tables",
        TABLES,
    )

    assert_path_error(result, "config file", missing)


def test_export_names_missing_source_workbook_directory(tmp_path):
    missing = tmp_path / "missing-datas"

    result = run_cli(
        "export-tables",
        "--datas",
        str(missing),
        "--out",
        str(tmp_path / "exports"),
    )

    assert_path_error(result, "source workbook directory", missing)


def test_run_names_missing_runtime_export_directory(tmp_path):
    missing = tmp_path / "missing-exports"

    result = run_cli(
        "run",
        "--config",
        CONFIG,
        "--tables",
        str(missing),
        "--scenario",
        "analytic_smoke",
        "--out",
        str(tmp_path / "run"),
    )

    assert_path_error(result, "runtime export directory", missing)


def test_report_names_missing_run_directory(tmp_path):
    missing = tmp_path / "missing-run"

    result = run_cli(
        "report",
        "--run",
        str(missing),
        "--out",
        str(tmp_path / "report"),
    )

    assert_path_error(result, "run directory", missing)


def test_review_proposal_names_missing_proposal_file(tmp_path):
    missing = tmp_path / "missing-proposal.json"

    result = run_cli(
        "review-proposal",
        "--proposal",
        str(missing),
        "--out",
        str(tmp_path / "review"),
    )

    assert_path_error(result, "proposal file", missing)


def test_advise_names_missing_optional_baseline_when_supplied(tmp_path):
    missing = tmp_path / "missing-baseline"

    result = run_cli(
        "advise",
        "--config",
        CONFIG,
        "--tables",
        TABLES,
        "--scenario",
        "analytic_smoke",
        "--baseline",
        str(missing),
        "--out",
        str(tmp_path / "advice"),
    )

    assert_path_error(result, "baseline run directory", missing)


def test_yaml_apply_names_missing_plan_file(tmp_path):
    missing = tmp_path / "missing-plan.json"

    result = run_cli(
        "yaml-apply",
        "--config",
        CONFIG,
        "--plan",
        str(missing),
        "--approve",
    )

    assert_path_error(result, "YAML plan file", missing)


def assert_unknown_scenario(
    result: subprocess.CompletedProcess[str], available: str
) -> None:
    assert result.returncode == 1
    assert result.stderr.strip() == (
        f"igess: unknown scenario 'bad'; available: {available}"
    )
    assert "Traceback" not in result.stderr


def test_run_lists_available_scenarios(tmp_path):
    result = run_cli(
        "run",
        "--config",
        CONFIG,
        "--tables",
        TABLES,
        "--scenario",
        "bad",
        "--out",
        str(tmp_path / "run"),
    )

    assert_unknown_scenario(result, "analytic_smoke, day_1_progression")


def test_advise_lists_available_scenarios(tmp_path):
    result = run_cli(
        "advise",
        "--config",
        CONFIG,
        "--tables",
        TABLES,
        "--scenario",
        "bad",
        "--out",
        str(tmp_path / "advice"),
    )

    assert_unknown_scenario(result, "analytic_smoke, day_1_progression")


def test_rng_run_lists_available_scenarios(tmp_path):
    result = run_cli(
        "rng-run",
        "--config",
        CONFIG,
        "--scenario",
        "bad",
        "--out",
        str(tmp_path / "rng"),
    )

    assert_unknown_scenario(result, "aura_baseline")
