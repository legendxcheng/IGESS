from decimal import Decimal
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from igess.numbers import SimNumber
from igess.stone_role_level import build_role_level_curve, write_role_level_artifacts


STONE_DATAS = Path(r"E:\stone-oasis\data-tables\Datas")
pytestmark = pytest.mark.external_data


def test_build_role_level_curve_uses_runtime_power_formula():
    result = build_role_level_curve(
        STONE_DATAS / "RoleLv.xlsx",
        STONE_DATAS / "CharacterAttributeDef.xlsx",
    )

    assert len(result.rows) == 300
    assert result.rows[0].level == 1
    assert result.rows[0].combat_power == Decimal("4310")
    assert result.rows[-1].level == 300
    assert result.rows[-1].combat_power == Decimal("1067640000000004000")
    assert result.rows[-1].cumulative_exp_to_level_start == Decimal(
        "3524128815480423707430567"
    )


def test_role_level_curve_uses_igess_sim_number_backend():
    result = build_role_level_curve(
        STONE_DATAS / "RoleLv.xlsx",
        STONE_DATAS / "CharacterAttributeDef.xlsx",
    )

    first = result.rows[0]
    last = result.rows[-1]
    assert isinstance(first.exp_req, SimNumber)
    assert isinstance(last.cumulative_exp_to_level_start, SimNumber)
    assert isinstance(last.combat_power, SimNumber)
    assert last.combat_power.backend == "bignum_log"


def test_write_role_level_artifacts_creates_auditable_outputs(tmp_path):
    result = build_role_level_curve(
        STONE_DATAS / "RoleLv.xlsx",
        STONE_DATAS / "CharacterAttributeDef.xlsx",
    )

    write_role_level_artifacts(result, tmp_path)

    curve_path = tmp_path / "role_level_curve.json"
    assert curve_path.exists()
    assert (tmp_path / "role_level_curve.csv").exists()
    summary_path = tmp_path / "role_level_summary.md"
    assert summary_path.exists()
    manifest_path = tmp_path / "source_manifest.json"
    assert manifest_path.exists()

    rows = json.loads(curve_path.read_text(encoding="utf-8"))
    assert len(rows) == 300
    assert "Level count: 300" in summary_path.read_text(encoding="utf-8")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["number_backend"] == "bignum_log"


def test_cli_stone_role_level_writes_artifacts(tmp_path):
    env = dict(os.environ)
    src_path = str(Path(__file__).resolve().parents[1] / "src")
    env["PYTHONPATH"] = (
        src_path
        if not env.get("PYTHONPATH")
        else src_path + os.pathsep + env["PYTHONPATH"]
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "igess.cli",
            "stone-role-level",
            "--role-lv",
            str(STONE_DATAS / "RoleLv.xlsx"),
            "--attribute-def",
            str(STONE_DATAS / "CharacterAttributeDef.xlsx"),
            "--out",
            str(tmp_path),
        ],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "Wrote stone role level model" in result.stdout
    assert (tmp_path / "role_level_curve.json").exists()
