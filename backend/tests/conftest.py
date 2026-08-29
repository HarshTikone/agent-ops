"""Shared pytest fixtures for the backend test suite.

Tests never rely on the developer's real `.env` — they build an explicit
`Settings` instance and override FastAPI's dependency, so the suite behaves
identically on a laptop with real keys and on a fresh CI runner with none.

That guarantee had a real gap until ADR-017: `_env_file=None` only disables
the *dotenv-file* source — pydantic-settings still reads real OS environment
variables regardless, and (verified directly, not assumed) a real env var
for the same field name wins over an explicit `_env_file`'s content too,
whether that file is real, fake, or `None`. Invisible until Day 3's CI
change gave the runner real `GEMINI_API_KEY`/etc. for the DB-backed tests —
`SETTINGS_ENV_VAR_NAMES` + `monkeypatch.delenv` below is what actually
closes it, not `_env_file=None` alone.

Exception: the DB-backed fixtures below (`db_pool`, `session_row`) read
`DATABASE_URL`. CI points it at a fresh PostgreSQL service container; local
development may point it at a developer database. Externally hosted provider
tests are marked `live` and excluded from the default suite.
"""

import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app import repository as repo
from app.config import Settings, get_settings
from app.db import get_optional_db_pool
from app.main import app

# Derived from the model, not hand-listed, so a new Settings field can't
# silently fall outside the isolation this provides (ADR-017).
SETTINGS_ENV_VAR_NAMES = [name.upper() for name in Settings.model_fields]


def isolate_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in SETTINGS_ENV_VAR_NAMES:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def make_client(monkeypatch):
    """Factory fixture: build a TestClient with a given Settings override."""
    isolate_settings_env(monkeypatch)

    def _make_client(**settings_overrides) -> TestClient:
        # _env_file=None disables loading the developer's real .env for this
        # instance; isolate_settings_env (above) is what actually clears any
        # real ambient env vars for the same field names — see ADR-017.
        settings_overrides.setdefault("agent_ops_api_key", "test-operator-key")
        settings = Settings(_env_file=None, **settings_overrides)
        app.dependency_overrides[get_settings] = lambda: settings
        if settings.database_url:
            app.dependency_overrides[get_optional_db_pool] = lambda: _HealthyPool()
        return TestClient(app, headers={"X-Agent-Ops-Key": "test-operator-key"})

    yield _make_client
    app.dependency_overrides.clear()


class _HealthyConnection:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def transaction(self):
        return self

    def execute(self, query, params=None):
        return self

    def fetchone(self):
        return (1,)


class _HealthyPool:
    def connection(self, *, timeout):
        return _HealthyConnection()


@pytest.fixture
def client(make_client) -> TestClient:
    """Default client with no provider/database configuration set."""
    return make_client()


@pytest.fixture(scope="session")
def db_pool():
    """A real connection pool against DATABASE_URL (repo-root `.env` locally,
    an isolated PostgreSQL service in CI) — skips DB-backed tests
    gracefully rather than failing if neither is set.
    """
    settings = Settings()  # deliberately NOT _env_file=None: reads the real .env
    if not settings.database_url:
        pytest.skip("DATABASE_URL not configured — skipping DB-backed tests")
    pool = ConnectionPool(
        conninfo=settings.database_url,
        max_size=5,
        kwargs={"autocommit": True, "row_factory": dict_row},
        open=True,
    )
    yield pool
    pool.close()


@pytest.fixture
def session_row(db_pool):
    """A real `sessions` row, deleted (cascading to every child table) when
    the test finishes — tests never leave rows behind in the shared project.
    """
    row = repo.create_session(db_pool, task="test session")
    yield row
    with db_pool.connection() as conn:
        conn.execute("DELETE FROM sessions WHERE id = %s", (row["id"],))
