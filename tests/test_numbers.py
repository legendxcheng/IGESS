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


def test_bignum_log_exposes_sign_zero_and_log10():
    positive = SimNumber.parse("1e1000000")
    negative = SimNumber.parse("-1e12")

    assert positive.backend == "bignum_log"
    assert positive.sign == 1
    assert positive.log10_abs == SimNumber.parse("1000000").decimal
    assert SimNumber.zero().sign == 0
    assert SimNumber.zero().log10_abs is None
    assert negative.sign == -1
    assert negative.log10_abs == SimNumber.parse("12").decimal


def test_bignum_log_handles_values_beyond_decimal_operation_range():
    huge = SimNumber.parse("1e1000000")

    assert huge.to_decimal_string() == "1E+1000000"
    assert (huge * SimNumber.parse("1e5")).to_decimal_string() == "1E+1000005"
    assert (huge + huge).to_decimal_string() == "2E+1000000"
    assert huge > SimNumber.parse("1e999999")


def test_sim_number_exact_decimal_comparison_ignores_log_rounding():
    assert SimNumber.parse("2.0") == SimNumber.parse("2")
    assert not (SimNumber.parse("2.0") < SimNumber.parse("2"))


def test_bignum_log_roundtrip_comparison_and_formatting_are_stable():
    roundtrip = (
        SimNumber.parse("2")
        * SimNumber.parse("1e1000000")
        / SimNumber.parse("1e1000000")
    )
    unity = SimNumber.parse("1e1000000") / SimNumber.parse("1e1000000")

    assert roundtrip.to_decimal_string() == "2"
    assert roundtrip == SimNumber.parse("2")
    assert not (roundtrip > SimNumber.parse("2"))
    assert unity.to_decimal_string() == "1"


def test_sim_number_hash_matches_custom_equality():
    assert SimNumber.parse("2.0") == SimNumber.parse("2")
    assert hash(SimNumber.parse("2.0")) == hash(SimNumber.parse("2"))


def test_bignum_log_decimal_property_handles_large_decimal_values():
    assert SimNumber.parse("1e1000000").decimal == SimNumber.parse("1e1000000").decimal
    assert str(SimNumber.parse("1e1000000").decimal) == "1E+1000000"


def test_sim_number_to_float_keeps_finite_float_range():
    assert SimNumber.parse("1.1e308").to_float() == float("1.1e308")
