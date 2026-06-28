from __future__ import annotations

import ast
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal

from .numbers import SimNumber


class FormulaCompileError(ValueError):
    pass


AllowedContext = Mapping[str, SimNumber]


@dataclass(frozen=True)
class CompiledFormula:
    formula_id: str
    args: tuple[str, ...]
    expr: str
    tree: ast.Expression

    def __call__(self, values: AllowedContext) -> SimNumber:
        missing = [arg for arg in self.args if arg not in values]
        if missing:
            raise FormulaCompileError(
                f"formula {self.formula_id} missing values for {', '.join(missing)}"
            )
        return FormulaEngine.evaluate_node(self.tree.body, values)


class FormulaEngine:
    ALLOWED_FUNCTIONS: dict[str, Callable[..., SimNumber]] = {}

    @classmethod
    def compile(cls, formula_id: str, args: list[str] | tuple[str, ...], expr: str) -> CompiledFormula:
        try:
            tree = ast.parse(cls._normalize_expr(expr), mode="eval")
        except SyntaxError as exc:
            raise FormulaCompileError(f"formula {formula_id} syntax error: {exc}") from exc
        allowed_names = set(args)
        cls._validate_node(formula_id, tree, allowed_names)
        return CompiledFormula(formula_id, tuple(args), expr, tree)

    @classmethod
    def referenced_names(cls, expr: str) -> set[str]:
        tree = ast.parse(cls._normalize_expr(expr), mode="eval")
        return {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}

    @staticmethod
    def _normalize_expr(expr: str) -> str:
        return expr.replace("^", "**")

    @classmethod
    def _validate_node(cls, formula_id: str, node: ast.AST, allowed_names: set[str]) -> None:
        for child in ast.walk(node):
            if isinstance(child, ast.Expression | ast.Load):
                continue
            if isinstance(child, ast.Constant):
                if isinstance(child.value, str):
                    raise FormulaCompileError(f"formula {formula_id} disallows string constants")
                if not isinstance(child.value, int | float):
                    raise FormulaCompileError(f"formula {formula_id} has unsupported constant")
                continue
            if isinstance(child, ast.Name):
                if child.id not in allowed_names and child.id not in cls.allowed_function_names():
                    raise FormulaCompileError(
                        f"formula {formula_id} unknown formula name '{child.id}'"
                    )
                continue
            if isinstance(child, ast.Call):
                if not isinstance(child.func, ast.Name):
                    raise FormulaCompileError(f"formula {formula_id} disallows dynamic calls")
                if child.func.id not in cls.allowed_function_names():
                    raise FormulaCompileError(
                        f"formula {formula_id} disallows function '{child.func.id}'"
                    )
                continue
            if isinstance(child, ast.BinOp):
                if not isinstance(child.op, ast.Add | ast.Sub | ast.Mult | ast.Div | ast.Pow):
                    raise FormulaCompileError(f"formula {formula_id} disallows operator")
                continue
            if isinstance(child, ast.UnaryOp):
                if not isinstance(child.op, ast.UAdd | ast.USub):
                    raise FormulaCompileError(f"formula {formula_id} disallows unary operator")
                continue
            if isinstance(child, ast.Add | ast.Sub | ast.Mult | ast.Div | ast.Pow | ast.UAdd | ast.USub):
                continue
            raise FormulaCompileError(
                f"formula {formula_id} disallows syntax {child.__class__.__name__}"
            )

    @classmethod
    def evaluate_node(cls, node: ast.AST, values: AllowedContext) -> SimNumber:
        if isinstance(node, ast.Constant):
            return SimNumber.parse(str(node.value))
        if isinstance(node, ast.Name):
            return values[node.id]
        if isinstance(node, ast.UnaryOp):
            value = cls.evaluate_node(node.operand, values)
            if isinstance(node.op, ast.USub):
                return -value
            return value
        if isinstance(node, ast.BinOp):
            left = cls.evaluate_node(node.left, values)
            right = cls.evaluate_node(node.right, values)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
            if isinstance(node.op, ast.Pow):
                return left ** right
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            fn = cls.ALLOWED_FUNCTIONS[node.func.id]
            args = [cls.evaluate_node(arg, values) for arg in node.args]
            return fn(*args)
        raise FormulaCompileError(f"cannot evaluate node {node.__class__.__name__}")

    @classmethod
    def allowed_function_names(cls) -> set[str]:
        return {"pow", "floor", "ceil", "min", "max", "log10"}


def _pow(base: SimNumber, exponent: SimNumber) -> SimNumber:
    return base ** exponent


def _floor(value: SimNumber) -> SimNumber:
    return value.floor()


def _ceil(value: SimNumber) -> SimNumber:
    return value.ceil()


def _min(*values: SimNumber) -> SimNumber:
    return min(values)


def _max(*values: SimNumber) -> SimNumber:
    return max(values)


def _log10(value: SimNumber) -> SimNumber:
    if value.decimal <= 0:
        raise ValueError("log10 requires a positive argument")
    return SimNumber.from_decimal(value.decimal.log10().quantize(Decimal("0.0000000001")))


FormulaEngine.ALLOWED_FUNCTIONS = {
    "pow": _pow,
    "floor": _floor,
    "ceil": _ceil,
    "min": _min,
    "max": _max,
    "log10": _log10,
}
