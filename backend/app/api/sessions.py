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
import traceback
from typing import Any
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from langgraph.checkpoint.base import BaseCheckpointSaver

from app import repository as repo
from app.api.schemas import (
    CreateMessageRequest,
    MessageResponse,
    SessionResponse,
    TraceEventResponse,
    validate_message_request,
    validate_session_limit,
)
from app.config import Settings, get_settings
from app.db import DbPool, get_checkpointer, get_db_pool
from app.dependencies import get_llm_provider
from app.llm.base import LLMProvider
from app.rate_limit import limiter
from app.resources import get_http_client
from app.sanitization import sanitize_error
from app.security import require_operator_key
from app.session_runner import continue_session_run, start_session_run

logger = logging.getLogger("agent_ops.api.sessions")

router = APIRouter(tags=["sessions"])

_RUN_CRASH_MESSAGE = "The agent run failed unexpectedly."


def session_with_pending_action(pool: DbPool, session: dict[str, Any]) -> dict[str, Any]:
    pending_action = None
    if session["status"] == "awaiting_approval":
        pending_action = repo.get_pending_action_for_session(pool, session["id"])
    return {**session, "pending_action": pending_action}


@router.post(
    "/sessions",
    response_model=SessionResponse,
    status_code=201,
    dependencies=[Depends(require_operator_key)],
)
@limiter.limit("20/minute")
def create_session(request: Request, pool: DbPool = Depends(get_db_pool)) -> dict[str, Any]:
    del request
    return session_with_pending_action(pool, repo.create_session(pool))


@router.get("/sessions", response_model=list[SessionResponse])
def list_sessions(
    limit: int = Depends(validate_session_limit),
    include_archived: bool = False,
    pool: DbPool = Depends(get_db_pool),
) -> list[dict[str, Any]]:
    return repo.list_sessions(pool, limit=limit, include_archived=include_archived)


@router.get("/sessions/{session_id}", response_model=SessionResponse)
def get_session(session_id: UUID, pool: DbPool = Depends(get_db_pool)) -> dict[str, Any]:
    session = repo.get_session(pool, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return session_with_pending_action(pool, session)


@router.post(
    "/sessions/{session_id}/messages",
    response_model=SessionResponse,
    dependencies=[Depends(require_operator_key)],
)
@limiter.limit("5/minute")
def send_message(
    request: Request,
    session_id: UUID,
    body: CreateMessageRequest = Depends(validate_message_request),
    pool: DbPool = Depends(get_db_pool),
    checkpointer: BaseCheckpointSaver = Depends(get_checkpointer),
    llm: LLMProvider = Depends(get_llm_provider),
    settings: Settings = Depends(get_settings),
    http_client: httpx.Client = Depends(get_http_client),
) -> dict[str, Any]:
    del request
    session = repo.get_session(pool, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    # ADR-033 supersedes ADR-015's one-task-per-session boundary: a
    # session's FIRST message starts its one graph run (start_session); a
    # message to a session that already finished a prior turn (done/
    # degraded/failed) starts a follow-up one on the same thread instead
    # (restart_session) so it can build on what the agent already did. A
    # session still running/paused matches neither WHERE clause, so a
    # second message there is still a clear 409, not a silent no-op or an
    # implicit "start a new unrelated run."
    is_continuation = False
    started = repo.start_session(pool, session_id, task=body.content)
    if started is None:
        started = repo.restart_session(pool, session_id, task=body.content)
        is_continuation = started is not None
    if started is None:
        raise HTTPException(
            status_code=409,
            detail=(f"session is '{session['status']}', not accepting a new message right now"),
        )

    try:
        repo.add_message(pool, session_id, role="user", content=body.content)
        run = continue_session_run if is_continuation else start_session_run
        run(
            pool,
            checkpointer,
            llm,
            session_id=session_id,
            task=body.content,
            tavily_api_key=settings.tavily_api_key,
            http_client=http_client,
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
        logger.error(
            "session_run_failed session_id=%s traceback=%s",
            session_id,
            sanitize_error(traceback.format_exc(), max_length=8_000),
        )
        repo.add_trace_event(
            pool, session_id, node="system", detail="CRASH: the run failed unexpectedly"
        )
        repo.update_session_status(
            pool, session_id, status="failed", final_answer=_RUN_CRASH_MESSAGE
        )
        raise HTTPException(
            status_code=502,
            detail="the agent run failed unexpectedly; the session has been marked failed",
        ) from exc
    completed = repo.get_session(pool, session_id)
    if completed is None:
        raise HTTPException(status_code=404, detail="session was deleted while the run completed")
    return session_with_pending_action(pool, completed)


@router.post(
    "/sessions/{session_id}/archive",
    response_model=SessionResponse,
    dependencies=[Depends(require_operator_key)],
)
@limiter.limit("20/minute")
def archive_session(
    request: Request, session_id: UUID, pool: DbPool = Depends(get_db_pool)
) -> dict[str, Any]:
    del request
    archived = repo.archive_session(pool, session_id)
    if archived is None:
        raise HTTPException(status_code=404, detail="session not found")
    return session_with_pending_action(pool, archived)


@router.post(
    "/sessions/{session_id}/restore",
    response_model=SessionResponse,
    dependencies=[Depends(require_operator_key)],
)
@limiter.limit("20/minute")
def restore_session(
    request: Request, session_id: UUID, pool: DbPool = Depends(get_db_pool)
) -> dict[str, Any]:
    del request
    restored = repo.restore_session(pool, session_id)
    if restored is None:
        raise HTTPException(status_code=404, detail="session not found")
    return session_with_pending_action(pool, restored)


@router.get("/sessions/{session_id}/trace", response_model=list[TraceEventResponse])
def get_trace(session_id: UUID, pool: DbPool = Depends(get_db_pool)) -> list[dict[str, Any]]:
    if repo.get_session(pool, session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")
    return repo.list_trace_events(pool, session_id)


@router.get("/sessions/{session_id}/messages", response_model=list[MessageResponse])
def get_messages(session_id: UUID, pool: DbPool = Depends(get_db_pool)) -> list[dict[str, Any]]:
    """The full multi-turn conversation (WP5, ADR-036) -- every user/
    assistant message across every turn, in order. Read-only and
    unauthenticated like `/trace`; the mutating `POST` at this same path is
    a separate route (FastAPI dispatches on method, not just path)."""
    if repo.get_session(pool, session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")
    return repo.list_messages(pool, session_id)
