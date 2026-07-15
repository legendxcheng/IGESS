import subprocess
import sys

import pytest


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "igess.cli", *args],
        check=False,
        capture_output=True,
        text=True,
    )


COMMAND_SUMMARIES = {
    "export-tables": "Export registered Luban workbooks",
    "stone-role-level": "Build the Stone role-level curve",
    "stone-realm-progression": "Build the Stone realm progression curve",
    "report": "Generate a static HTML report",
    "compare": "Compare two simulation runs",
    "scan": "Scan a numeric parameter",
    "rng-run": "Run an RNG scenario",
    "gate": "Evaluate regression gates",
    "advise": "Generate tuning advice",
    "review-run": "Review an existing simulation run",
    "review-proposal": "Review a tuning proposal",
    "verify-edits": "Verify proposed configuration edits",
    "yaml-plan": "Create a reviewable YAML edit plan",
    "yaml-apply": "Apply an approved YAML edit plan",
    "init": "Initialize an IGESS project",
    "doctor": "Diagnose an IGESS project",
    "explain": "Explain one simulation event",
    "dashboard": "Serve the local simulation dashboard",
    "lint": "Validate an economy model",
    "run": "Run a deterministic economy simulation",
}


COMMAND_ARGUMENT_HELP = {
    "export-tables": {
        "--datas": "Directory containing registered Luban workbooks.",
        "--out": "Directory for exported JSON tables.",
    },
    "stone-role-level": {
        "--role-lv": "Stone role-level workbook or sheet input.",
        "--attribute-def": "Stone attribute-definition workbook or sheet input.",
        "--out": "Directory for generated role-level artifacts.",
    },
    "stone-realm-progression": {
        "--role-realm": "Stone role-realm workbook or sheet input.",
        "--attribute-def": "Stone attribute-definition workbook or sheet input.",
        "--out": "Directory for generated realm artifacts.",
    },
    "report": {
        "--run": "Simulation run directory to report on.",
        "--out": "Directory for the generated static report.",
        "--title": "Optional report title.",
    },
    "compare": {
        "--base": "Baseline simulation run directory.",
        "--candidate": "Candidate simulation run directory.",
        "--out": "Directory for the comparison report.",
    },
    "scan": {
        "--config": "Path to the economy YAML configuration.",
        "--tables": "Directory containing exported Luban JSON tables.",
        "--scenario": "Scenario identifier to simulate.",
        "--param": "Parameter scan expression path=start:stop:step.",
        "--out": "Directory for scan runs and summary.",
    },
    "rng-run": {
        "--config": "Path to the economy YAML configuration.",
        "--scenario": "RNG scenario identifier to simulate.",
        "--out": "Directory for RNG simulation outputs.",
    },
    "gate": {
        "--base": "Baseline simulation run directory.",
        "--candidate": "Candidate simulation run directory.",
        "--config": "Path to the regression gate YAML configuration.",
        "--out": "Directory for regression gate results.",
    },
    "advise": {
        "--config": "Path to the economy YAML configuration.",
        "--tables": "Directory containing exported Luban JSON tables.",
        "--scenario": "Scenario identifier to analyze.",
        "--out": "Directory for tuning advice.",
        "--baseline": "Optional baseline simulation run directory.",
    },
    "review-run": {
        "--run": "Simulation run directory to review.",
        "--out": "Directory for review artifacts.",
        "--baseline": "Optional baseline simulation run directory.",
    },
    "review-proposal": {
        "--proposal": "Path to the tuning proposal YAML file.",
        "--out": "Directory for proposal review artifacts.",
    },
    "verify-edits": {
        "--config": "Path to the economy YAML configuration.",
        "--proposal": "Path to the tuning proposal YAML file.",
        "--scenario": "Scenario identifier used for verification.",
        "--out": "Directory for verification artifacts.",
        "--tables": "Optional exported Luban JSON table directory.",
        "--datas": "Optional registered Luban workbook directory.",
        "--baseline": "Optional baseline simulation run directory.",
    },
    "yaml-plan": {
        "--config": "Path to the economy YAML configuration.",
        "--intent": "Natural-language edit intent.",
        "--out": "Path for the generated YAML edit plan.",
    },
    "yaml-apply": {
        "--config": "Path to the economy YAML configuration.",
        "--plan": "Path to a generated YAML edit plan.",
        "--approve": "Confirm that the reviewed plan may be applied.",
        "--tables": "Optional exported Luban JSON table directory.",
    },
    "init": {
        "--template": "Project template name.",
        "--out": "Directory to initialize.",
    },
    "doctor": {
        "--project": "IGESS project root directory.",
        "--config": "Economy YAML path, relative to the project root by default.",
        "--tables": "Exported table directory, relative to the project root by default.",
    },
    "explain": {
        "--run": "Simulation run directory containing event artifacts.",
        "--event": "Zero-based event index to explain.",
    },
    "dashboard": {
        "--project": "IGESS project root directory.",
        "--config": "Economy YAML path, relative to the project root by default.",
        "--tables": "Exported table directory, relative to the project root by default.",
        "--runs-root": "Optional directory used to discover simulation runs.",
        "--host": "Dashboard bind address.",
        "--port": "Dashboard TCP port.",
    },
    "lint": {
        "--config": "Path to the economy YAML configuration.",
        "--tables": "Directory containing exported Luban JSON tables.",
    },
    "run": {
        "--config": "Path to the economy YAML configuration.",
        "--tables": "Directory containing exported Luban JSON tables.",
        "--scenario": "Scenario identifier to simulate.",
        "--out": "Directory for simulation outputs.",
    },
}


def test_top_level_help_lists_and_describes_all_commands_and_exit_codes():
    result = run_cli("--help")

    assert result.returncode == 0, result.stderr
    assert "Commands:" in result.stdout
    for command, summary in COMMAND_SUMMARIES.items():
        assert command in result.stdout
        assert summary in result.stdout
    assert "Exit codes:" in result.stdout
    assert "0  Command completed successfully." in result.stdout
    assert "1  Command failed." in result.stdout
    assert "2  Command-line usage error." in result.stdout


@pytest.mark.parametrize(
    ("command", "example"),
    [
        (
            "run",
            "igess run --config economy.yaml --tables luban_exports --scenario day_1 --out runs/day_1",
        ),
        ("lint", "igess lint --config economy.yaml --tables luban_exports"),
        (
            "scan",
            "igess scan --config economy.yaml --tables luban_exports --scenario day_1",
        ),
        (
            "rng-run",
            "igess rng-run --config economy.yaml --scenario loot_check --out runs/loot_check",
        ),
        ("report", "igess report --run runs/day_1 --out reports/day_1"),
        ("dashboard", "igess dashboard --project . --port 8765"),
        ("init", "igess init --out my-economy"),
    ],
)
def test_primary_command_help_has_arguments_and_complete_example(command, example):
    result = run_cli(command, "--help")

    assert result.returncode == 0, result.stderr
    assert "Examples:" in result.stdout
    assert example in result.stdout
    for option, description in COMMAND_ARGUMENT_HELP[command].items():
        assert option in result.stdout
        assert description in result.stdout


@pytest.mark.parametrize("command", sorted(COMMAND_ARGUMENT_HELP))
def test_every_existing_command_documents_each_argument(command):
    result = run_cli(command, "--help")

    assert result.returncode == 0, result.stderr
    assert "Examples:" in result.stdout
    for option, description in COMMAND_ARGUMENT_HELP[command].items():
        assert option in result.stdout
        assert description in result.stdout


@pytest.mark.parametrize(
    ("command", "default_text"),
    [
        ("init", "incremental-basic"),
        ("doctor", "examples/shelldiver_v0/economy.yaml"),
        ("dashboard", "127.0.0.1"),
        ("dashboard", "8765"),
    ],
)
def test_command_help_shows_meaningful_defaults(command, default_text):
    result = run_cli(command, "--help")

    assert result.returncode == 0, result.stderr
    assert f"(default: {default_text})" in result.stdout


def test_help_does_not_expose_unimplemented_model_command():
    result = run_cli("--help")

    assert "\n    model" not in result.stdout
