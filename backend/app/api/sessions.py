"""Session, message, and trace endpoints (ARCHITECTURE.md §1/§3, Day 3).

Each request that runs the graph (`send_message`) blocks synchronously
until the graph either finishes or pauses on an approval interrupt —
ARCHITECTURE.md §3 step 5 is explicit that a paused run "literally ends" and
is resumed by a later, separate request, not held open in memory.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from langgraph.checkpoint.base import BaseCheckpointSaver
from psycopg_pool import ConnectionPool
from pydantic import BaseModel

from app import repository as repo
from app.config import Settings, get_settings
from app.db import get_checkpointer, get_db_pool
from app.dependencies import get_llm_provider
from app.llm.base import LLMProvider
from app.session_runner import start_session_run

router = APIRouter(tags=["sessions"])


class SessionResponse(BaseModel):
    id: UUID
    task: str
    status: str
    final_answer: str | None
    created_at: datetime
    updated_at: datetime


class TraceEventResponse(BaseModel):
    id: int
    session_id: UUID
    node: str
    detail: str
    provider: str | None
    created_at: datetime


class CreateMessageRequest(BaseModel):
    content: str


@router.post("/sessions", response_model=SessionResponse, status_code=201)
def create_session(pool: ConnectionPool = Depends(get_db_pool)) -> dict[str, Any]:
    return repo.create_session(pool)


@router.get("/sessions/{session_id}", response_model=SessionResponse)
def get_session(session_id: UUID, pool: ConnectionPool = Depends(get_db_pool)) -> dict[str, Any]:
    session = repo.get_session(pool, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return session


@router.post("/sessions/{session_id}/messages", response_model=SessionResponse)
def send_message(
    session_id: UUID,
    body: CreateMessageRequest,
    pool: ConnectionPool = Depends(get_db_pool),
    checkpointer: BaseCheckpointSaver = Depends(get_checkpointer),
    llm: LLMProvider = Depends(get_llm_provider),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    session = repo.get_session(pool, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    # Day 3 scope boundary (ADR-015): one task per session. A session's
    # FIRST message starts its one graph run; a second message to a
    # session that's already running/paused/finished is a clear 409, not a
    # silent no-op or an implicit "start a new unrelated run."
    started = repo.start_session(pool, session_id, task=body.content)
    if started is None:
        raise HTTPException(
            status_code=409,
            detail=f"session is '{session['status']}', not 'created' — cannot accept a new message",
        )

    repo.add_message(pool, session_id, role="user", content=body.content)
    start_session_run(
        pool,
        checkpointer,
        llm,
        session_id=session_id,
        task=body.content,
        tavily_api_key=settings.tavily_api_key,
    )
    return repo.get_session(pool, session_id)


@router.get("/sessions/{session_id}/trace", response_model=list[TraceEventResponse])
def get_trace(
    session_id: UUID, pool: ConnectionPool = Depends(get_db_pool)
) -> list[dict[str, Any]]:
    if repo.get_session(pool, session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")
    return repo.list_trace_events(pool, session_id)
