import json
import os
import subprocess
import sys
import hashlib
from pathlib import Path

import pytest

from igess.verification import review_proposal, verify_edits


CONFIG = "examples/shelldiver_v0/economy.yaml"
TABLES = "examples/shelldiver_v0/luban_exports"
DATAS = "data-tables/Datas"


def _write_json(path, payload):
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _subprocess_env():
    env = dict(os.environ)
    src_path = str(Path.cwd() / "src")
    current = env.get("PYTHONPATH")
    env["PYTHONPATH"] = src_path if not current else os.pathsep.join([src_path, current])
    return env


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_generator_proposal(tmp_path, suggested_value):
    proposal_path = tmp_path / "proposal.json"
    _write_json(
        proposal_path,
        {
            "schema_version": 1,
            "scenario_id": "day_1_progression",
            "recommendations": [
                {
                    "table": "generators",
                    "workbook": "generators.xlsx",
                    "row_id": "fisherman",
                    "field": "cost_growth",
                    "current_value": "1.15",
                    "suggested_value": suggested_value,
                    "reason": "Test recommendation.",
                    "apply_mode": "human_only",
                }
            ],
        },
    )
    return proposal_path


def test_review_proposal_normalizes_advice_recommendations(tmp_path):
    proposal_path = tmp_path / "advice.json"
    _write_json(
        proposal_path,
        {
            "schema_version": 1,
            "scenario_id": "day_1_progression",
            "table_recommendations": [
                {
                    "id": "table.generators.fisherman.cost_growth",
                    "kind": "table_recommendation",
                    "table": "generators",
                    "workbook": "generators.xlsx",
                    "row_id": "fisherman",
                    "field": "cost_growth",
                    "current_value": "1.15",
                    "suggested_value": "1.13",
                    "reason": "Reduce early gap.",
                    "apply_mode": "human_only",
                }
            ],
        },
    )

    review = review_proposal(proposal_path, tmp_path / "review")

    assert review["recommendation_count"] == 1
    recommendation = review["recommendations"][0]
    assert recommendation["id"] == "table.generators.fisherman.cost_growth"
    assert recommendation["table"] == "generators"
    assert recommendation["workbook"] == "generators.xlsx"
    assert recommendation["row_id"] == "fisherman"
    assert recommendation["field"] == "cost_growth"
    assert recommendation["suggested_value"] == "1.13"
    assert recommendation["apply_mode"] == "human_only"
    assert (tmp_path / "review" / "proposal_review.json").exists()
    markdown = (tmp_path / "review" / "proposal_review.md").read_text(encoding="utf-8")
    assert "generators.xlsx" in markdown


def test_review_proposal_normalizes_tuning_candidate_changes(tmp_path):
    proposal_path = tmp_path / "tuning_report.json"
    _write_json(
        proposal_path,
        {
            "schema_version": 1,
            "scenario_id": "day_1_progression",
            "best_candidates": [
                {
                    "candidate_id": "cand_0001",
                    "changes": [
                        {
                            "table": "generators",
                            "workbook": "generators.xlsx",
                            "row_id": "fisherman",
                            "field": "cost_growth",
                            "current_value": "1.15",
                            "suggested_value": "1.13",
                            "apply_mode": "human_only",
                        }
                    ],
                }
            ],
        },
    )

    review = review_proposal(proposal_path, tmp_path / "review")

    assert review["recommendation_count"] == 1
    recommendation = review["recommendations"][0]
    assert recommendation["candidate_id"] == "cand_0001"
    assert recommendation["id"] == "table.generators.fisherman.cost_growth"


@pytest.mark.parametrize(
    ("suggested_value", "expected_report_status", "expected_check_status"),
    [
        ("1.15", "passed", "matched"),
        ("1.14 - 1.16", "passed", "matched"),
        ("review a 5-10% softer early-game value", "needs_review", "needs_manual_review"),
        ("1.13", "failed", "mismatched"),
    ],
)
def test_verify_edits_checks_exported_table_values(
    tmp_path,
    suggested_value,
    expected_report_status,
    expected_check_status,
):
    proposal_path = _write_generator_proposal(tmp_path, suggested_value)

    report = verify_edits(
        CONFIG,
        proposal_path,
        "day_1_progression",
        tmp_path / "verify",
        tables=TABLES,
    )

    assert report["status"] == expected_report_status
    assert report["table_checks"][0]["status"] == expected_check_status
    assert report["table_checks"][0]["actual"] == "1.15"
    assert (tmp_path / "verify" / "run" / "run_manifest.json").exists()
    assert (tmp_path / "verify" / "verification_report.json").exists()


def test_verify_edits_exports_datas_without_modifying_source_workbooks(tmp_path):
    proposal_path = _write_generator_proposal(tmp_path, "1.15")
    workbook = Path(DATAS) / "generators.xlsx"
    before = _sha256(workbook)

    report = verify_edits(
        CONFIG,
        proposal_path,
        "day_1_progression",
        tmp_path / "verify",
        datas=DATAS,
    )

    assert report["status"] == "passed"
    assert (tmp_path / "verify" / "exported_tables" / "generators.json").exists()
    assert _sha256(workbook) == before


def test_cli_review_proposal_writes_review(tmp_path):
    proposal_path = _write_generator_proposal(tmp_path, "1.15")
    out_dir = tmp_path / "review-cli"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "igess.cli",
            "review-proposal",
            "--proposal",
            str(proposal_path),
            "--out",
            str(out_dir),
        ],
        check=False,
        capture_output=True,
        env=_subprocess_env(),
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "Wrote proposal review" in result.stdout
    assert (out_dir / "proposal_review.json").exists()


def test_cli_verify_edits_writes_report(tmp_path):
    proposal_path = _write_generator_proposal(tmp_path, "1.15")
    out_dir = tmp_path / "verify-cli"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "igess.cli",
            "verify-edits",
            "--config",
            CONFIG,
            "--tables",
            TABLES,
            "--proposal",
            str(proposal_path),
            "--scenario",
            "day_1_progression",
            "--out",
            str(out_dir),
        ],
        check=False,
        capture_output=True,
        env=_subprocess_env(),
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "Wrote edit verification" in result.stdout
    assert (out_dir / "verification_report.json").exists()
