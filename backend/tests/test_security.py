"""Mutation authentication, validation, and rate-limit boundaries."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from app import repository as repo
from app.config import Settings, get_settings
from app.db import get_checkpointer, get_db_pool
from app.dependencies import get_llm_provider
from app.main import app
from app.rate_limit import limiter
from app.resources import get_http_client


def _session() -> dict:
    now = datetime.now(UTC)
    return {
        "id": uuid4(),
        "task": "",
        "status": "created",
        "final_answer": None,
        "created_at": now,
        "updated_at": now,
    }


def test_missing_and_incorrect_keys_are_rejected_before_database_construction() -> None:
    settings = Settings(_env_file=None, agent_ops_api_key="correct-key")
    app.dependency_overrides[get_settings] = lambda: settings

    def database_must_not_be_resolved():
        raise AssertionError("database dependency resolved before authentication")

    app.dependency_overrides[get_db_pool] = database_must_not_be_resolved
    try:
        client = TestClient(app)
        missing = client.post("/sessions")
        incorrect = client.post("/sessions", headers={"X-Agent-Ops-Key": "wrong-key"})
    finally:
        app.dependency_overrides.clear()

    assert missing.status_code == 401
    assert incorrect.status_code == 401
    assert (
        missing.json() == incorrect.json() == {"detail": "valid operator credentials are required"}
    )


def test_valid_key_preserves_mutation_flow(monkeypatch) -> None:
    settings = Settings(_env_file=None, agent_ops_api_key="correct-key")
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_db_pool] = lambda: object()
    monkeypatch.setattr(repo, "create_session", lambda pool: _session())
    try:
        response = TestClient(app).post("/sessions", headers={"X-Agent-Ops-Key": "correct-key"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    assert response.json()["status"] == "created"


def test_session_creation_rate_limit_has_stable_json(monkeypatch) -> None:
    limiter.reset()
    settings = Settings(_env_file=None, agent_ops_api_key="correct-key")
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_db_pool] = lambda: object()
    monkeypatch.setattr(repo, "create_session", lambda pool: _session())
    client = TestClient(app, headers={"X-Agent-Ops-Key": "correct-key"})
    try:
        responses = [client.post("/sessions") for _ in range(21)]
    finally:
        app.dependency_overrides.clear()
        limiter.reset()

    assert all(response.status_code == 201 for response in responses[:20])
    assert responses[-1].status_code == 429
    assert responses[-1].json() == {"detail": "rate limit exceeded; try again later"}


def test_message_validation_rejects_blank_and_oversized_content(monkeypatch) -> None:
    settings = Settings(_env_file=None, agent_ops_api_key="correct-key")
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_db_pool] = lambda: object()
    app.dependency_overrides[get_checkpointer] = lambda: object()
    app.dependency_overrides[get_llm_provider] = lambda: object()
    app.dependency_overrides[get_http_client] = lambda: object()

    def mutation_must_not_start(*args, **kwargs):
        raise AssertionError("invalid message reached the database mutation path")

    monkeypatch.setattr(repo, "get_session", mutation_must_not_start)
    try:
        client = TestClient(app, headers={"X-Agent-Ops-Key": "correct-key"})
        blank = client.post(f"/sessions/{uuid4()}/messages", json={"content": "   "})
        oversized = client.post(f"/sessions/{uuid4()}/messages", json={"content": "x" * 8_001})
    finally:
        app.dependency_overrides.clear()

    assert blank.status_code == 422
    assert oversized.status_code == 422


def test_session_list_limit_is_bounded(monkeypatch) -> None:
    app.dependency_overrides[get_db_pool] = lambda: object()

    def query_must_not_run(*args, **kwargs):
        raise AssertionError("invalid limit reached the database query path")

    monkeypatch.setattr(repo, "list_sessions", query_must_not_run)
    try:
        client = TestClient(app)
        below = client.get("/sessions?limit=0")
        above = client.get("/sessions?limit=101")
    finally:
        app.dependency_overrides.clear()
    assert below.status_code == 422
    assert above.status_code == 422
