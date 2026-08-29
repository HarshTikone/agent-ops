"""Shared mutation rate limiter and stable error response."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    del request, exc
    return JSONResponse(
        status_code=429,
        content={"detail": "rate limit exceeded; try again later"},
        headers={"Retry-After": "60"},
    )
