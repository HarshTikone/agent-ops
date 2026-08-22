"""Tests for Settings parsing logic that isn't already covered via the API.

Every instance below passes `_env_file=None` to disable loading the
developer's real `.env` — otherwise these assertions would be nondeterministic
depending on whether *your* machine happens to have real secrets on disk,
which is exactly the kind of environment-dependent flakiness a test suite
must not have (see also tests/conftest.py's `make_client`).
"""

from app.config import Settings


def test_cors_origin_list_splits_and_trims():
    settings = Settings(
        _env_file=None, cors_origins="http://localhost:5173, https://example.com ,,"
    )
    assert settings.cors_origin_list == ["http://localhost:5173", "https://example.com"]


def test_cors_origin_list_single_origin():
    settings = Settings(_env_file=None, cors_origins="http://localhost:5173")
    assert settings.cors_origin_list == ["http://localhost:5173"]


def test_is_production_flag():
    assert Settings(_env_file=None, environment="production").is_production is True
    assert Settings(_env_file=None, environment="development").is_production is False


def test_llm_providers_configured_requires_gemini_key():
    assert Settings(_env_file=None, gemini_api_key="").llm_providers_configured is False
    assert Settings(_env_file=None, gemini_api_key="a-real-key").llm_providers_configured is True
