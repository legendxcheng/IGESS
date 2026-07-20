import argparse
import subprocess
import sys

import pytest

from igess.cli import build_parser


EXPECTED_COMMANDS = {
    "advise",
    "compare",
    "dashboard",
    "doctor",
    "explain",
    "export-tables",
    "fish-rng-run",
    "gate",
    "init",
    "lint",
    "model",
    "report",
    "review-proposal",
    "review-run",
    "rng-run",
    "run",
    "scan",
    "stone-realm-progression",
    "stone-role-level",
    "verify-edits",
    "yaml-apply",
    "yaml-plan",
}

CRITICAL_HELP_CASES = (
    (
        "lint",
        (
            ("config", "Path to the economy YAML configuration."),
            ("tables", "Directory containing exported Luban JSON tables."),
        ),
        "igess lint --config economy.yaml --tables luban_exports",
    ),
    (
        "rng-run",
        (
            ("config", "Path to the economy YAML configuration."),
            ("scenario", "RNG scenario identifier to simulate."),
            ("out", "Directory for RNG simulation outputs."),
        ),
        "igess rng-run --config economy.yaml --scenario loot_check --out runs/loot_check",
    ),
    (
        "report",
        (
            ("run", "Simulation run directory to report on."),
            ("out", "Directory for the generated static report."),
            ("title", "Optional report title."),
        ),
        "igess report --run runs/day_1 --out reports/day_1",
    ),
    (
        "dashboard",
        (
            ("project", "IGESS project root directory."),
            ("config", "Economy YAML path, relative to the project root by default."),
            (
                "tables",
                "Exported table directory, relative to the project root by default.",
            ),
            ("runs_root", "Optional directory used to discover simulation runs."),
            ("host", "Dashboard bind address."),
            ("port", "Dashboard TCP port."),
        ),
        "igess dashboard --project . --port 8765",
    ),
    (
        "init",
        (
            ("template", "Project template name."),
            ("out", "Directory to initialize."),
        ),
        "igess init --out my-economy",
    ),
    (
        "run",
        (
            ("config", "Path to the economy YAML configuration."),
            ("tables", "Directory containing exported Luban JSON tables."),
            ("scenario", "Scenario identifier to simulate."),
            ("out", "Directory for simulation outputs."),
        ),
        "igess run --config economy.yaml --tables luban_exports "
        "--scenario day_1 --out runs/day_1",
    ),
    (
        "scan",
        (
            ("config", "Path to the economy YAML configuration."),
            ("tables", "Directory containing exported Luban JSON tables."),
            ("scenario", "Scenario identifier to simulate."),
            ("param", "Parameter scan expression PATH=START..STOP:STEP."),
            ("out", "Directory for scan runs and summary."),
        ),
        "igess scan --config examples/shelldiver_v0/economy.yaml --tables "
        "examples/shelldiver_v0/luban_exports --scenario day_1_progression --param "
        "generators.fisherman.cost_growth=1.14..1.18:0.01 --out scan-out",
    ),
)

CRITICAL_COMMANDS = frozenset(case[0] for case in CRITICAL_HELP_CASES)
NESTED_COMMANDS = frozenset({"model"})
OTHER_COMMANDS = tuple(sorted(EXPECTED_COMMANDS - CRITICAL_COMMANDS - NESTED_COMMANDS))


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "igess.cli", *args],
        check=False,
        capture_output=True,
        text=True,
    )


def command_group(parser: argparse.ArgumentParser) -> argparse._SubParsersAction:
    return next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )


def command_actions(parser: argparse.ArgumentParser) -> dict[str, argparse.Action]:
    return {action.dest: action for action in parser._actions}


def example_from(parser: argparse.ArgumentParser) -> str:
    assert parser.epilog and "Examples:" in parser.epilog
    return parser.epilog.split("Examples:", 1)[1].strip()


def assert_complete_help_contract(command: str, parser: argparse.ArgumentParser) -> None:
    rendered = parser.format_help()
    assert parser.description and parser.description.strip(), command
    assert parser.description in rendered, command
    assert parser.epilog and "Examples:" in parser.epilog, command
    example = example_from(parser)
    assert example.startswith(f"igess {command} "), command
    assert example in rendered, command

    example_tokens = example.split()
    for action in parser._actions:
        if action.dest == "help":
            continue
        assert action.help not in (None, argparse.SUPPRESS), (command, action.dest)
        assert action.help.strip(), (command, action.dest)
        if action.required:
            assert any(option in example_tokens for option in action.option_strings), (
                command,
                action.dest,
            )


def test_top_level_cli_help_lists_all_commands_with_summaries_and_exit_codes():
    parser = build_parser()
    commands = command_group(parser)
    result = run_cli("--help")

    assert result.returncode == 0, result.stderr
    assert set(commands.choices) == EXPECTED_COMMANDS
    assert "Commands:" in result.stdout
    for choice in commands._choices_actions:
        assert choice.dest in result.stdout
        assert choice.help
        assert choice.help in result.stdout
    assert "Exit codes:" in result.stdout
    assert "0  Command completed successfully." in result.stdout
    assert "1  Command failed." in result.stdout
    assert "2  Command-line usage error." in result.stdout


def test_parameterized_help_cases_cover_every_registered_command():
    commands = command_group(build_parser())

    assert set(commands.choices) == EXPECTED_COMMANDS
    assert CRITICAL_COMMANDS | NESTED_COMMANDS | set(OTHER_COMMANDS) == set(commands.choices)
    assert CRITICAL_COMMANDS.isdisjoint(OTHER_COMMANDS)


def test_model_help_is_a_nested_command_group():
    model = command_group(build_parser()).choices["model"]
    nested = command_group(model)
    rendered = model.format_help()

    assert set(nested.choices) == {"init", "status", "apply", "simulate"}
    assert "Author a game economy one validated rule at a time." in rendered
    assert "igess model init --out projects/my-game" in rendered
    assert "Exit codes:" in rendered


@pytest.mark.parametrize(
    ("command", "expected_argument_help", "expected_example"),
    CRITICAL_HELP_CASES,
    ids=[case[0] for case in CRITICAL_HELP_CASES],
)
def test_critical_command_help_contracts(
    command,
    expected_argument_help,
    expected_example,
):
    parser = command_group(build_parser()).choices[command]
    actions = command_actions(parser)
    rendered = parser.format_help()

    assert_complete_help_contract(command, parser)
    assert example_from(parser) == expected_example
    for dest, expected_help in expected_argument_help:
        assert actions[dest].help == expected_help
        assert actions[dest].option_strings[0] in rendered


@pytest.mark.parametrize("command", OTHER_COMMANDS)
def test_other_command_help_contracts(command):
    parser = command_group(build_parser()).choices[command]

    assert_complete_help_contract(command, parser)


@pytest.mark.parametrize(
    ("command", "expected_text"),
    [
        (
            "run",
            (
                "Run a deterministic economy simulation.",
                "--config",
                "--tables",
                "--scenario",
                "--out",
                "igess run --config economy.yaml --tables luban_exports "
                "--scenario day_1 --out runs/day_1",
            ),
        ),
        (
            "scan",
            (
                "Scan a numeric parameter.",
                "Parameter scan expression PATH=START..STOP:STEP.",
                "igess scan --config examples/shelldiver_v0/economy.yaml --tables "
                "examples/shelldiver_v0/luban_exports --scenario day_1_progression --param "
                "generators.fisherman.cost_growth=1.14..1.18:0.01 --out scan-out",
            ),
        ),
    ],
)
def test_representative_command_help_works_through_cli(command, expected_text):
    result = run_cli(command, "--help")

    assert result.returncode == 0, result.stderr
    for text in expected_text:
        assert text in result.stdout


def test_run_and_scan_argument_contracts_are_unchanged():
    commands = command_group(build_parser()).choices
    run_actions = command_actions(commands["run"])
    scan_actions = command_actions(commands["scan"])

    assert set(run_actions) == {"help", "config", "tables", "scenario", "out"}
    assert set(scan_actions) == {"help", "config", "tables", "scenario", "param", "out"}
    assert all(run_actions[name].required for name in ("config", "tables", "scenario", "out"))
    assert all(
        scan_actions[name].required
        for name in ("config", "tables", "scenario", "param", "out")
    )


def test_missing_defaults_are_hidden_but_real_defaults_are_rendered():
    commands = command_group(build_parser()).choices
    rendered_help = "\n".join(parser.format_help() for parser in commands.values())

    assert "(default: None)" not in rendered_help

    init_actions = command_actions(commands["init"])
    assert init_actions["template"].default == "incremental-basic"
    assert init_actions["out"].default is None
    assert "(default: incremental-basic)" in commands["init"].format_help()

    dashboard_actions = command_actions(commands["dashboard"])
    assert dashboard_actions["config"].default is None
    assert dashboard_actions["tables"].default is None
    assert dashboard_actions["host"].default == "127.0.0.1"
    assert dashboard_actions["port"].default == 8765
    dashboard_help = commands["dashboard"].format_help()
    assert "(default: 127.0.0.1)" in dashboard_help
    assert "(default: 8765)" in dashboard_help

    doctor_actions = command_actions(commands["doctor"])
    assert doctor_actions["project"].default == "."
    assert doctor_actions["config"].default == "examples/shelldiver_v0/economy.yaml"
    assert doctor_actions["tables"].default == "examples/shelldiver_v0/luban_exports"
    doctor_help = commands["doctor"].format_help()
    assert doctor_help.count("default:") == 3
    assert "examples/shelldiver_v0/economy.yaml" in doctor_help
    assert "examples/shelldiver_v0/luban_exports" in doctor_help


@pytest.mark.parametrize(
    ("command", "expected_required", "expected_defaults"),
    [
        (
            "dashboard",
            frozenset(),
            (
                ("project", "."),
                ("config", None),
                ("tables", None),
                ("runs_root", None),
                ("host", "127.0.0.1"),
                ("port", 8765),
            ),
        ),
        (
            "init",
            frozenset({"out"}),
            (("template", "incremental-basic"), ("out", None)),
        ),
    ],
)
def test_dashboard_and_init_defaults_and_required_contracts(
    command,
    expected_required,
    expected_defaults,
):
    parser = command_group(build_parser()).choices[command]
    actions = command_actions(parser)
    rendered = parser.format_help()

    required = {action.dest for action in parser._actions if action.required}
    assert required == expected_required
    for dest, expected_default in expected_defaults:
        assert actions[dest].default == expected_default
    assert rendered.count("default:") == sum(
        default is not None for _, default in expected_defaults
    )
    assert "(default: None)" not in rendered


def test_help_formatter_follows_terminal_width(monkeypatch):
    monkeypatch.setenv("COLUMNS", "94")

    formatter = build_parser().formatter_class("igess")

    assert formatter._width == 92
    assert formatter._max_help_position == 32
