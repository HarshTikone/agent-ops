"""CalculatorTool: happy path plus every failure mode it can hit."""

import time

import pytest

from app.tools.calculator import CalculatorTool
from app.tools.errors import ToolError

# Generous relative to how fast these actually resolve (well under 0.01s,
# see ADR-020's live timing) but tight enough that a version which computes
# the huge result before rejecting it (defeating the whole point of C2's
# fix) would blow it -- this is a timing bug, so a bound-free "eventually
# raises ToolError" assertion would pass against a version that takes an
# hour to raise it.
_FAST_REJECTION_SECONDS = 2.0


@pytest.fixture
def calculator() -> CalculatorTool:
    return CalculatorTool()


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("2 + 2", "4"),
        ("(3 + 4) * 2", "14"),
        ("10 / 4", "2.5"),
        ("2 ** 10", "1024"),
        ("-5 + 3", "-2"),
        ("abs(-7)", "7"),
        ("round(3.14159, 2)", "3.14"),
        ("max(3, 9, 1)", "9"),
    ],
)
def test_evaluates_supported_expressions(
    calculator: CalculatorTool, expression: str, expected: str
) -> None:
    assert calculator.run(expression=expression) == expected


def test_malformed_expression_raises_permanent_tool_error(calculator: CalculatorTool) -> None:
    with pytest.raises(ToolError) as exc_info:
        calculator.run(expression="2 + * 3")
    assert exc_info.value.transient is False


def test_division_by_zero_raises_permanent_tool_error(calculator: CalculatorTool) -> None:
    with pytest.raises(ToolError) as exc_info:
        calculator.run(expression="1 / 0")
    assert exc_info.value.transient is False


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('echo pwned')",
        "open('/etc/passwd').read()",
        "[].__class__.__base__.__subclasses__()",
        "1 .bit_length()",
        "'a' + 'b'",
    ],
)
def test_disallowed_expression_elements_are_rejected(
    calculator: CalculatorTool, expression: str
) -> None:
    """The AST allow-list, not eval(), is what makes this tool safe to point
    an LLM-controlled string at — this is the test that would fail if
    someone "simplified" the implementation back to eval().
    """
    with pytest.raises(ToolError) as exc_info:
        calculator.run(expression=expression)
    assert exc_info.value.transient is False


# --- C2 (ADR-020): resource-exhaustion bounds, not just code-execution ones -


def _assert_fast_permanent_rejection(calculator: CalculatorTool, expression: str) -> None:
    start = time.monotonic()
    with pytest.raises(ToolError) as exc_info:
        calculator.run(expression=expression)
    elapsed = time.monotonic() - start
    assert exc_info.value.transient is False
    assert elapsed < _FAST_REJECTION_SECONDS, (
        f"took {elapsed:.2f}s to reject — the bound check ran too late, "
        "after doing the expensive work it exists to prevent"
    )


def test_huge_right_associative_power_is_rejected_fast(calculator: CalculatorTool) -> None:
    """The exact input that hung for 8+ seconds before this fix (ADR-020) —
    `9**9**9` parses as `9 ** (9 ** 9)`, so the inner power is small and
    legal; only the outer one is astronomically large."""
    _assert_fast_permanent_rejection(calculator, "9**9**9")


def test_power_of_a_large_inner_result_is_rejected_fast(calculator: CalculatorTool) -> None:
    _assert_fast_permanent_rejection(calculator, "2**(10**10)")


def test_very_long_expression_is_rejected_fast(calculator: CalculatorTool) -> None:
    _assert_fast_permanent_rejection(calculator, "1+" * 5000 + "1")


def test_deeply_nested_expression_is_rejected_fast_not_a_raw_recursion_error(
    calculator: CalculatorTool,
) -> None:
    """A short-but-deep expression (well under the length cap) that would
    hit Python's own recursion limit if walked without a depth counter —
    must come back as a permanent ToolError, not a raw RecursionError
    escaping past tool_call_node's `except ToolError` (M8)."""
    expression = "+".join(["1"] * 80)
    assert len(expression) < 500
    _assert_fast_permanent_rejection(calculator, expression)


def test_moderately_nested_legitimate_expression_still_works(calculator: CalculatorTool) -> None:
    expression = "+".join(["1"] * 20)
    assert calculator.run(expression=expression) == "20"
