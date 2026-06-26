import json
import subprocess
import sys

from igess.builder import ModelBuilder
from igess.compare import compare_runs
from igess.loader import ConfigLoader
from igess.metrics import extract_metrics
from igess.outputs import OutputWriter
from igess.scan import parse_scan_parameter, run_scan
from igess.simulator import Simulator
from igess.gates import evaluate_gates


CONFIG = "examples/shelldiver_v0/economy.yaml"
TABLES = "examples/shelldiver_v0/luban_exports"


def _write_sample_run(tmp_path, name="run"):
    model = ModelBuilder.build(ConfigLoader.load(CONFIG, TABLES))
    result = Simulator(model).run_scenario("day_1_progression")
    run_dir = tmp_path / name
    OutputWriter.write_all(result, run_dir, model)
    return run_dir


def test_extract_metrics_from_run_artifacts(tmp_path):
    run_dir = _write_sample_run(tmp_path)

    metrics = extract_metrics(run_dir)

    assert metrics["scenario_id"] == "day_1_progression"
    assert "casual" in metrics["final_resources"]
    assert "fish" in metrics["final_resources"]["casual"]
    assert metrics["unlock_times"]["casual"]["generator:fisherman"] == 0
    assert metrics["purchase_counts"]["optimizer"]["generator:fisherman"] > 0
    assert "optimizer" in metrics["payback_seconds"]


def test_compare_runs_writes_json_and_html(tmp_path):
    base = _write_sample_run(tmp_path, "base")
    candidate = _write_sample_run(tmp_path, "candidate")
    out_dir = tmp_path / "compare"

    index = compare_runs(base, candidate, out_dir)

    comparison = json.loads((out_dir / "comparison.json").read_text(encoding="utf-8"))
    assert index == out_dir / "index.html"
    assert comparison["base"]["scenario_id"] == "day_1_progression"
    assert "final_resource_delta" in comparison["deltas"]
    assert "unlock_time_delta_seconds" in comparison["deltas"]
    assert "fisherman" in index.read_text(encoding="utf-8")


def test_cli_compare_generates_comparison_report(tmp_path):
    base = _write_sample_run(tmp_path, "base")
    candidate = _write_sample_run(tmp_path, "candidate")
    out_dir = tmp_path / "compare-cli"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "igess.cli",
            "compare",
            "--base",
            str(base),
            "--candidate",
            str(candidate),
            "--out",
            str(out_dir),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "Wrote comparison report" in result.stdout
    assert (out_dir / "comparison.json").exists()


def test_parse_scan_parameter_expands_inclusive_range():
    parameter = parse_scan_parameter("generators.fisherman.cost_growth=1.14..1.15:0.01")

    assert parameter.table == "generators"
    assert parameter.row_id == "fisherman"
    assert parameter.field == "cost_growth"
    assert parameter.values == ["1.14", "1.15"]


def test_run_scan_writes_variant_runs_and_summary(tmp_path):
    out_dir = tmp_path / "scan"

    summary_path = run_scan(
        CONFIG,
        TABLES,
        "day_1_progression",
        "generators.fisherman.cost_growth=1.14..1.15:0.01",
        out_dir,
    )

    summary = json.loads((out_dir / "scan.json").read_text(encoding="utf-8"))
    assert summary_path == out_dir / "summary.csv"
    assert summary["scenario_id"] == "day_1_progression"
    assert [row["value"] for row in summary["variants"]] == ["1.14", "1.15"]
    assert (out_dir / "variant_1_14" / "timeline.json").exists()
    manifest = json.loads(
        (out_dir / "variant_1_14" / "run_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["overrides"] == ["generators.fisherman.cost_growth=1.14"]
    assert "variant_id,value,profile_id,final_total_cps" in summary_path.read_text(encoding="utf-8")


def test_cli_scan_generates_summary(tmp_path):
    out_dir = tmp_path / "scan-cli"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "igess.cli",
            "scan",
            "--config",
            CONFIG,
            "--tables",
            TABLES,
            "--scenario",
            "day_1_progression",
            "--param",
            "generators.fisherman.cost_growth=1.14..1.15:0.01",
            "--out",
            str(out_dir),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "Wrote scan summary" in result.stdout
    assert (out_dir / "scan.json").exists()


def _write_gate_config(tmp_path, threshold):
    config_text = open(CONFIG, encoding="utf-8").read()
    path = tmp_path / "gate.yaml"
    path.write_text(
        config_text
        + f"""

regression_gates:
  day_1_progression:
    max_payback_seconds:
      generator:fisherman: {threshold}
""",
        encoding="utf-8",
        newline="\n",
    )
    return path


def test_evaluate_gates_writes_pass_and_fail_results(tmp_path):
    base = _write_sample_run(tmp_path, "base")
    candidate = _write_sample_run(tmp_path, "candidate")

    passing = evaluate_gates(base, candidate, _write_gate_config(tmp_path, 999999), tmp_path / "pass")
    failing = evaluate_gates(base, candidate, _write_gate_config(tmp_path, 0), tmp_path / "fail")

    assert passing.ok
    assert not failing.ok
    assert "generator:fisherman" in failing.failures[0]["key"]
    assert (tmp_path / "fail" / "gate_results.json").exists()
    assert "FAILED" in (tmp_path / "fail" / "gate_results.md").read_text(encoding="utf-8")


def test_cli_gate_uses_exit_code_for_threshold_failures(tmp_path):
    base = _write_sample_run(tmp_path, "base")
    candidate = _write_sample_run(tmp_path, "candidate")
    config_path = _write_gate_config(tmp_path, 0)
    out_dir = tmp_path / "gate-cli"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "igess.cli",
            "gate",
            "--base",
            str(base),
            "--candidate",
            str(candidate),
            "--config",
            str(config_path),
            "--out",
            str(out_dir),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "Regression gates failed" in result.stdout
    assert (out_dir / "gate_results.json").exists()
