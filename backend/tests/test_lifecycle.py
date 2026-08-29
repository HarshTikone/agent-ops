"""Application lifespan ownership and readiness probe behavior."""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient
from psycopg_pool import PoolTimeout

import app.main as main_module
from app.api.health import _database_reachable
from app.config import Settings
from app.main import unhandled_exception_handler


class _TrackedPool:
    def __init__(self) -> None:
        self.open_calls = 0
        self.close_calls = 0

    def open(self, *, wait: bool) -> None:
        assert wait is False
        self.open_calls += 1

    def close(self) -> None:
        self.close_calls += 1


class _TrackedClient:
    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


class _UnavailablePool:
    def connection(self, *, timeout: float):
        raise PoolTimeout(f"unavailable after {timeout}")


def test_lifespan_opens_and_closes_resources_exactly_once(monkeypatch) -> None:
    pool = _TrackedPool()
    http_client = _TrackedClient()
    settings = Settings(_env_file=None, database_url="postgresql://localhost/test")
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    monkeypatch.setattr(main_module, "create_db_pool", lambda configured: pool)
    monkeypatch.setattr(main_module, "create_http_client", lambda: http_client)

    with TestClient(main_module.app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert pool.open_calls == 1
        assert pool.close_calls == 0
        assert http_client.close_calls == 0

    assert pool.close_calls == 1
    assert http_client.close_calls == 1


def test_database_probe_classifies_pool_timeout_as_unreachable() -> None:
    assert _database_reachable(_UnavailablePool(), 0.01) is False  # type: ignore[arg-type]


def test_unhandled_exception_handler_logs_traceback_and_sanitizes_response(caplog) -> None:
    from starlette.requests import Request

    request = Request({"type": "http", "method": "GET", "path": "/explode", "headers": []})
    secret = "upstream-secret-must-not-leak"

    try:
        raise RuntimeError(f"api_key={secret}")
    except RuntimeError as exc:
        response = asyncio.run(unhandled_exception_handler(request, exc))

    assert response.status_code == 500
    assert response.body == b'{"detail":"internal server error"}'
    assert secret not in response.body.decode()
    assert secret not in caplog.text
    assert "api_key=[REDACTED]" in caplog.text
