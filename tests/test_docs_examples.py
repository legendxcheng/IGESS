import subprocess
import sys
import tomllib


CONFIG = "examples/shelldiver_v0/economy.yaml"


def test_project_metadata_and_readme_document_v04_workflow():
    metadata = tomllib.loads(open("pyproject.toml", "rb").read().decode("utf-8"))
    readme = open("README.md", encoding="utf-8").read()

    assert metadata["project"]["version"] == "0.4.0"
    for command in [
        "report",
        "dashboard",
        "compare",
        "scan",
        "gate",
        "doctor",
        "explain",
    ]:
        assert f"igess.cli {command}" in readme
    assert "v0.4 Workflow" in readme


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
