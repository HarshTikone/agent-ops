"""FastAPI dependency-injection singletons for infra beyond Settings itself
— same @lru_cache-singleton, override-in-tests pattern as app.config and
app.db (ADR-014).
"""

from __future__ import annotations

from functools import lru_cache

from app.config import get_settings
from app.llm.base import LLMProvider
from app.llm.failover import FailoverProvider
from app.llm.gemini import GeminiProvider
from app.llm.openrouter import OpenRouterProvider


@lru_cache
def get_llm_provider() -> LLMProvider:
    settings = get_settings()
    gemini = GeminiProvider(api_key=settings.gemini_api_key, model=settings.gemini_model)
    openrouter = OpenRouterProvider(
        api_key=settings.openrouter_api_key, model=settings.openrouter_model
    )
    return FailoverProvider(gemini, openrouter)
