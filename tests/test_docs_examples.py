import json
import subprocess
import sys
import tomllib
from pathlib import Path

import yaml


CONFIG = "examples/shelldiver_v0/economy.yaml"
AGENT_GUIDE = Path("docs/agent-operator-guide.md")


ONE_CHANGE_YAML = """version: 1
operation: upsert
entity: resource
id: gold
fields:
  name: Gold
  dimension: currency
if_model_digest: sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
"""


def _read(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def _fenced_block(document: str, marker: str, language: str) -> str:
    start = document.index(marker) + len(marker)
    opening = document.index(f"```{language}\n", start) + len(language) + 4
    end = document.index("```", opening)
    return document[opening:end]


def test_agent_first_incremental_authoring_is_the_primary_documented_flow():
    readme = _read("README.md")
    guide = _read(AGENT_GUIDE)

    for command in (
        "igess model init --out projects/my-game --id my_game",
        "igess model status --project projects/my-game --json",
        "igess model apply --project projects/my-game --change changes/resource.yaml --json",
        "igess model simulate --project projects/my-game --scenario smoke --json",
    ):
        assert command in guide

    assert "Agent 一次协助填写一条规则" in readme
    assert "docs/agent-operator-guide.md" in readme
    assert "10 个 tick" in guide
    assert "首要用户熟悉 Python" in guide


def test_guide_contains_one_exact_change_and_the_stable_json_envelope():
    guide = _read(AGENT_GUIDE)

    change_source = _fenced_block(guide, "<!-- exact-one-change -->", "yaml")
    assert change_source == ONE_CHANGE_YAML
    assert yaml.safe_load(change_source) == {
        "version": 1,
        "operation": "upsert",
        "entity": "resource",
        "id": "gold",
        "fields": {"name": "Gold", "dimension": "currency"},
        "if_model_digest": (
            "sha256:0123456789abcdef0123456789abcdef"
            "0123456789abcdef0123456789abcdef"
        ),
    }

    response = json.loads(
        _fenced_block(guide, "<!-- exact-json-envelope -->", "json")
    )
    assert list(response) == [
        "schema_version",
        "command",
        "ok",
        "code",
        "message",
        "details",
        "result",
    ]
    assert response["schema_version"] == 1
    assert response["command"] == "model.status"
    assert response["ok"] is True
    assert isinstance(response["details"], dict)
    assert isinstance(response["result"], dict)


def test_guide_defines_progression_smoke_recovery_and_front_end_boundaries():
    guide = _read(AGENT_GUIDE)

    for state in ("failed", "incomplete", "runnable", "ready"):
        assert f"`{state}`" in guide
    for phrase in (
        "自动 smoke",
        "if_model_digest",
        "stale_model",
        "changes/failed",
        "崩溃恢复",
        "Dashboard 不填写或修改规则",
        "正式调参",
        "旧命令保持兼容",
    ):
        assert phrase in guide


def test_sources_of_truth_and_external_data_policy_are_documented_and_configured():
    guide = _read(AGENT_GUIDE)
    luban = _read("docs/luban-workflow.md")
    metadata = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    pytest_options = metadata["tool"]["pytest"]["ini_options"]

    assert "`economy.yaml` 与 `Datas/*.xlsx` 是正式 source of truth" in guide
    assert "Generated output: `luban_exports/`" in luban
    assert (
        "pytest -m external_data tests/test_stone_role_level.py "
        "tests/test_stone_realm_progression.py"
    ) in guide
    assert pytest_options["addopts"] == '-m "not external_data"'
    assert any(
        marker.startswith("external_data:") for marker in pytest_options["markers"]
    )

    for module in (
        "tests/test_stone_role_level.py",
        "tests/test_stone_realm_progression.py",
    ):
        source = _read(module)
        assert "import pytest" in source
        assert "pytestmark = pytest.mark.external_data" in source


def test_project_metadata_and_readme_document_v05_workflow():
    metadata = tomllib.loads(open("pyproject.toml", "rb").read().decode("utf-8"))
    readme = open("README.md", encoding="utf-8").read()

    assert metadata["project"]["version"] == "0.5.0"
    for command in [
        "report",
        "dashboard",
        "compare",
        "scan",
        "gate",
        "doctor",
        "explain",
        "advise",
        "review-run",
        "yaml-plan",
        "yaml-apply",
    ]:
        assert f"igess.cli {command}" in readme
    assert "v0.5 Agent Analyst" in readme


def test_documented_v04_cli_flow_runs(tmp_path):
    tables = tmp_path / "exports"
    run_dir = tmp_path / "run"
    report_dir = tmp_path / "report"
    compare_dir = tmp_path / "compare"
    scan_dir = tmp_path / "scan"
    gate_dir = tmp_path / "gate"
    gate_config = tmp_path / "gate.yaml"
    gate_config.write_text(
        open(CONFIG, encoding="utf-8").read()
        + """

regression_gates:
  day_1_progression:
    max_payback_seconds:
      generator:fisherman: 999999
""",
        encoding="utf-8",
        newline="\n",
    )

    commands = [
        [
            "export-tables",
            "--datas",
            "data-tables/Datas",
            "--out",
            str(tables),
        ],
        ["lint", "--config", CONFIG, "--tables", str(tables)],
        [
            "run",
            "--config",
            CONFIG,
            "--tables",
            str(tables),
            "--scenario",
            "day_1_progression",
            "--out",
            str(run_dir),
        ],
        ["report", "--run", str(run_dir), "--out", str(report_dir)],
        ["compare", "--base", str(run_dir), "--candidate", str(run_dir), "--out", str(compare_dir)],
        [
            "scan",
            "--config",
            CONFIG,
            "--tables",
            str(tables),
            "--scenario",
            "day_1_progression",
            "--param",
            "generators.fisherman.cost_growth=1.14..1.15:0.01",
            "--out",
            str(scan_dir),
        ],
        [
            "gate",
            "--base",
            str(run_dir),
            "--candidate",
            str(run_dir),
            "--config",
            str(gate_config),
            "--out",
            str(gate_dir),
        ],
        ["doctor", "--project", ".", "--config", CONFIG, "--tables", str(tables)],
        ["explain", "--run", str(run_dir), "--event", "0"],
    ]
    for command in commands:
        result = subprocess.run(
            [sys.executable, "-m", "igess.cli", *command],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"{command}: {result.stderr}\n{result.stdout}"

    assert (report_dir / "index.html").exists()
    assert (compare_dir / "comparison.json").exists()
    assert (scan_dir / "scan.json").exists()
    assert (gate_dir / "gate_results.json").exists()
