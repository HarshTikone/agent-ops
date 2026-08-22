"""FastAPI application entrypoint.

Day 1 scope only: app wiring, CORS, and health/readiness endpoints. No LLM
calls, no agent graph, no database access — those start Day 2 (agent
engine) and Day 3 (memory/approval/tracing/API endpoints).
"""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health
from app.config import get_settings

settings = get_settings()

logging.basicConfig(level=settings.log_level.upper())
logger = logging.getLogger("agent_ops")

app = FastAPI(
    title="Agent Ops",
    description="Multi-agent orchestration copilot — planner + tool-using "
    "sub-agents with human-in-the-loop approval and full decision tracing.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)


@app.get("/")
def root() -> dict[str, str]:
    return {"service": "agent-ops-backend", "docs": "/docs"}
