"""CalculatorTool: happy path plus every failure mode it can hit."""

import pytest

from app.tools.calculator import CalculatorTool
from app.tools.errors import ToolError


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
