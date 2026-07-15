import pytest

from igess.human_numbers import format_human_number, human_number


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ("", ""),
        ("0", "0"),
        ("-0", "0"),
        ("999999", "999999"),
        ("999999.5", "1000000"),
        ("1000000", "1e6"),
        ("0.0001", "0.0001"),
        ("0.00009999995", "1e-4"),
        ("0.0000123456789", "1.23457e-5"),
        ("739.864019013290554", "739.864"),
        ("-999999", "-999999"),
        ("-999999.5", "-1000000"),
        ("-1000000", "-1e6"),
        ("-0.0001", "-0.0001"),
        ("-0.00009999995", "-1e-4"),
        ("-0.0000123456789", "-1.23457e-5"),
        ("-739.864019013290554", "-739.864"),
        ("1.234565", "1.23456"),
        ("1.234575", "1.23458"),
        ("1067640000000004000", "1.06764e18"),
        ("1e+0007", "1e7"),
        ("Infinity", "Infinity"),
        ("-Infinity", "-Infinity"),
        ("NaN", "NaN"),
    ],
)
def test_format_human_number_uses_six_significant_digits(value, expected):
    assert format_human_number(value) == expected


def test_human_number_keeps_exact_and_display_values_separate():
    assert human_number("1000000") == {
        "exact_value": "1000000",
        "display_value": "1e6",
    }


def test_thousand_digit_finite_number_does_not_overflow_through_float():
    value = "9" * 1000

    assert format_human_number(value) == "1e1000"
