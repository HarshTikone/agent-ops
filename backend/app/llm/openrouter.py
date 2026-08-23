"""Fallback LLM provider (ADR-002, ADR-005): OpenRouter via the OpenAI-
compatible `langchain-openai` client, pointed at OpenRouter's base URL.

Verified directly against the installed package (`langchain-openai` 1.6.0,
pinned in ADR-004): unlike the Gemini integration, this one normalizes ALL
four transient shapes to `langchain_core.exceptions` types —
`ModelRateLimitError` (429), `ModelAPIError` (5xx), `ModelTimeoutError`, and
`ModelConnectionError`. See ADR-010 for the full verification and why the two
providers need different `except` clauses despite sharing one interface.
"""

from __future__ import annotations

from langchain_core.exceptions import (
    ModelAPIError,
    ModelConnectionError,
    ModelRateLimitError,
    ModelTimeoutError,
)
from langchain_core.messages import BaseMessage
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI

from app.llm.base import LLMResponse, llm_response_from_ai_message
from app.llm.errors import ProviderRateLimitError, ProviderServerError, ProviderTimeoutError

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_REQUEST_TIMEOUT_SECONDS = 30


class OpenRouterProvider:
    """Wraps `ChatOpenAI` with `base_url=OPENROUTER_BASE_URL` (ADR-005).

    `max_retries=0` for the same reason as `GeminiProvider` — see there.
    """

    name = "openrouter"

    def __init__(self, api_key: str, model: str, *, client: ChatOpenAI | None = None) -> None:
        self._client = client or ChatOpenAI(
            model=model,
            api_key=api_key,
            base_url=OPENROUTER_BASE_URL,
            max_retries=0,
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )

    def generate(
        self, messages: list[BaseMessage], tools: list[BaseTool] | None = None
    ) -> LLMResponse:
        bound = self._client.bind_tools(tools) if tools else self._client
        try:
            ai_message = bound.invoke(messages)
        except ModelRateLimitError as exc:
            raise ProviderRateLimitError(f"OpenRouter rate-limited: {exc}") from exc
        except ModelAPIError as exc:
            raise ProviderServerError(f"OpenRouter server error: {exc}") from exc
        except (ModelTimeoutError, ModelConnectionError) as exc:
            raise ProviderTimeoutError(f"OpenRouter timed out: {exc}") from exc
        return llm_response_from_ai_message(ai_message, provider=self.name)
