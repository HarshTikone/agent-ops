"""Tests for Settings parsing logic that isn't already covered via the API.

Every instance below passes `_env_file=None` to disable loading the
developer's real `.env` — otherwise these assertions would be nondeterministic
depending on whether *your* machine happens to have real secrets on disk,
which is exactly the kind of environment-dependent flakiness a test suite
must not have (see also tests/conftest.py's `make_client`).
"""

from pathlib import Path

from app.config import _ENV_FILE, _REPO_ROOT, Settings


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


# --- Regression coverage: env_file must not depend on process CWD ----------
#
# Bug: model_config used env_file=".env", a relative path pydantic-settings
# resolves against the CWD at Settings() construction time. README's local-dev
# flow runs uvicorn from backend/ while .env lives at the repo root, so the
# app silently read nothing (every field defaults to "") and reported
# "not_ready" against a fully-populated .env with no error at all.
#
# These tests independently recompute "repo root" from *this test file's own*
# location (tests/test_config.py -> backend -> repo root) rather than trusting
# config.py's arithmetic, so a future refactor that breaks the indexing in
# config.py can't also break the check meant to catch it.


def test_env_file_is_absolute_and_anchored_to_repo_root():
    """The configured path must not be relative — that's the whole bug."""
    assert _ENV_FILE.is_absolute()

    independently_computed_root = Path(__file__).resolve().parents[2]
    assert independently_computed_root == _REPO_ROOT
    assert independently_computed_root / ".env" == _ENV_FILE


def test_settings_loads_real_env_file_regardless_of_cwd(tmp_path, monkeypatch):
    """The actual regression: construct Settings from a directory that has
    no .env of its own, and confirm it still finds the *module-anchored*
    file rather than looking relative to CWD (which would find nothing here,
    silently, exactly like the original bug).

    Uses an explicit tmp .env (not the developer's real root .env) so this
    stays deterministic on any machine, matching this file's own convention.
    """
    fake_env = tmp_path / "fake_repo_root.env"
    fake_env.write_text("GEMINI_API_KEY=from-fake-env-file\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)  # simulates running uvicorn from backend/
    settings = Settings(_env_file=fake_env)

    assert settings.gemini_api_key == "from-fake-env-file"


def test_env_file_none_ignores_real_dotenv_even_when_present():
    """`_env_file=None` (used throughout this suite and in conftest's
    `make_client`) must keep meaning "ignore any .env entirely" after the
    fix — not just "ignore the old relative path" — even on a machine where
    the real repo-root .env is fully populated with real keys.
    """
    settings = Settings(_env_file=None)
    assert settings.gemini_api_key == ""
    assert settings.supabase_url == ""


def test_env_file_pointing_at_nonexistent_path_is_a_no_op(tmp_path):
    """Deployment (Render/Vercel) has no .env file at all — config comes
    entirely from the platform's real environment variables. An absolute
    env_file path that doesn't exist on disk must silently do nothing, not
    raise, so the module-level _ENV_FILE constant is safe to import even
    where no .env was ever created.
    """
    missing = tmp_path / "does-not-exist" / ".env"
    assert not missing.exists()

    settings = Settings(_env_file=missing, gemini_api_key="from-real-platform-env")
    assert settings.gemini_api_key == "from-real-platform-env"
