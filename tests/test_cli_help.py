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
    "gate",
    "init",
    "lint",
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


def test_every_registered_command_has_description_example_and_argument_help():
    commands = command_group(build_parser())

    assert set(commands.choices) == EXPECTED_COMMANDS
    for command, parser in commands.choices.items():
        assert parser.description and parser.description.strip(), command
        assert parser.epilog and "Examples:" in parser.epilog, command
        assert f"igess {command}" in parser.epilog, command
        for action in parser._actions:
            if action.dest == "help":
                continue
            assert action.help not in (None, argparse.SUPPRESS), (command, action.dest)
            assert action.help.strip(), (command, action.dest)


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


def test_help_formatter_follows_terminal_width(monkeypatch):
    monkeypatch.setenv("COLUMNS", "94")

    formatter = build_parser().formatter_class("igess")

    assert formatter._width == 92
    assert formatter._max_help_position == 32
