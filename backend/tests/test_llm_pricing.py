"""`cost_for`: a model missing from the rate table must yield `None`, never
a guessed number (the P3 plan's own framing — a confidently wrong cost is
worse than a blank one for a product whose whole claim is trustworthy
reporting).
"""

from __future__ import annotations

import logging
from decimal import Decimal

from app.llm.base import TokenUsage
from app.llm.pricing import cost_for


def test_known_model_computes_cost_from_the_rate_table() -> None:
    usage = TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000)
    cost = cost_for("gemini-3.1-flash-lite", usage)
    assert cost == Decimal("0.375")  # $0.075 (in) + $0.30 (out) per the table


def test_small_token_counts_still_produce_a_nonzero_cost() -> None:
    usage = TokenUsage(input_tokens=1_000, output_tokens=200)
    cost = cost_for("gemini-3.1-flash-lite", usage)
    assert cost is not None
    assert cost > Decimal("0")


def test_unrecognized_model_returns_none_not_zero() -> None:
    usage = TokenUsage(input_tokens=100, output_tokens=50)
    assert cost_for("some/unpriced-model:free", usage) is None


def test_none_model_returns_none() -> None:
    assert cost_for(None, TokenUsage(input_tokens=100, output_tokens=50)) is None


def test_none_usage_returns_none() -> None:
    assert cost_for("gemini-3.1-flash-lite", None) is None


def test_unrecognized_model_logs_a_warning_exactly_once(caplog) -> None:
    usage = TokenUsage(input_tokens=10, output_tokens=5)
    with caplog.at_level(logging.WARNING, logger="agent_ops.llm.pricing"):
        cost_for("brand-new-unpriced-model", usage)
        cost_for("brand-new-unpriced-model", usage)

    warnings = [r for r in caplog.records if "pricing_unknown_model" in r.message]
    assert len(warnings) == 1
