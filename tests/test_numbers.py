from igess.numbers import SimNumber


def test_sim_number_preserves_large_subtraction_precision():
    value = SimNumber.parse("1e18")
    reduced = value - SimNumber.parse("10")

    assert reduced < value
    assert reduced.to_decimal_string() == "999999999999999990"


def test_sim_number_formats_deterministically():
    assert SimNumber.parse("123.4500").to_decimal_string() == "123.45"
    assert SimNumber.zero().to_decimal_string() == "0"
    assert SimNumber.parse("1e40").to_decimal_string() == "1E+40"
