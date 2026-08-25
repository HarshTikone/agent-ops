"""Session, message, and trace endpoints (ARCHITECTURE.md §1/§3, Day 3;
`GET /sessions` and the embedded `pending_action` added Day 4, per ADR-015's
own note that both were deferred until the UI shape was known).

Each request that runs the graph (`send_message`) blocks synchronously
until the graph either finishes or pauses on an approval interrupt —
ARCHITECTURE.md §3 step 5 is explicit that a paused run "literally ends" and
is resumed by a later, separate request, not held open in memory.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from langgraph.checkpoint.base import BaseCheckpointSaver
from psycopg_pool import ConnectionPool

from app import repository as repo
from app.api.schemas import CreateMessageRequest, SessionResponse, TraceEventResponse
from app.config import Settings, get_settings
from app.db import get_checkpointer, get_db_pool
from app.dependencies import get_llm_provider
from app.llm.base import LLMProvider
from app.session_runner import start_session_run

logger = logging.getLogger("agent_ops.api.sessions")

router = APIRouter(tags=["sessions"])

_RUN_CRASH_MESSAGE = "The agent run failed unexpectedly."


def session_with_pending_action(pool: ConnectionPool, session: dict[str, Any]) -> dict[str, Any]:
    pending_action = None
    if session["status"] == "awaiting_approval":
        pending_action = repo.get_pending_action_for_session(pool, session["id"])
    return {**session, "pending_action": pending_action}


@router.post("/sessions", response_model=SessionResponse, status_code=201)
def create_session(pool: ConnectionPool = Depends(get_db_pool)) -> dict[str, Any]:
    return session_with_pending_action(pool, repo.create_session(pool))


@router.get("/sessions", response_model=list[SessionResponse])
def list_sessions(pool: ConnectionPool = Depends(get_db_pool)) -> list[dict[str, Any]]:
    return [session_with_pending_action(pool, s) for s in repo.list_sessions(pool)]


@router.get("/sessions/{session_id}", response_model=SessionResponse)
def get_session(session_id: UUID, pool: ConnectionPool = Depends(get_db_pool)) -> dict[str, Any]:
    session = repo.get_session(pool, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return session_with_pending_action(pool, session)


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

    try:
        repo.add_message(pool, session_id, role="user", content=body.content)
        start_session_run(
            pool,
            checkpointer,
            llm,
            session_id=session_id,
            task=body.content,
            tavily_api_key=settings.tavily_api_key,
        )
    except Exception as exc:
        # C4 (ADR-020): without this, an exception anywhere from here on
        # (a provider construction error, a DB blip on add_message itself, a
        # genuine bug) left the row `running` forever — repo.start_session's
        # WHERE status='created' guard then turns every retry into a 409,
        # permanently. A session must always land on a terminal status, even
        # when the run itself never got the chance to report one. add_message
        # is inside this try for the same reason: it is one more write that
        # happens after the row is already committed `running`, so it must be
        # covered too, not just the run call.
        logger.exception("session_run_failed session_id=%s", session_id)
        repo.add_trace_event(
            pool, session_id, node="system", detail=f"CRASH: the run failed unexpectedly: {exc}"
        )
        repo.update_session_status(
            pool, session_id, status="failed", final_answer=_RUN_CRASH_MESSAGE
        )
        raise HTTPException(
            status_code=502,
            detail="the agent run failed unexpectedly; the session has been marked failed",
        ) from exc
    return session_with_pending_action(pool, repo.get_session(pool, session_id))


@router.get("/sessions/{session_id}/trace", response_model=list[TraceEventResponse])
def get_trace(
    session_id: UUID, pool: ConnectionPool = Depends(get_db_pool)
) -> list[dict[str, Any]]:
    if repo.get_session(pool, session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")
    return repo.list_trace_events(pool, session_id)
