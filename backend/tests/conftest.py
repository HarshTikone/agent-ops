"""Shared pytest fixtures for the backend test suite.

Tests never rely on the developer's real `.env` — they build an explicit
`Settings` instance and override FastAPI's dependency, so the suite behaves
identically on a laptop with real keys and on a fresh CI runner with none.
"""

import pytest
from fastapi.testclient import TestClient

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
