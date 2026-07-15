from __future__ import annotations

import subprocess
import sys

import pytest

from igess.scan import parse_scan_parameter


CONFIG = "examples/shelldiver_v0/economy.yaml"
TABLES = "examples/shelldiver_v0/luban_exports"
SYNTAX = "PATH=START..STOP:STEP"
EXAMPLE = "generators.fisherman.cost_growth=1.14..1.18:0.01"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "igess.cli", *args],
        check=False,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize(
    "spec",
    [
        "bad",
        "=1..2:1",
        "a=",
        "a=1",
        "a=1..2",
        "a=1..2:",
        "a=x..2:1",
        "a=1..x:1",
        "a=1..2:x",
        "a=1..2:0",
        "a=2..1:1",
        "a=1..2:-1",
        "a..b=1..2:1",
        "a.b.c=1...2:-1",
        "a.b.c=NaN..2:1",
        "a.b.c=1..Infinity:1",
        "a.b.c=1..2:-Infinity",
    ],
)
def test_parse_scan_parameter_rejects_invalid_specs_with_actionable_error(spec: str):
    with pytest.raises(ValueError) as caught:
        parse_scan_parameter(spec)

    message = str(caught.value)
    assert spec in message
    assert SYNTAX in message
    assert EXAMPLE in message


def test_parse_scan_parameter_supports_descending_ranges():
    parameter = parse_scan_parameter("generators.fisherman.cost_growth=2.0..1.0:-0.5")

    assert parameter.table == "generators"
    assert parameter.row_id == "fisherman"
    assert parameter.field == "cost_growth"
    assert parameter.values == ["2.0", "1.5", "1.0"]


def test_parse_scan_parameter_expands_large_integers_exactly():
    start = 10**80
    parameter = parse_scan_parameter(f"constants.large.value={start}..{start + 2}:1")

    assert parameter.values == [str(start), str(start + 1), str(start + 2)]


def test_parse_scan_parameter_expands_descending_large_integers_exactly():
    start = 10**80
    parameter = parse_scan_parameter(f"constants.large.value={start + 2}..{start}:-1")

    assert parameter.values == [str(start + 2), str(start + 1), str(start)]


def test_parse_scan_parameter_rejects_a_single_extremely_wide_value():
    spec = "constants.large.value=1e+10000..2e+10000:1e+10000"

    with pytest.raises(ValueError) as caught:
        parse_scan_parameter(spec)

    message = str(caught.value)
    assert spec in message
    assert "too large" in message
    assert SYNTAX in message


def test_parse_scan_parameter_rejects_excessive_total_output_size():
    start_text = "1" + "0" * 1000
    end_text = str(int(start_text) + 999)
    spec = f"constants.large.value={start_text}..{end_text}:1"

    with pytest.raises(ValueError, match="too large"):
        parse_scan_parameter(spec)


def test_parse_scan_parameter_accepts_exactly_variant_cap_values():
    parameter = parse_scan_parameter("constants.value.amount=0..999:1")

    assert len(parameter.values) == 1000
    assert parameter.values[0] == "0"
    assert parameter.values[-1] == "999"


def test_parse_scan_parameter_rejects_one_over_variant_cap():
    with pytest.raises(ValueError, match="too many variants"):
        parse_scan_parameter("constants.value.amount=0..1000:1")


def test_parse_scan_parameter_stops_before_non_divisible_descending_endpoint():
    parameter = parse_scan_parameter("constants.value.amount=5..0:-2")

    assert parameter.values == ["5", "3", "1"]


def test_parse_scan_parameter_preserves_trailing_precision():
    parameter = parse_scan_parameter("constants.value.amount=1.00..1.02:0.01")

    assert parameter.values == ["1.00", "1.01", "1.02"]


def test_parse_scan_parameter_does_not_expand_zero_positive_exponent():
    parameter = parse_scan_parameter("constants.value.amount=0e+10000..0:1")

    assert parameter.values == ["0"]


@pytest.mark.parametrize("spec", ["bad", "a.b.c=NaN..2:1", "a.b.c=2..1:1"])
def test_cli_scan_reports_invalid_parameter_without_traceback(tmp_path, spec: str):
    result = run_cli(
        "scan",
        "--config",
        CONFIG,
        "--tables",
        TABLES,
        "--scenario",
        "day_1_progression",
        "--param",
        spec,
        "--out",
        str(tmp_path / "scan"),
    )

    assert result.returncode == 1
    assert spec in result.stderr
    assert SYNTAX in result.stderr
    assert EXAMPLE in result.stderr
    assert "Traceback" not in result.stderr
