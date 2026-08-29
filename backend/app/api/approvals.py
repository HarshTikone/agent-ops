"""Approval endpoints — the pending_actions state machine's HTTP surface
(ARCHITECTURE.md §2, ADR-015): pending -> approved/rejected -> executed.

Returns the SESSION (with its embedded pending_action, ADR-018), not the
bare decided pending_action — a caller deciding an approval needs to know
what the session's state is *now* (done? failed? paused again on a new
approval?), which the decided action alone can't tell it without a second
round trip.
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
from app.api.schemas import RejectRequest, SessionResponse, validate_reject_request
from app.api.sessions import session_with_pending_action
from app.config import Settings, get_settings
from app.db import DbPool, get_checkpointer, get_db_pool
from app.dependencies import get_llm_provider
from app.llm.base import LLMProvider
from app.rate_limit import limiter
from app.resources import get_http_client
from app.sanitization import sanitize_error
from app.security import require_operator_key
from app.session_runner import resume_session_run

logger = logging.getLogger("agent_ops.api.approvals")

router = APIRouter(tags=["approvals"])

_RUN_CRASH_MESSAGE = "The agent run failed unexpectedly after this decision."


def _decide(
    pending_action_id: UUID,
    *,
    approve: bool,
    reason: str | None,
    pool: DbPool,
    checkpointer: BaseCheckpointSaver,
    llm: LLMProvider,
    settings: Settings,
    http_client: httpx.Client,
) -> dict[str, Any]:
    existing = repo.get_pending_action(pool, pending_action_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="pending action not found")

    # The WHERE status='pending' guard in decide_pending_action is what
    # actually prevents a double-apply (e.g. two concurrent approve calls);
    # this check just turns that into a clear 409 instead of the caller
    # silently getting back a row that doesn't reflect what they asked for.
    decided = repo.decide_pending_action(
        pool, pending_action_id, status="approved" if approve else "rejected", reason=reason
    )
    if decided is None:
        raise HTTPException(
            status_code=409, detail=f"pending action already {existing['status']}, not 'pending'"
        )

    try:
        resume_session_run(
            pool,
            checkpointer,
            llm,
            session_id=decided["session_id"],
            approved=approve,
            tavily_api_key=settings.tavily_api_key,
            pending_action_id=pending_action_id,
            http_client=http_client,
        )
    except Exception as exc:
        logger.error(
            "resume_run_failed session_id=%s pending_action_id=%s traceback=%s",
            decided["session_id"],
            pending_action_id,
            sanitize_error(traceback.format_exc(), max_length=8_000),
        )
        repo.add_trace_event(
            pool,
            decided["session_id"],
            node="system",
            detail=f"CRASH: resume after {'approve' if approve else 'reject'} failed unexpectedly",
        )
        repo.update_session_status(
            pool, decided["session_id"], status="failed", final_answer=_RUN_CRASH_MESSAGE
        )
        raise HTTPException(
            status_code=502,
            detail="the agent run failed unexpectedly after this decision; the session has been marked failed",
        ) from exc

    session = repo.get_session(pool, decided["session_id"])
    if session is None:
        raise HTTPException(status_code=404, detail="session was deleted while the run completed")
    return session_with_pending_action(pool, session)


@router.post(
    "/approvals/{pending_action_id}/approve",
    response_model=SessionResponse,
    dependencies=[Depends(require_operator_key)],
)
@limiter.limit("10/minute")
def approve(
    request: Request,
    pending_action_id: UUID,
    pool: DbPool = Depends(get_db_pool),
    checkpointer: BaseCheckpointSaver = Depends(get_checkpointer),
    llm: LLMProvider = Depends(get_llm_provider),
    settings: Settings = Depends(get_settings),
    http_client: httpx.Client = Depends(get_http_client),
) -> dict[str, Any]:
    del request
    return _decide(
        pending_action_id,
        approve=True,
        reason=None,
        pool=pool,
        checkpointer=checkpointer,
        llm=llm,
        settings=settings,
        http_client=http_client,
    )


@router.post(
    "/approvals/{pending_action_id}/reject",
    response_model=SessionResponse,
    dependencies=[Depends(require_operator_key)],
)
@limiter.limit("10/minute")
def reject(
    request: Request,
    pending_action_id: UUID,
    body: RejectRequest = Depends(validate_reject_request),
    pool: DbPool = Depends(get_db_pool),
    checkpointer: BaseCheckpointSaver = Depends(get_checkpointer),
    llm: LLMProvider = Depends(get_llm_provider),
    settings: Settings = Depends(get_settings),
    http_client: httpx.Client = Depends(get_http_client),
) -> dict[str, Any]:
    del request
    return _decide(
        pending_action_id,
        approve=False,
        reason=body.reason,
        pool=pool,
        checkpointer=checkpointer,
        llm=llm,
        settings=settings,
        http_client=http_client,
    )
