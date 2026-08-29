"""`FailoverProvider` — the automatic Gemini -> OpenRouter fallback (ADR-002).

Composes two `LLMProvider`s: try the primary, and on a `TransientProviderError`
(timeout/5xx/rate-limit only — see `errors.py`), retry once on the fallback.
If the fallback also raises, that error propagates to the caller unchanged —
this provider does not retry the fallback itself; retry-vs-replan-vs-give-up
after that point is the graph's `decide_next` node's job (ADR-012), not this
layer's.
"""

from __future__ import annotations

import logging

from langchain_core.messages import BaseMessage
from langchain_core.tools import BaseTool

from app.llm.base import LLMProvider, LLMResponse
from app.llm.errors import TransientProviderError

logger = logging.getLogger("agent_ops.llm.failover")


class FailoverProvider:
    name = "failover"

    def __init__(self, primary: LLMProvider, fallback: LLMProvider) -> None:
        self._primary = primary
        self._fallback = fallback

    def generate(
        self, messages: list[BaseMessage], tools: list[BaseTool] | None = None
    ) -> LLMResponse:
        try:
            return self._primary.generate(messages, tools)
        except TransientProviderError as exc:
            logger.warning(
                "provider_failover from=%s to=%s reason=%s",
                self._primary.name,
                self._fallback.name,
                exc,
            )
            return self._fallback.generate(messages, tools)
