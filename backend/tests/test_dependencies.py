"""get_llm_provider (ADR-020, C1): a Gemini-only ("degraded" per ADR-009)
deploy must get back a usable provider, not a construction-time crash.

`ChatOpenAI.__init__` raises `openai.OpenAIError` when `api_key` is empty —
verified directly against the installed langchain-openai (ADR-020) — so
eagerly building `OpenRouterProvider` regardless of configuration made a
Gemini-only deploy unable to serve a single request. These tests exercise
`get_llm_provider` itself (bypassing its `@lru_cache` by clearing it, since
the cache is process-global and other tests may have already populated it).
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.dependencies import get_llm_provider
from app.llm.failover import FailoverProvider
from app.llm.gemini import GeminiProvider


@pytest.fixture(autouse=True)
def _clear_provider_cache():
    get_llm_provider.cache_clear()
    yield
    get_llm_provider.cache_clear()


def _install_settings(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    import app.dependencies as dependencies_module

    monkeypatch.setattr(dependencies_module, "get_settings", lambda: settings)


def test_gemini_only_settings_return_a_bare_gemini_provider(monkeypatch) -> None:
    settings = Settings(_env_file=None, gemini_api_key="g", gemini_model="gemini-x")
    _install_settings(monkeypatch, settings)

    provider = get_llm_provider()

    assert isinstance(provider, GeminiProvider)
    assert not isinstance(provider, FailoverProvider)


def test_gemini_only_provider_does_not_raise_at_construction(monkeypatch) -> None:
    """The actual regression: constructing the provider used to raise
    openai.OpenAIError before this call ever returned."""
    settings = Settings(_env_file=None, gemini_api_key="g", gemini_model="gemini-x")
    _install_settings(monkeypatch, settings)

    get_llm_provider()  # must not raise


def test_both_providers_configured_return_a_failover_provider(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        gemini_api_key="g",
        gemini_model="gemini-x",
        openrouter_api_key="or-key",
        openrouter_model="some/model:free",
    )
    _install_settings(monkeypatch, settings)

    provider = get_llm_provider()

    assert isinstance(provider, FailoverProvider)
