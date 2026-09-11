"""Per-model USD pricing for LLM calls (P3).

A small, explicit rate table rather than a call to a pricing API or a
computed estimate: this project's whole claim is trustworthy reporting, and
a confidently wrong cost is worse than a blank one. `cost_for` returns
`None` for any model this table doesn't know about — logging once at
WARNING so the gap gets noticed — rather than guessing.
"""

from __future__ import annotations

import logging
from decimal import ROUND_HALF_UP, Decimal

from app.llm.base import TokenUsage

logger = logging.getLogger("agent_ops.llm.pricing")

_MILLION = Decimal(1_000_000)
_CENTS_PLACES = Decimal("0.000001")  # matches trace_events.cost_usd's numeric(12,6)

# USD list price per 1M tokens, as (input, output). Extend this table when a
# new model is wired up via GEMINI_MODEL/OPENROUTER_MODEL; a model missing
# here degrades to `cost_usd = NULL` rather than a wrong number.
_RATES_PER_MILLION_TOKENS: dict[str, tuple[Decimal, Decimal]] = {
    "gemini-3.1-flash-lite": (Decimal("0.075"), Decimal("0.30")),
    "gemini-3.1-flash": (Decimal("0.30"), Decimal("1.20")),
    "gemini-3.1-pro": (Decimal("1.25"), Decimal("5.00")),
}

_warned_models: set[str] = set()


def cost_for(model: str | None, usage: TokenUsage | None) -> Decimal | None:
    """Cost in USD for one `generate()` call, or `None` if it can't be priced.

    `None` covers a missing `model`, missing `usage`, and an unrecognized
    `model` alike — in every case there is no rate to multiply against, and
    the caller should render that as "unknown", never as zero.
    """
    if model is None or usage is None:
        return None
    rates = _RATES_PER_MILLION_TOKENS.get(model)
    if rates is None:
        if model not in _warned_models:
            logger.warning("pricing_unknown_model model=%s", model)
            _warned_models.add(model)
        return None
    input_rate, output_rate = rates
    raw = (
        Decimal(usage.input_tokens) * input_rate + Decimal(usage.output_tokens) * output_rate
    ) / (_MILLION)
    return raw.quantize(_CENTS_PLACES, rounding=ROUND_HALF_UP)
