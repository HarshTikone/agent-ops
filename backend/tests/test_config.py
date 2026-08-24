"""Tests for Settings parsing logic that isn't already covered via the API.

Every instance below passes `_env_file=None` to disable loading the
developer's real `.env` — otherwise these assertions would be nondeterministic
depending on whether *your* machine happens to have real secrets on disk,
which is exactly the kind of environment-dependent flakiness a test suite
must not have (see also tests/conftest.py's `make_client`).

Three tests below ALSO need `isolate_settings_env`/an explicit subprocess
`env=` — `_env_file=None` disables the dotenv-file source only; real OS
environment variables are a separate source pydantic-settings still reads,
and (verified directly) win over an explicit `_env_file`'s content for the
same field too. See ADR-017 for the full story of how this went unnoticed
until Day 3's CI change gave the runner real secrets.
"""

import os
import subprocess
import sys
from pathlib import Path

import app as app_package
from app.config import _ENV_FILE, _REPO_ROOT, Settings
from tests.conftest import SETTINGS_ENV_VAR_NAMES, isolate_settings_env

# The real app/ directory's own location — never hardcode this as a relative
# path from this test file, or the mutation test below would silently start
# passing against the wrong tree the moment either directory moves.
REAL_APP_DIR = Path(app_package.__file__).resolve().parent


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
    """The `_ENV_FILE`/`_REPO_ROOT` constants themselves must not be relative.

    NOTE: this only checks the constants exist and are shaped correctly — it
    does NOT prove `Settings` actually uses them. A mutation that reverts
    `model_config`'s `env_file=_ENV_FILE` back to the original buggy
    `env_file=".env"` (while leaving these constants perfectly correct and
    unused) passes this test. That mutation is exactly what regressed once
    already; see `test_model_config_actually_uses_the_anchored_path` and
    `test_settings_reads_repo_root_env_when_started_from_backend` below for
    the tests that actually catch it — this one is kept only as a cheap
    shape check on the constants in isolation.
    """
    assert _ENV_FILE.is_absolute()

    independently_computed_root = Path(__file__).resolve().parents[2]
    assert independently_computed_root == _REPO_ROOT
    assert independently_computed_root / ".env" == _ENV_FILE


def test_model_config_actually_uses_the_anchored_path():
    """The wiring assertion the constant-only test above can't provide:
    `Settings.model_config["env_file"]` — what pydantic-settings actually
    reads at construction time — must literally be `_ENV_FILE`, not merely
    "some absolute path" or (the regressed state) the original relative
    `".env"` string sitting unused next to a correct constant.
    """
    configured = Settings.model_config["env_file"]
    assert Path(configured).is_absolute()
    assert Path(configured) == _ENV_FILE


def test_settings_reads_repo_root_env_when_started_from_backend(tmp_path):
    """End-to-end proof of the actual regression, in a throwaway repo copy
    so it never reads or writes the developer's real `.env`.

    Mirrors production's directory shape exactly (a `.env` at the repo root,
    the app one level under a `backend/` directory) by copying the real
    `app/` package into a fresh `<tmp>/repo/backend/app` and writing a fake
    `.env` at `<tmp>/repo/.env` — then imports `Settings` fresh in a
    subprocess run with CWD set to the fake `backend/`, exactly matching how
    `uvicorn` is actually started per the README. If `env_file` is ever
    relative again, this subprocess resolves it against the fake `backend/`
    CWD, finds nothing there, and `gemini_api_key` comes back `""` instead of
    the value below — failing this assertion.

    The subprocess is given an explicit `env=`, not the default (inherit the
    parent's environment) — otherwise a real `GEMINI_API_KEY` in the test
    runner's own environment (true in CI as of Day 3, ADR-017) would win
    over the fake dotenv value and this test would assert on the wrong
    thing while still technically passing against a real key.
    """
    import shutil

    fake_repo_root = tmp_path / "repo"
    fake_backend = fake_repo_root / "backend"
    fake_backend.mkdir(parents=True)
    shutil.copytree(
        REAL_APP_DIR, fake_backend / "app", ignore=shutil.ignore_patterns("__pycache__")
    )
    (fake_repo_root / ".env").write_text("GEMINI_API_KEY=from-fake-repo-root\n", encoding="utf-8")

    clean_env = {k: v for k, v in os.environ.items() if k.upper() not in SETTINGS_ENV_VAR_NAMES}
    result = subprocess.run(
        [sys.executable, "-c", "from app.config import Settings; print(Settings().gemini_api_key)"],
        cwd=fake_backend,
        capture_output=True,
        text=True,
        check=True,
        env=clean_env,
    )

    assert result.stdout.strip() == "from-fake-repo-root"


def test_settings_loads_an_explicit_env_file_path_regardless_of_cwd(tmp_path, monkeypatch):
    """Component-level check of pydantic-settings' own loading mechanism:
    given an absolute `_env_file` override, it reads that exact file even
    when CWD points elsewhere — as long as no real environment variable for
    the same field also exists (ADR-017: a real env var wins over an
    explicit `_env_file`'s content, so this needs `isolate_settings_env`
    too, not just a fake file, to observe the file's value at all).

    This does NOT exercise config.py's CWD-independence fix — passing
    `_env_file=fake_env` explicitly bypasses `model_config`'s `env_file`
    entirely, so this test passes identically against the original buggy
    code. It stays here as a check on the underlying library behavior our
    fix depends on, not as regression coverage for the bug itself (that's
    `test_model_config_actually_uses_the_anchored_path` and
    `test_settings_reads_repo_root_env_when_started_from_backend` above).
    """
    isolate_settings_env(monkeypatch)
    fake_env = tmp_path / "fake_repo_root.env"
    fake_env.write_text("GEMINI_API_KEY=from-fake-env-file\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    settings = Settings(_env_file=fake_env)

    assert settings.gemini_api_key == "from-fake-env-file"


def test_env_file_none_ignores_real_dotenv_even_when_present(monkeypatch):
    """`_env_file=None` (used throughout this suite and in conftest's
    `make_client`) must keep meaning "ignore any .env entirely" after the
    fix — not just "ignore the old relative path" — even on a machine where
    the real repo-root .env is fully populated with real keys.

    `isolate_settings_env` is required alongside `_env_file=None`, not
    redundant with it (ADR-017): `_env_file=None` only removes the
    dotenv-file source; it does nothing about real OS environment variables,
    which pydantic-settings reads regardless and which CI now genuinely has
    set (GEMINI_API_KEY etc., added for the DB-backed tests in ADR-014).
    Without the isolation call, this test passes on a machine with no
    relevant env vars set and fails the moment one exists — exactly the
    machine-dependent flakiness its own docstring already claimed to rule
    out, which is exactly what happened in CI before this fix.
    """
    isolate_settings_env(monkeypatch)
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
