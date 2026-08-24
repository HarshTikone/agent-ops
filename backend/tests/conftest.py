"""Shared pytest fixtures for the backend test suite.

Tests never rely on the developer's real `.env` — they build an explicit
`Settings` instance and override FastAPI's dependency, so the suite behaves
identically on a laptop with real keys and on a fresh CI runner with none.

Exception: the DB-backed fixtures below (`db_pool`, `session_row`) DO read
the real `.env` / CI's real `DATABASE_URL` secret and hit the real Supabase
project (ADR-014) — unlike the LLM providers, Postgres isn't rate-limited
the way OpenRouter is, and a repository/API layer test suite that never
touches a real database isn't actually testing the persistence layer.
"""

import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app import repository as repo
from app.config import Settings, get_settings
from app.main import app


@pytest.fixture
def make_client():
    """Factory fixture: build a TestClient with a given Settings override."""

    def _make_client(**settings_overrides) -> TestClient:
        # _env_file=None disables loading the developer's real .env for this
        # instance — otherwise "no config set" tests would pass or fail
        # depending on whether *your* laptop happens to have real secrets in
        # .env, which is exactly the kind of nondeterminism a test suite must
        # not have.
        settings = Settings(_env_file=None, **settings_overrides)
        app.dependency_overrides[get_settings] = lambda: settings
        return TestClient(app)

    yield _make_client
    app.dependency_overrides.clear()


@pytest.fixture
def client(make_client) -> TestClient:
    """Default client with no provider/database configuration set."""
    return make_client()


@pytest.fixture(scope="session")
def db_pool():
    """A real connection pool against the real DATABASE_URL (repo-root
    `.env` locally, a CI secret in Actions) — skips DB-backed tests
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
