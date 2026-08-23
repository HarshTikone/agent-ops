"""Calculator tool (ADR-011): a deterministic arithmetic evaluator.

Not `eval()` — expressions are parsed to an AST and walked by hand, allowing
only numeric literals, the arithmetic operators, and a small allow-list of
functions. This is deliberate, not defense-in-depth theater: `run()` is
reachable from whatever the planner LLM decides to pass as `expression`, so
this is effectively an LLM-controlled input string reaching Python — an AST
allow-list makes "what can this evaluate" a closed, auditable set instead of
"anything Python can execute."
"""

from __future__ import annotations

import ast
import operator
from collections.abc import Callable

from pydantic import BaseModel, Field

from app.tools.errors import ToolError

_BINARY_OPERATORS: dict[type[ast.AST], Callable[[float, float], float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.FloorDiv: operator.floordiv,
}
_UNARY_OPERATORS: dict[type[ast.AST], Callable[[float], float]] = {
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}
_FUNCTIONS: dict[str, Callable[..., float]] = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
}


class CalculatorArgs(BaseModel):
    expression: str = Field(description="A numeric arithmetic expression, e.g. '(3 + 4) * 2'")


def _eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, int | float) and not isinstance(node.value, bool):
            return node.value
        raise ToolError(f"unsupported constant: {node.value!r}", transient=False)
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        return _BINARY_OPERATORS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
        return _UNARY_OPERATORS[type(node.op)](_eval_node(node.operand))
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in _FUNCTIONS
    ):
        args = [_eval_node(arg) for arg in node.args]
        return _FUNCTIONS[node.func.id](*args)
    raise ToolError(f"disallowed expression element: {ast.dump(node)}", transient=False)


class CalculatorTool:
    name = "calculator"
    description = (
        "Evaluate a deterministic arithmetic expression (+ - * / % ** // and "
        "abs/round/min/max). Use this for any exact numeric computation "
        "instead of computing it yourself."
    )
    args_schema = CalculatorArgs

    def run(self, *, expression: str) -> str:
        try:
            tree = ast.parse(expression, mode="eval")
        except SyntaxError as exc:
            raise ToolError(
                f"could not parse expression {expression!r}: {exc}", transient=False
            ) from exc
        try:
            result = _eval_node(tree.body)
        except ZeroDivisionError as exc:
            raise ToolError(f"division by zero in {expression!r}", transient=False) from exc
        except ToolError:
            raise
        except (TypeError, OverflowError, ValueError) as exc:
            raise ToolError(f"evaluation error in {expression!r}: {exc}", transient=False) from exc
        return str(result)
