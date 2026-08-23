"""GeminiProvider / OpenRouterProvider: the exception-translation boundary
each one sits on top of (ADR-010). No real API calls — a fake object with a
controllable `.invoke()`/`.bind_tools()` stands in for the LangChain chat
model, since that's the exact seam these classes wrap.

This is what makes the FailoverProvider tests in test_llm_failover.py
trustworthy: those tests use plain fake `LLMProvider`s and never touch this
translation logic directly, so this file is the only place that verifies
Gemini's and OpenRouter's *specific* SDK exceptions actually turn into the
narrow `TransientProviderError` subclasses the failover boundary catches.
"""

from __future__ import annotations

import httpx
import pytest
from langchain_core.exceptions import (
    ModelAPIError,
    ModelAuthenticationError,
    ModelConnectionError,
    ModelInvalidRequestError,
    ModelRateLimitError,
    ModelTimeoutError,
)
from langchain_core.messages import AIMessage, HumanMessage

from app.llm.errors import ProviderRateLimitError, ProviderServerError, ProviderTimeoutError
from app.llm.gemini import GeminiProvider
from app.llm.openrouter import OpenRouterProvider


class _FakeChatModel:
    """Stands in for `ChatGoogleGenerativeAI` / `ChatOpenAI`: `bind_tools()`
    returns self, `invoke()` either raises `self.error` or returns
    `self.response`.
    """

    def __init__(
        self, *, response: AIMessage | None = None, error: Exception | None = None
    ) -> None:
        self.response = response or AIMessage(content="ok", tool_calls=[])
        self.error = error
        self.invoke_calls = 0

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.invoke_calls += 1
        if self.error is not None:
            raise self.error
        return self.response


MESSAGES = [HumanMessage(content="hi")]


# --- GeminiProvider ----------------------------------------------------


def test_gemini_provider_returns_normalized_response_on_success() -> None:
    fake = _FakeChatModel(response=AIMessage(content="pong", tool_calls=[]))
    provider = GeminiProvider(api_key="k", model="m", client=fake)
    response = provider.generate(MESSAGES)
    assert response.content == "pong"
    assert response.provider == "gemini"
    assert fake.invoke_calls == 1


def test_gemini_provider_translates_rate_limit_error() -> None:
    fake = _FakeChatModel(error=ModelRateLimitError("429"))
    provider = GeminiProvider(api_key="k", model="m", client=fake)
    with pytest.raises(ProviderRateLimitError):
        provider.generate(MESSAGES)


def test_gemini_provider_translates_server_error() -> None:
    fake = _FakeChatModel(error=ModelAPIError("500"))
    provider = GeminiProvider(api_key="k", model="m", client=fake)
    with pytest.raises(ProviderServerError):
        provider.generate(MESSAGES)


def test_gemini_provider_translates_httpx_timeout() -> None:
    """Verified against the installed package (ADR-010): unlike OpenAI's
    integration, langchain-google-genai does NOT normalize timeouts to
    ModelTimeoutError — they surface as a raw httpx exception."""
    fake = _FakeChatModel(error=httpx.TimeoutException("timed out"))
    provider = GeminiProvider(api_key="k", model="m", client=fake)
    with pytest.raises(ProviderTimeoutError):
        provider.generate(MESSAGES)


def test_gemini_provider_translates_httpx_connect_error() -> None:
    fake = _FakeChatModel(error=httpx.ConnectError("refused"))
    provider = GeminiProvider(api_key="k", model="m", client=fake)
    with pytest.raises(ProviderTimeoutError):
        provider.generate(MESSAGES)


def test_gemini_provider_does_not_translate_auth_errors() -> None:
    """A missing/invalid key must NOT look failover-eligible (ADR-002,
    ADR-009) — it should propagate as the original langchain_core error."""
    fake = _FakeChatModel(error=ModelAuthenticationError("401"))
    provider = GeminiProvider(api_key="k", model="m", client=fake)
    with pytest.raises(ModelAuthenticationError):
        provider.generate(MESSAGES)


def test_gemini_provider_does_not_translate_invalid_request_errors() -> None:
    fake = _FakeChatModel(error=ModelInvalidRequestError("400"))
    provider = GeminiProvider(api_key="k", model="m", client=fake)
    with pytest.raises(ModelInvalidRequestError):
        provider.generate(MESSAGES)


# --- OpenRouterProvider --------------------------------------------------


def test_openrouter_provider_returns_normalized_response_on_success() -> None:
    fake = _FakeChatModel(response=AIMessage(content="pong", tool_calls=[]))
    provider = OpenRouterProvider(api_key="k", model="m", client=fake)
    response = provider.generate(MESSAGES)
    assert response.content == "pong"
    assert response.provider == "openrouter"


def test_openrouter_provider_translates_rate_limit_error() -> None:
    fake = _FakeChatModel(error=ModelRateLimitError("429"))
    provider = OpenRouterProvider(api_key="k", model="m", client=fake)
    with pytest.raises(ProviderRateLimitError):
        provider.generate(MESSAGES)


def test_openrouter_provider_translates_server_error() -> None:
    fake = _FakeChatModel(error=ModelAPIError("500"))
    provider = OpenRouterProvider(api_key="k", model="m", client=fake)
    with pytest.raises(ProviderServerError):
        provider.generate(MESSAGES)


def test_openrouter_provider_translates_model_timeout_error() -> None:
    fake = _FakeChatModel(error=ModelTimeoutError("timed out"))
    provider = OpenRouterProvider(api_key="k", model="m", client=fake)
    with pytest.raises(ProviderTimeoutError):
        provider.generate(MESSAGES)


def test_openrouter_provider_translates_model_connection_error() -> None:
    fake = _FakeChatModel(error=ModelConnectionError("refused"))
    provider = OpenRouterProvider(api_key="k", model="m", client=fake)
    with pytest.raises(ProviderTimeoutError):
        provider.generate(MESSAGES)


def test_openrouter_provider_does_not_translate_auth_errors() -> None:
    fake = _FakeChatModel(error=ModelAuthenticationError("401"))
    provider = OpenRouterProvider(api_key="k", model="m", client=fake)
    with pytest.raises(ModelAuthenticationError):
        provider.generate(MESSAGES)
