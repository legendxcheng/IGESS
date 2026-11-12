"""Combined card/gun delivery and fault recovery through the real Lua host."""
import subprocess

import pytest

from test_fish_source_guns import SOURCE


@pytest.mark.skipif(not (SOURCE / 'simulation/cli.lua').exists(), reason='paired Fish checkout required')
def test_monthly_and_gun_delivery_save_gates_and_equipment_recovery():
    result = subprocess.run(
        ['lua55', 'tests/simulation_gun_delivery_test.lua'], cwd=SOURCE,
        capture_output=True, text=True, encoding='utf-8', timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count('PASS') == 4
