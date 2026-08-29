"""FastAPI application entrypoint."""

import logging
import traceback
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from app.api import approvals, health, sessions
from app.config import get_settings
from app.db import create_db_pool
from app.rate_limit import limiter, rate_limit_exceeded_handler
from app.resources import create_http_client
from app.sanitization import sanitize_error

settings = get_settings()

logging.basicConfig(level=settings.log_level.upper())
logger = logging.getLogger("agent_ops")


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Log unexpected failures while keeping implementation details private."""
    logger.error(
        "unhandled_exception method=%s path=%s traceback=%s",
        request.method,
        request.url.path,
        sanitize_error(
            "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
            max_length=8_000,
        ),
    )
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Create infrastructure once and close it exactly once on shutdown."""
    runtime_settings = get_settings()
    pool = create_db_pool(runtime_settings) if runtime_settings.database_url else None
    http_client: httpx.Client = create_http_client()
    application.state.db_pool = pool
    application.state.http_client = http_client
    application.state.checkpointer = None
    if pool is not None:
        # Background connection establishment keeps an unavailable/resuming
        # database from preventing liveness; readiness reports reachability.
        pool.open(wait=False)
    try:
        yield
    finally:
        http_client.close()
        if pool is not None:
            pool.close()
        application.state.http_client = None
        application.state.db_pool = None
        application.state.checkpointer = None


app = FastAPI(
    title="Agent Ops",
    description="Multi-agent orchestration copilot — planner + tool-using "
    "sub-agents with human-in-the-loop approval and full decision tracing.",
    version="0.1.0",
    lifespan=lifespan,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)  # type: ignore[arg-type]
app.add_exception_handler(Exception, unhandled_exception_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(sessions.router)
app.include_router(approvals.router)


@app.get("/")
def root() -> dict[str, str]:
    return {"service": "agent-ops-backend", "docs": "/docs"}
