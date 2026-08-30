from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from app.config import Settings
from scripts import release_check


class _Provider:
    calls: list[str] = []

    def __init__(self, api_key: str, model: str) -> None:
        assert api_key and model

    def generate(self, messages) -> None:
        self.calls.append(str(messages[0].content))


class _Search:
    calls: list[tuple[str, list[str]]] = []

    def __init__(self, api_key: str, *, client: httpx.Client) -> None:
        assert api_key and client

    def run(self, *, query: str, include_domains: list[str]) -> str:
        self.calls.append((query, include_domains))
        return "official result"


class _Connection:
    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None

    def execute(self, query: str):
        assert query == "SELECT 1"
        return self

    def fetchone(self) -> tuple[int]:
        return (1,)


class _Pool:
    opened = False
    closed = False

    def open(self, *, wait: bool, timeout: int) -> None:
        assert wait and timeout == 10
        self.opened = True

    def connection(self, *, timeout: int) -> _Connection:
        assert timeout == 5
        return _Connection()

    def close(self) -> None:
        self.closed = True


def _settings(**overrides: str) -> Settings:
    values = {
        "gemini_api_key": "gemini-key",
        "gemini_model": "gemini-model",
        "tavily_api_key": "tavily-key",
        "supabase_url": "https://project.supabase.co",
        "supabase_secret_key": "supabase-secret",
        "database_url": "postgresql://example",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_release_check_verifies_required_dependencies_and_skips_optional(monkeypatch) -> None:
    pool = _Pool()
    monkeypatch.setattr(release_check, "GeminiProvider", _Provider)
    monkeypatch.setattr(release_check, "WebSearchTool", _Search)
    monkeypatch.setattr(release_check, "create_db_pool", lambda settings: pool)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["apikey"] == "supabase-secret"
        return httpx.Response(200)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    release_check.run_release_checks(_settings(), http_client=client)

    assert _Provider.calls
    assert _Search.calls[-1][1] == ["openai.com"]
    assert pool.opened and pool.closed


def test_release_check_verifies_openrouter_when_configured(monkeypatch) -> None:
    gemini = SimpleNamespace(generate=lambda messages: None)
    openrouter_calls: list[bool] = []
    monkeypatch.setattr(release_check, "GeminiProvider", lambda *args: gemini)
    monkeypatch.setattr(
        release_check,
        "OpenRouterProvider",
        lambda *args: SimpleNamespace(generate=lambda messages: openrouter_calls.append(True)),
    )
    monkeypatch.setattr(release_check, "WebSearchTool", _Search)
    monkeypatch.setattr(release_check, "create_db_pool", lambda settings: _Pool())
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200)))

    release_check.run_release_checks(
        _settings(openrouter_api_key="openrouter-key", openrouter_model="model"),
        http_client=client,
    )
    assert openrouter_calls == [True]


def test_release_check_redacts_provider_error_details(monkeypatch, caplog) -> None:
    secret = "super-secret-provider-response"

    class _FailingProvider:
        def __init__(self, *args) -> None:
            pass

        def generate(self, messages) -> None:
            raise ValueError(secret)

    monkeypatch.setattr(release_check, "GeminiProvider", _FailingProvider)
    with pytest.raises(RuntimeError, match="gemini"):
        release_check.run_release_checks(_settings(), http_client=httpx.Client())
    assert secret not in caplog.text
