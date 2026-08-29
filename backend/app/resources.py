"""Application-owned HTTP resources exposed as request dependencies."""

from __future__ import annotations

from typing import cast

import httpx
from fastapi import HTTPException, Request


def create_http_client() -> httpx.Client:
    return httpx.Client(timeout=15.0)


def get_http_client(request: Request) -> httpx.Client:
    client = getattr(request.app.state, "http_client", None)
    if client is None:
        raise HTTPException(status_code=503, detail="HTTP client is not available")
    return cast(httpx.Client, client)
