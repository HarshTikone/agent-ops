"""Primary LLM provider (ADR-002): Gemini via `langchain-google-genai`.

Verified directly against the installed package (`langchain-google-genai`
4.3.5, pinned in ADR-004): a 429 is re-raised by that package as
`langchain_core.exceptions.ModelRateLimitError` and a 5xx as `ModelAPIError`
— both already normalized across providers by LangChain itself, so no
per-provider status-code parsing is needed here. Unlike the OpenAI-compatible
integration (see `openrouter.py`), this package does *not* normalize timeout/
connection failures to `ModelTimeoutError` — those surface as raw
`httpx.TimeoutException` / `httpx.ConnectError`, caught explicitly below.
See ADR-010 for the full verification.
"""

from __future__ import annotations

import httpx
from langchain_core.exceptions import ModelAPIError, ModelRateLimitError
from langchain_core.messages import BaseMessage
from langchain_core.tools import BaseTool
from langchain_google_genai import ChatGoogleGenerativeAI

from app.llm.base import LLMResponse, llm_response_from_ai_message
from app.llm.errors import ProviderRateLimitError, ProviderServerError, ProviderTimeoutError

_REQUEST_TIMEOUT_SECONDS = 30


class GeminiProvider:
    """Wraps `ChatGoogleGenerativeAI`.

    `max_retries=0` on the underlying client is deliberate: retry/failover
    decisions belong to `FailoverProvider` and, above that, to the graph's
    `decide_next` node — not to the SDK's own internal retry loop (which
    defaults to 6 attempts and would hide a transient failure from the
    failover boundary for all of them before ever raising).
    """

    name = "gemini"

    def __init__(
        self, api_key: str, model: str, *, client: ChatGoogleGenerativeAI | None = None
    ) -> None:
        self._client = client or ChatGoogleGenerativeAI(
            model=model,
            api_key=api_key,
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
            raise ProviderRateLimitError(f"Gemini rate-limited: {exc}") from exc
        except ModelAPIError as exc:
            raise ProviderServerError(f"Gemini server error: {exc}") from exc
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            raise ProviderTimeoutError(f"Gemini timed out: {exc}") from exc
        return llm_response_from_ai_message(ai_message, provider=self.name)
