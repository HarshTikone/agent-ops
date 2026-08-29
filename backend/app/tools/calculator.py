"""Calculator tool (ADR-011, ADR-020): a deterministic arithmetic evaluator.

Not `eval()` — expressions are parsed to an AST and walked by hand, allowing
only numeric literals, the arithmetic operators, and a small allow-list of
functions. This is deliberate, not defense-in-depth theater: `run()` is
reachable from whatever the planner LLM decides to pass as `expression`, so
this is effectively an LLM-controlled input string reaching Python — an AST
allow-list makes "what can this evaluate" a closed, auditable set instead of
"anything Python can execute."

The allow-list closes *code execution*; it does nothing about *resource
exhaustion* on its own. `9**9**9` is fully expressible with only allow-listed
nodes and pins a CPU/thread indefinitely computing a number with hundreds of
millions of digits — verified live (ADR-020): it did not return within an
8-second bound. `_MAX_EXPRESSION_LENGTH`, `_MAX_AST_DEPTH`, and
`_check_pow_bounds` close that gap.
"""

from __future__ import annotations

import ast
import math
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

# LLM-controlled input reaching Python needs bounds on more than just WHICH
# operations are allowed — also on how much work any single evaluation can
# demand (ADR-020). All three verified live against the exact inputs they
# name, not assumed from the shape of the risk:
#   - a 10,000-character expression: rejected before ast.parse ever runs.
#   - `9**9**9`: base**exponent estimated at ~1.2 billion bits, rejected by
#     _check_pow_bounds before operator.pow is ever called.
#   - a 5,000-term flat `+` chain: raised a raw RecursionError *during
#     ast.parse itself* (not even reaching _eval_node's own walk) — confirmed
#     the length cap alone prevents it from ever reaching the parser, and
#     RecursionError is now caught explicitly at both the parse and eval call
#     sites as defense in depth regardless.
_MAX_EXPRESSION_LENGTH = 500
_MAX_AST_DEPTH = 50
_MAX_POW_RESULT_BITS = 4096  # ~10**1233 -- far beyond any real calculator use


class CalculatorArgs(BaseModel):
    expression: str = Field(description="A numeric arithmetic expression, e.g. '(3 + 4) * 2'")


def _check_pow_bounds(base: float, exponent: float) -> None:
    """Rejects a `base ** exponent` whose result would be enormous, checked
    BEFORE `operator.pow` is ever called — an estimate from `log2`, not a
    post-hoc check on an already-computed (and already-expensive) result.
    Non-integer operands are left to Python's own float overflow handling
    (already caught as `OverflowError` by `CalculatorTool.run`); the
    unbounded-integer case is the one this project actually observed hang.
    """
    if not isinstance(base, int) or not isinstance(exponent, int):
        return
    if abs(base) <= 1:
        return  # magnitude never grows past 1, whatever the exponent
    if exponent <= 0:
        return
    estimated_bits = exponent * math.log2(abs(base))
    if estimated_bits > _MAX_POW_RESULT_BITS:
        raise ToolError(
            f"result of {base!r} ** {exponent!r} would be too large "
            f"(estimated {estimated_bits:.0f} bits, max {_MAX_POW_RESULT_BITS})",
            transient=False,
        )


def _eval_node(node: ast.AST, depth: int = 0) -> float:
    if depth > _MAX_AST_DEPTH:
        raise ToolError(
            f"expression too deeply nested (max depth {_MAX_AST_DEPTH})", transient=False
        )
    if isinstance(node, ast.Constant):
        if isinstance(node.value, int | float) and not isinstance(node.value, bool):
            return node.value
        raise ToolError(f"unsupported constant: {node.value!r}", transient=False)
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
        left = _eval_node(node.left, depth + 1)
        right = _eval_node(node.right, depth + 1)
        if type(node.op) is ast.Pow:
            _check_pow_bounds(left, right)
        return _BINARY_OPERATORS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
        return _UNARY_OPERATORS[type(node.op)](_eval_node(node.operand, depth + 1))
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in _FUNCTIONS
    ):
        args = [_eval_node(arg, depth + 1) for arg in node.args]
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

    def invoke(self, arguments: dict[str, object]) -> str:
        args = self.args_schema.model_validate(arguments)
        return self.run(expression=args.expression)

    def run(self, *, expression: str) -> str:
        if len(expression) > _MAX_EXPRESSION_LENGTH:
            raise ToolError(
                f"expression too long ({len(expression)} chars, max {_MAX_EXPRESSION_LENGTH})",
                transient=False,
            )
        try:
            tree = ast.parse(expression, mode="eval")
        except SyntaxError as exc:
            raise ToolError(
                f"could not parse expression {expression!r}: {exc}", transient=False
            ) from exc
        except RecursionError as exc:
            raise ToolError(
                f"expression too complex to parse: {expression[:50]!r}...", transient=False
            ) from exc
        try:
            result = _eval_node(tree.body)
        except ZeroDivisionError as exc:
            raise ToolError(f"division by zero in {expression!r}", transient=False) from exc
        except ToolError:
            raise
        except RecursionError as exc:
            raise ToolError(
                f"expression too deeply nested to evaluate: {expression[:50]!r}...", transient=False
            ) from exc
        except (TypeError, OverflowError, ValueError) as exc:
            raise ToolError(f"evaluation error in {expression!r}: {exc}", transient=False) from exc
        return str(result)
