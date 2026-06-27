import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from igess.advice import review_run, run_advise
from igess.builder import ModelBuilder
from igess.loader import ConfigLoader
from igess.outputs import OutputWriter
from igess.simulator import Simulator
from igess.yaml_plan import PlanValidationError, apply_yaml_plan, create_yaml_plan


CONFIG = "examples/shelldiver_v0/economy.yaml"
TABLES = "examples/shelldiver_v0/luban_exports"


def _write_sample_run(tmp_path):
    model = ModelBuilder.build(ConfigLoader.load(CONFIG, TABLES))
    result = Simulator(model).run_scenario("day_1_progression")
    run_dir = tmp_path / "run"
    OutputWriter.write_all(result, run_dir, model)
    return run_dir


def _table_hashes():
    return {
        path.as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(Path("data-tables/Datas").glob("*.xlsx"))
    }


def test_review_run_writes_advice_without_rerunning(tmp_path):
    run_dir = _write_sample_run(tmp_path)
    review_dir = tmp_path / "review"

    advice = review_run(run_dir, review_dir)

    assert advice["schema_version"] == 1
    assert advice["scenario_id"] == "day_1_progression"
    assert advice["status"] in {"ok", "needs_attention"}
    assert advice["findings"]
    assert {item["category"] for item in advice["findings"]} & {
        "invalid_content",
        "payback",
        "progression_gap",
    }
    assert advice["table_recommendations"]
    assert advice["table_recommendations"][0]["apply_mode"] == "human_only"
    assert advice["yaml_recommendations"]
    assert advice["yaml_recommendations"][0]["requires_human_approval"] is True
    assert "analysis.json" in advice["artifact_paths"]["analysis"]
    assert (review_dir / "advice.json").exists()
    assert (review_dir / "advice.md").read_text(encoding="utf-8").startswith("# IGESS Agent Advice")
    assert not (review_dir / "run").exists()


def test_advise_runs_full_loop_and_preserves_source_tables(tmp_path):
    before = _table_hashes()
    out_dir = tmp_path / "advice"

    advice = run_advise(CONFIG, TABLES, "day_1_progression", out_dir)

    assert advice["scenario_id"] == "day_1_progression"
    assert (out_dir / "run" / "timeline.json").exists()
    assert (out_dir / "report" / "index.html").exists()
    assert (out_dir / "advice.json").exists()
    assert _table_hashes() == before


def test_agent_analyst_cli_commands_write_expected_artifacts(tmp_path):
    run_dir = _write_sample_run(tmp_path)
    review_dir = tmp_path / "review_cli"
    advice_dir = tmp_path / "advice_cli"

    review = subprocess.run(
        [
            sys.executable,
            "-m",
            "igess.cli",
            "review-run",
            "--run",
            str(run_dir),
            "--out",
            str(review_dir),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    advise = subprocess.run(
        [
            sys.executable,
            "-m",
            "igess.cli",
            "advise",
            "--config",
            CONFIG,
            "--tables",
            TABLES,
            "--scenario",
            "day_1_progression",
            "--out",
            str(advice_dir),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert review.returncode == 0, review.stderr
    assert advise.returncode == 0, advise.stderr
    assert "Wrote advice" in review.stdout
    assert "Wrote advice" in advise.stdout
    assert (review_dir / "advice.json").exists()
    assert (advice_dir / "run" / "run_manifest.json").exists()


def test_yaml_plan_writes_reviewable_proposal_without_editing_config(tmp_path):
    config = tmp_path / "economy.yaml"
    shutil.copyfile(CONFIG, config)
    original = config.read_text(encoding="utf-8")

    plan = create_yaml_plan(
        config,
        "Add a strict early-game gate for first prestige timing",
        tmp_path / "yaml_plan",
    )

    assert config.read_text(encoding="utf-8") == original
    assert plan["schema_version"] == 1
    assert plan["requires_human_approval"] is True
    assert plan["changes"][0]["section"].startswith("regression_gates")
    assert (tmp_path / "yaml_plan" / "yaml_plan.json").exists()
    assert (tmp_path / "yaml_plan" / "yaml_plan.md").exists()
    assert (tmp_path / "yaml_plan" / "economy.patch.yaml").exists()


def test_yaml_apply_requires_approval_and_refuses_table_paths(tmp_path):
    config = tmp_path / "economy.yaml"
    shutil.copyfile(CONFIG, config)
    plan = create_yaml_plan(config, "Add early regression gates", tmp_path / "yaml_plan")
    plan_path = tmp_path / "yaml_plan" / "yaml_plan.json"

    with pytest.raises(PlanValidationError):
        apply_yaml_plan(config, plan_path, approve=False)

    result = apply_yaml_plan(config, plan_path, approve=True, tables=TABLES)
    data = yaml.safe_load(config.read_text(encoding="utf-8"))

    assert result["status"] == "applied"
    assert result["lint"] == "passed"
    assert "regression_gates" in data

    bad_plan = dict(plan)
    bad_plan["changes"] = [
        {
            "file": "data-tables/Datas/generators.xlsx",
            "section": "tables",
            "operation": "merge",
            "value": {"bad": True},
        }
    ]
    bad_path = tmp_path / "bad_plan.json"
    bad_path.write_text(json.dumps(bad_plan), encoding="utf-8")

    with pytest.raises(PlanValidationError):
        apply_yaml_plan(config, bad_path, approve=True)


def test_yaml_cli_plan_and_apply(tmp_path):
    config = tmp_path / "economy.yaml"
    shutil.copyfile(CONFIG, config)
    out_dir = tmp_path / "yaml_cli"

    plan = subprocess.run(
        [
            sys.executable,
            "-m",
            "igess.cli",
            "yaml-plan",
            "--config",
            str(config),
            "--intent",
            "Add early regression gates",
            "--out",
            str(out_dir),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    apply = subprocess.run(
        [
            sys.executable,
            "-m",
            "igess.cli",
            "yaml-apply",
            "--config",
            str(config),
            "--plan",
            str(out_dir / "yaml_plan.json"),
            "--approve",
            "--tables",
            TABLES,
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert plan.returncode == 0, plan.stderr
    assert apply.returncode == 0, apply.stderr
    assert "Wrote YAML plan" in plan.stdout
    assert "Applied YAML plan" in apply.stdout
