import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from igess.numbers import SimNumber
from igess.stone_role_level import (
    build_realm_progression_curve,
    write_realm_progression_artifacts,
)


STONE_DATAS = Path(r"E:\stone-oasis\data-tables\Datas")
pytestmark = pytest.mark.external_data


def test_build_realm_progression_curve_keeps_realm_power_independent():
    result = build_realm_progression_curve(
        STONE_DATAS / "RoleRealm.xlsx",
        STONE_DATAS / "CharacterAttributeDef.xlsx",
    )

    assert len(result.rows) == 31
    assert result.rows[0].realm_id == 0
    assert result.rows[0].realm_name == "凡人"
    assert result.rows[0].level_cap == 10
    assert result.rows[0].realm_combat_power == SimNumber.zero()
    assert result.rows[0].realm_combat_power_delta is None
    assert result.rows[1].realm_id == 1
    assert result.rows[1].realm_name == "炼气"
    assert result.rows[1].realm_combat_power == SimNumber.parse("360000")
    assert result.rows[-2].realm_id == 29
    assert result.rows[-2].realm_combat_power == SimNumber.parse("5400000000000000000")
    assert result.rows[-1].realm_id == 30
    assert result.rows[-1].realm_name == "金仙后期"
    assert result.rows[-1].realm_combat_power == SimNumber.parse("3600000000000000000")
    assert result.rows[-1].realm_combat_power_delta == SimNumber.parse(
        "-1800000000000000000"
    )


def test_write_realm_progression_artifacts_creates_separate_realm_outputs(tmp_path):
    result = build_realm_progression_curve(
        STONE_DATAS / "RoleRealm.xlsx",
        STONE_DATAS / "CharacterAttributeDef.xlsx",
    )

    write_realm_progression_artifacts(result, tmp_path)

    curve_path = tmp_path / "realm_progression_curve.json"
    assert curve_path.exists()
    assert (tmp_path / "realm_progression_curve.csv").exists()
    summary_path = tmp_path / "realm_progression_summary.md"
    assert summary_path.exists()
    manifest_path = tmp_path / "source_manifest.json"
    assert manifest_path.exists()

    rows = json.loads(curve_path.read_text(encoding="utf-8"))
    assert len(rows) == 31
    assert rows[0] == {
        "realm_id": 0,
        "realm_name": "凡人",
        "level_cap": 10,
        "realm_combat_power": "0",
        "realm_combat_power_delta": None,
    }
    assert "combat_power" not in rows[0]
    assert "level_combat_power" not in rows[0]
    summary = summary_path.read_text(encoding="utf-8")
    assert "Realm count: 31" in summary
    assert "Level combat power is not included" in summary
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["model"] == "realm_progression_baseline"
    assert manifest["number_backend"] == "bignum_log"
    assert manifest["sources"]["role_realm"] == str(STONE_DATAS / "RoleRealm.xlsx")


def test_cli_stone_realm_progression_writes_artifacts(tmp_path):
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
            "stone-realm-progression",
            "--role-realm",
            str(STONE_DATAS / "RoleRealm.xlsx"),
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
    assert "Wrote stone realm progression model" in result.stdout
    assert (tmp_path / "realm_progression_curve.json").exists()
