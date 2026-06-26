import pytest

from igess.formula import FormulaCompileError, FormulaEngine
from igess.numbers import SimNumber


def test_formula_engine_compiles_and_evaluates_exponential_cost():
    compiled = FormulaEngine.compile(
        formula_id="exponential_cost",
        args=["base_cost", "growth", "owned"],
        expr="base_cost * pow(growth, owned)",
    )

    result = compiled(
        {
            "base_cost": SimNumber.parse("10"),
            "growth": SimNumber.parse("1.15"),
            "owned": SimNumber.parse("2"),
        }
    )

    assert result.to_decimal_string() == "13.225"


@pytest.mark.parametrize(
    "expr",
    [
        "__import__('os').system('echo bad')",
        "open('x')",
        "base_cost.__class__",
        "base_cost + missing_arg",
    ],
)
def test_formula_engine_rejects_unsafe_or_unknown_expressions(expr):
    with pytest.raises(FormulaCompileError):
        FormulaEngine.compile(
            formula_id="bad_formula",
            args=["base_cost"],
            expr=expr,
        )
