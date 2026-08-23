"""FailoverProvider (ADR-002): mock Gemini to fail, assert it lands on
OpenRouter.

Day 1 shipped four regression tests that all passed against the exact bug
they were meant to catch (ADR-007) — the lesson recorded there was that a
test which only checks "a response came back" or mocks too broadly can pass
without ever exercising the branch it claims to test. Every test below
asserts on the FAKE PROVIDER'S OWN CALL COUNT (`primary.calls`,
`fallback.calls`) and on `response.provider`, not just on `response.content`
— so a FailoverProvider that silently swallows the primary's error and
fabricates a response, or that never actually calls the fallback, cannot
pass these by accident.

Mutation-test evidence for this file is recorded in ADR-013, not here (per
ADR-007's own lesson: a test file cannot prove itself trustworthy from
inside itself).
"""

from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage

from app.llm.base import LLMResponse
from app.llm.errors import (
    ProviderRateLimitError,
    ProviderServerError,
    ProviderTimeoutError,
    TransientProviderError,
)
from app.llm.failover import FailoverProvider

MESSAGES = [HumanMessage(content="hi")]


class _FakeProvider:
    """A minimal `LLMProvider` test double. Never touches the real Gemini/
    OpenRouter translation layer (that's `test_llm_providers.py`'s job) —
    this file tests only `FailoverProvider`'s own composition logic.
    """

    def __init__(
        self, name: str, *, error: Exception | None = None, content: str | None = None
    ) -> None:
        self.name = name
        self._error = error
        self._content = content if content is not None else f"answer from {name}"
        self.calls = 0

    def generate(self, messages, tools=None) -> LLMResponse:
        self.calls += 1
        if self._error is not None:
            raise self._error
        return LLMResponse(content=self._content, tool_calls=[], provider=self.name)


class _NonTransientError(Exception):
    """Stands in for "a real bug in our own code" — anything that is not a
    `TransientProviderError`."""


@pytest.mark.parametrize(
    "transient_error",
    [
        ProviderTimeoutError("gemini timed out"),
        ProviderRateLimitError("gemini rate-limited"),
        ProviderServerError("gemini 503"),
    ],
)
def test_transient_primary_failure_falls_over_to_fallback(
    transient_error: TransientProviderError,
) -> None:
    primary = _FakeProvider("gemini", error=transient_error)
    fallback = _FakeProvider("openrouter", content="answer from openrouter, distinctly")
    failover = FailoverProvider(primary, fallback)

    response = failover.generate(MESSAGES)

    assert primary.calls == 1
    assert fallback.calls == 1
    assert response.provider == "openrouter"
    assert response.content == "answer from openrouter, distinctly"


def test_healthy_primary_never_calls_fallback() -> None:
    primary = _FakeProvider("gemini", content="answer from gemini")
    fallback = _FakeProvider("openrouter")
    failover = FailoverProvider(primary, fallback)

    response = failover.generate(MESSAGES)

    assert primary.calls == 1
    assert fallback.calls == 0
    assert response.provider == "gemini"
    assert response.content == "answer from gemini"


def test_non_transient_primary_failure_is_not_caught_and_fallback_is_never_called() -> None:
    """ADR-002's central point: an auth error / bug in our own code must
    propagate, not be laundered as a clean failover."""
    primary = _FakeProvider("gemini", error=_NonTransientError("bad request"))
    fallback = _FakeProvider("openrouter")
    failover = FailoverProvider(primary, fallback)

    with pytest.raises(_NonTransientError):
        failover.generate(MESSAGES)

    assert primary.calls == 1
    assert fallback.calls == 0


def test_fallback_failure_propagates_without_a_second_retry() -> None:
    """FailoverProvider is one hop (ADR-002: "retries once on OpenRouter") —
    it must not retry the fallback itself; that's decide_next's job."""
    primary = _FakeProvider("gemini", error=ProviderTimeoutError("gemini timed out"))
    fallback = _FakeProvider("openrouter", error=ProviderServerError("openrouter also down"))
    failover = FailoverProvider(primary, fallback)

    with pytest.raises(ProviderServerError):
        failover.generate(MESSAGES)

    assert primary.calls == 1
    assert fallback.calls == 1


def test_messages_and_tools_are_forwarded_unchanged_to_the_fallback() -> None:
    captured = {}

    class _CapturingFallback(_FakeProvider):
        def generate(self, messages, tools=None):
            captured["messages"] = messages
            captured["tools"] = tools
            return super().generate(messages, tools)

    primary = _FakeProvider("gemini", error=ProviderTimeoutError("timed out"))
    fallback = _CapturingFallback("openrouter")
    failover = FailoverProvider(primary, fallback)

    sentinel_tools = [object()]
    failover.generate(MESSAGES, tools=sentinel_tools)

    assert captured["messages"] == MESSAGES
    assert captured["tools"] is sentinel_tools
