from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from igess.cli import build_parser
from igess.authoring import cli as authoring_cli
from igess.authoring.response import CommandResponse


RESOURCE_YAML = """\
version: 1
operation: upsert
entity: resource
id: gold
fields:
  name: Gold
  dimension: currency
"""

RESOURCE_JSON = json.dumps(
    {
        "version": 1,
        "operation": "upsert",
        "entity": "resource",
        "id": "gems",
        "fields": {"name": "Gems", "dimension": "currency"},
    }
)

MAX_CHANGE_BYTES = 1_048_576


def run_cli(
    *args: str,
    stdin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "igess.cli", *args],
        input=stdin,
        check=False,
        capture_output=True,
        text=True,
    )


def json_result(result: subprocess.CompletedProcess[str]) -> dict[str, object]:
    assert result.stdout.count("\n") <= 1, result.stdout
    payload = json.loads(result.stdout)
    assert isinstance(payload, dict)
    return payload


def model_commands() -> dict[str, argparse.ArgumentParser]:
    top = next(
        action
        for action in build_parser()._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    model = top.choices["model"]
    nested = next(
        action
        for action in model._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    return nested.choices


def actions(parser: argparse.ArgumentParser) -> dict[str, argparse.Action]:
    return {action.dest: action for action in parser._actions}


def test_model_help_owns_exact_nested_arguments_defaults_examples_and_exit_codes():
    commands = model_commands()

    assert set(commands) == {"init", "status", "apply", "simulate"}
    assert set(actions(commands["init"])) == {"help", "out", "model_id", "json"}
    assert set(actions(commands["status"])) == {"help", "project", "json"}
    assert set(actions(commands["apply"])) == {
        "help",
        "project",
        "change",
        "stdin",
        "format_name",
        "json",
    }
    assert set(actions(commands["simulate"])) == {
        "help",
        "project",
        "scenario",
        "json",
    }
    assert actions(commands["status"])["project"].default == "."
    assert actions(commands["apply"])["project"].default == "."
    assert actions(commands["apply"])["format_name"].default is None
    assert actions(commands["apply"])["format_name"].choices == ("yaml", "json")
    assert actions(commands["simulate"])["project"].default == "."
    assert actions(commands["simulate"])["scenario"].default == "smoke"

    for name, parser in commands.items():
        rendered = parser.format_help()
        assert parser.description and parser.description in rendered
        assert parser.epilog and "Examples:" in parser.epilog
        assert f"igess model {name}" in parser.epilog
        assert "Exit codes:" in parser.epilog
        assert "0  Command completed successfully." in parser.epilog
        assert "1  Command failed." in parser.epilog
        assert "2  Command-line usage error." in parser.epilog
        for action in parser._actions:
            if action.dest != "help":
                assert action.help and action.help.strip()


def test_model_parser_is_red_without_disturbing_legacy_help():
    legacy = run_cli("lint", "--help")
    model = run_cli("model", "--help")

    assert legacy.returncode == 0
    assert "Validate an economy model." in legacy.stdout
    assert model.returncode == 0, model.stderr
    assert "init" in model.stdout
    assert "status" in model.stdout
    assert "apply" in model.stdout
    assert "simulate" in model.stdout


def test_model_init_human_and_json_return_exact_paths(tmp_path: Path):
    human_root = tmp_path / "human model"
    human = run_cli("model", "init", "--out", str(human_root), "--id", "human_id")

    assert human.returncode == 0, human.stderr
    assert human.stderr == ""
    assert human.stdout.splitlines()[0] == f"Initialized model project at {human_root}"
    assert human.stdout.count("Initialized model project") == 1
    assert "Artifacts:" in human.stdout

    root = tmp_path / "json model"
    result = run_cli(
        "model", "init", "--out", str(root), "--id", "json_id", "--json"
    )
    payload = json_result(result)

    assert result.returncode == 0
    assert result.stderr == ""
    assert payload["command"] == "model.init"
    assert payload["ok"] is True
    assert payload["result"] == {
        "project": str(root),
        "model_id": "json_id",
        "config": str(root / "economy.yaml"),
        "datas": str(root / "Datas"),
        "tables": str(root / "Datas" / "__tables__.xlsx"),
        "readme": str(root / "README.md"),
        "run_script": str(root / "run.ps1"),
    }


def test_model_status_absent_valid_incomplete_and_failed_full_json(tmp_path: Path):
    absent = run_cli("model", "status", "--project", str(tmp_path / "absent"), "--json")
    absent_payload = json_result(absent)
    assert absent.returncode == 1
    assert absent_payload["ok"] is False
    assert "Traceback" not in absent.stderr + absent.stdout

    root = tmp_path / "model"
    assert run_cli("model", "init", "--out", str(root)).returncode == 0
    valid = run_cli("model", "status", "--project", str(root), "--json")
    valid_payload = json_result(valid)
    assert valid.returncode == 0
    assert valid.stderr == ""
    assert valid_payload["ok"] is True
    assert valid_payload["result"]["state"] == "incomplete"

    (root / "economy.yaml").write_text("model: [\n", encoding="utf-8")
    failed = run_cli("model", "status", "--project", str(root), "--json")
    failed_payload = json_result(failed)
    assert failed.returncode == 1
    assert failed_payload["ok"] is False
    assert set(failed_payload["result"]) == {
        "model_digest",
        "structural_valid",
        "smoke_eligible",
        "state",
        "entity_counts",
        "missing_requirements",
        "warnings",
        "available_scenarios",
        "latest_smoke_run_id",
    }
    assert failed_payload["result"]["state"] == "failed"
    assert "Traceback" not in failed.stderr + failed.stdout


def test_model_status_human_orders_missing_requirements_before_warnings(tmp_path: Path):
    root = tmp_path / "model"
    assert run_cli("model", "init", "--out", str(root)).returncode == 0

    result = run_cli("model", "status", "--project", str(root))

    lines = result.stdout.splitlines()
    assert result.returncode == 0
    assert result.stderr == ""
    assert lines[0] == "Model is valid but incomplete"
    assert result.stdout.count(lines[0]) == 1
    assert lines.index("Missing requirements:") < lines.index("Warnings:")


@pytest.mark.parametrize(
    ("source_name", "document", "extra_args", "expected_id"),
    [
        ("rule.yaml", RESOURCE_YAML, (), "gold"),
        ("rule.json", RESOURCE_JSON, (), "gems"),
    ],
)
def test_model_apply_autodetects_change_file_extension(
    tmp_path: Path,
    source_name: str,
    document: str,
    extra_args: tuple[str, ...],
    expected_id: str,
):
    root = tmp_path / expected_id
    change = tmp_path / source_name
    assert run_cli("model", "init", "--out", str(root)).returncode == 0
    change.write_text(document, encoding="utf-8")

    result = run_cli(
        "model",
        "apply",
        "--project",
        str(root),
        "--change",
        str(change),
        *extra_args,
        "--json",
    )
    payload = json_result(result)

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert payload["code"] == "applied"
    assert payload["result"]["id"] == expected_id
    assert payload["result"]["status"]["state"] == "incomplete"
    assert payload["result"]["smoke"]["status"] == "not_run"


def test_model_apply_file_format_is_strictly_selected_by_extension(tmp_path: Path):
    root = tmp_path / "model"
    unknown = tmp_path / "rule.txt"
    json_change = tmp_path / "rule.json"
    assert run_cli("model", "init", "--out", str(root)).returncode == 0
    unknown.write_text(RESOURCE_YAML, encoding="utf-8")
    json_change.write_text(RESOURCE_JSON, encoding="utf-8")

    rejected = run_cli(
        "model",
        "apply",
        "--project",
        str(root),
        "--change",
        str(unknown),
        "--format",
        "yaml",
        "--json",
    )
    rejected_payload = json_result(rejected)
    assert rejected.returncode == 1
    assert rejected_payload["code"] == "invalid_change"
    assert "Traceback" not in rejected.stderr + rejected.stdout

    accepted = run_cli(
        "model",
        "apply",
        "--project",
        str(root),
        "--change",
        str(json_change),
        "--format",
        "yaml",
        "--json",
    )
    accepted_payload = json_result(accepted)
    assert accepted.returncode == 0, accepted.stderr + accepted.stdout
    assert accepted_payload["result"]["id"] == "gems"


def test_model_apply_help_limits_format_option_to_standard_input():
    apply = model_commands()["apply"]

    assert actions(apply)["format_name"].help == (
        "Standard-input format; defaults to yaml. File input always uses its extension."
    )


def test_model_apply_stdin_stops_at_budget_without_waiting_for_eof(tmp_path: Path):
    root = tmp_path / "model"
    assert run_cli("model", "init", "--out", str(root)).returncode == 0
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "igess.cli",
            "model",
            "apply",
            "--project",
            str(root),
            "--stdin",
            "--json",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdin is not None
    try:
        process.stdin.write(b" " * (MAX_CHANGE_BYTES + 1))
        process.stdin.flush()
        returncode = process.wait(timeout=15)
        assert process.stdout is not None
        assert process.stderr is not None
        stdout = process.stdout.read().decode("utf-8")
        stderr = process.stderr.read().decode("utf-8")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        process.stdin.close()

    payload = json.loads(stdout)
    assert returncode == 1
    assert stderr == ""
    assert payload["code"] == "invalid_change"
    assert payload["details"]["reason"] == "budget_exceeded"
    assert payload["details"]["budget"] == "source_bytes"
    assert "Traceback" not in stdout + stderr


@pytest.mark.parametrize("source", ["stdin", "file"])
def test_model_apply_accepts_a_change_at_the_exact_byte_budget(
    tmp_path: Path,
    source: str,
):
    root = tmp_path / source
    assert run_cli("model", "init", "--out", str(root)).returncode == 0
    document = RESOURCE_YAML + (" " * (MAX_CHANGE_BYTES - len(RESOURCE_YAML.encode("utf-8"))))
    if source == "stdin":
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "igess.cli",
                "model",
                "apply",
                "--project",
                str(root),
                "--stdin",
                "--json",
            ],
            input=document.encode("utf-8"),
            check=False,
            capture_output=True,
        )
        payload = json.loads(result.stdout.decode("utf-8"))
        diagnostic = result.stderr.decode("utf-8") + result.stdout.decode("utf-8")
    else:
        change = tmp_path / "boundary.yaml"
        change.write_bytes(document.encode("utf-8"))
        result = run_cli(
            "model",
            "apply",
            "--project",
            str(root),
            "--change",
            str(change),
            "--json",
        )
        payload = json_result(result)
        diagnostic = result.stderr + result.stdout

    assert result.returncode == 0, diagnostic
    assert payload["result"]["id"] == "gold"


def test_model_apply_rejects_an_oversized_change_file_before_parsing(tmp_path: Path):
    root = tmp_path / "model"
    change = tmp_path / "oversized.yaml"
    assert run_cli("model", "init", "--out", str(root)).returncode == 0
    change.write_bytes(b" " * (MAX_CHANGE_BYTES + 1))

    result = run_cli(
        "model",
        "apply",
        "--project",
        str(root),
        "--change",
        str(change),
        "--json",
    )
    payload = json_result(result)

    assert result.returncode == 1
    assert result.stderr == ""
    assert payload["code"] == "invalid_change"
    assert payload["details"]["reason"] == "budget_exceeded"
    assert payload["details"]["budget"] == "source_bytes"
    assert "Traceback" not in result.stdout


def test_change_file_reader_rejects_growth_during_bounded_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    change = tmp_path / "growing.yaml"
    change.write_text(RESOURCE_YAML, encoding="utf-8")
    real_read = os.read
    appended = False

    def grow_after_first_read(fd: int, size: int) -> bytes:
        nonlocal appended
        chunk = real_read(fd, size)
        if not appended:
            appended = True
            with change.open("ab") as stream:
                stream.write(b" ")
        return chunk

    monkeypatch.setattr(os, "read", grow_after_first_read)
    response = authoring_cli._read_change_document(
        SimpleNamespace(change=str(change), format_name=None)
    )

    assert isinstance(response, CommandResponse)
    assert response.ok is False
    assert response.code == "change_read_failed"
    assert response.details["reason"] == "source_changed"


def test_change_file_reader_rejects_symbolic_links_when_supported(tmp_path: Path):
    target = tmp_path / "target.yaml"
    link = tmp_path / "link.yaml"
    target.write_text(RESOURCE_YAML, encoding="utf-8")
    try:
        link.symlink_to(target)
    except OSError as error:
        pytest.skip(f"symbolic links unavailable: {error}")

    response = authoring_cli._read_change_document(
        SimpleNamespace(change=str(link), format_name=None)
    )

    assert isinstance(response, CommandResponse)
    assert response.ok is False
    assert response.code == "change_read_failed"
    assert response.details["reason"] == "unsafe_file"


def test_bounded_stdin_reader_supports_replaced_text_stream(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(authoring_cli.sys, "stdin", io.StringIO(RESOURCE_YAML))

    document = authoring_cli._read_change_document(
        SimpleNamespace(change=None, format_name=None)
    )

    assert document == (RESOURCE_YAML, "yaml")


@pytest.mark.parametrize(
    ("document", "format_args", "expected_id"),
    [
        (RESOURCE_YAML, (), "gold"),
        (RESOURCE_JSON, ("--format", "json"), "gems"),
    ],
)
def test_model_apply_reads_stdin_with_yaml_default_or_explicit_json(
    tmp_path: Path,
    document: str,
    format_args: tuple[str, ...],
    expected_id: str,
):
    root = tmp_path / expected_id
    assert run_cli("model", "init", "--out", str(root)).returncode == 0

    result = run_cli(
        "model",
        "apply",
        "--project",
        str(root),
        "--stdin",
        *format_args,
        "--json",
        stdin=document,
    )
    payload = json_result(result)

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert payload["result"]["id"] == expected_id


def test_model_apply_requires_exactly_one_input_source(tmp_path: Path):
    root = tmp_path / "model"
    change = tmp_path / "change.yaml"
    change.write_text(RESOURCE_YAML, encoding="utf-8")

    neither = run_cli("model", "apply", "--project", str(root))
    both = run_cli(
        "model",
        "apply",
        "--project",
        str(root),
        "--change",
        str(change),
        "--stdin",
        stdin=RESOURCE_YAML,
    )

    assert neither.returncode == 2
    assert both.returncode == 2
    assert "Traceback" not in neither.stderr + both.stderr


def test_model_apply_invalid_and_stale_changes_are_structured_without_traceback(
    tmp_path: Path,
):
    root = tmp_path / "model"
    assert run_cli("model", "init", "--out", str(root)).returncode == 0
    invalid = RESOURCE_YAML.replace("  dimension: currency\n", "")
    stale = RESOURCE_YAML.replace(
        "fields:\n",
        f"if_model_digest: sha256:{'0' * 64}\nfields:\n",
    )

    for document, expected_code in ((invalid, "invalid_change"), (stale, "stale_model")):
        result = run_cli(
            "model",
            "apply",
            "--project",
            str(root),
            "--stdin",
            "--json",
            stdin=document,
        )
        payload = json_result(result)
        assert result.returncode == 1
        assert payload["ok"] is False
        assert payload["code"] == expected_code
        assert "Traceback" not in result.stderr + result.stdout


def _apply_runnable_activity(root: Path) -> dict[str, object]:
    changes = [
        RESOURCE_YAML,
        """\
version: 1
operation: upsert
entity: activity
id: gather
fields:
  name: Gather
  source_type: active
  unlock_condition: always
""",
        """\
version: 1
operation: upsert
entity: activity_output
id: gather_gold
fields:
  activity_id: gather
  output_resource: gold
  amount_per_second: "1"
""",
        """\
version: 1
operation: upsert
entity: player_profile
id: default
fields:
  activity_weights:
    gather: "1"
""",
    ]
    payload: dict[str, object] = {}
    for document in changes:
        result = run_cli(
            "model",
            "apply",
            "--project",
            str(root),
            "--stdin",
            "--json",
            stdin=document,
        )
        assert result.returncode == 0, result.stderr + result.stdout
        payload = json_result(result)
    return payload


def test_model_apply_automatically_runs_smoke_when_candidate_becomes_runnable(
    tmp_path: Path,
):
    root = tmp_path / "model"
    assert run_cli("model", "init", "--out", str(root)).returncode == 0

    payload = _apply_runnable_activity(root)

    assert payload["result"]["status"]["state"] == "runnable"
    assert payload["result"]["smoke"]["status"] == "success"
    run_id = payload["result"]["smoke"]["run_id"]
    assert (root / "runs" / run_id / "output" / "run_manifest.json").is_file()
    assert (root / "runs" / run_id / "report" / "index.html").is_file()


def test_model_simulate_default_and_explicit_scenario_return_artifact_paths(
    tmp_path: Path,
):
    root = tmp_path / "model"
    assert run_cli("model", "init", "--out", str(root)).returncode == 0
    _apply_runnable_activity(root)

    for scenario_args in ((), ("--scenario", "smoke")):
        result = run_cli(
            "model",
            "simulate",
            "--project",
            str(root),
            *scenario_args,
            "--json",
        )
        payload = json_result(result)
        assert result.returncode == 0, result.stderr + result.stdout
        assert result.stderr == ""
        assert payload["result"]["scenario_id"] == "smoke"
        assert Path(payload["result"]["output_dir"]).is_dir()
        assert Path(payload["result"]["report_index"]).is_file()


def test_model_simulate_domain_failure_has_no_traceback(tmp_path: Path):
    root = tmp_path / "model"
    assert run_cli("model", "init", "--out", str(root)).returncode == 0

    result = run_cli(
        "model",
        "simulate",
        "--project",
        str(root),
        "--scenario",
        "unknown",
        "--json",
    )
    payload = json_result(result)

    assert result.returncode == 1
    assert payload["ok"] is False
    assert "Traceback" not in result.stderr + result.stdout
