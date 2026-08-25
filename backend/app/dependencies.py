"""FastAPI dependency-injection singletons for infra beyond Settings itself
— same @lru_cache-singleton, override-in-tests pattern as app.config and
app.db (ADR-014).
"""

from __future__ import annotations

import logging
from functools import lru_cache

from app.config import get_settings
from app.llm.base import LLMProvider
from app.llm.failover import FailoverProvider
from app.llm.gemini import GeminiProvider
from app.llm.openrouter import OpenRouterProvider

logger = logging.getLogger("agent_ops.dependencies")


@lru_cache
def get_llm_provider() -> LLMProvider:
    settings = get_settings()
    gemini = GeminiProvider(api_key=settings.gemini_api_key, model=settings.gemini_model)

    if not settings.openrouter_api_key or not settings.openrouter_model:
        # ADR-020: ChatOpenAI (langchain-openai) raises openai.OpenAIError at
        # CONSTRUCTION time when api_key is empty — verified directly, not
        # assumed from the SDK's error message. Building OpenRouterProvider
        # eagerly here made a Gemini-only ("degraded" per ADR-009) deploy
        # unable to serve a single request: every send_message/approve call
        # raised before FailoverProvider's own narrow except clause ever ran.
        # A bare GeminiProvider is exactly what "degraded" promises: can
        # serve every request, just with no failover safety net.
        # config.py's _reject_half_configured_openrouter rules out the
        # half-set case at Settings construction, so the only way this
        # branch is reached is "both empty" — a deliberate choice, not a
        # misconfiguration this needs to also reject.
        logger.warning("openrouter_not_configured: failover disabled, running on Gemini alone")
        return gemini

    openrouter = OpenRouterProvider(
        api_key=settings.openrouter_api_key, model=settings.openrouter_model
    )
    return FailoverProvider(gemini, openrouter)
