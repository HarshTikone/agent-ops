"""Approval endpoints — the pending_actions state machine's HTTP surface
(ARCHITECTURE.md §2, ADR-015): pending -> approved/rejected -> executed.

Returns the SESSION (with its embedded pending_action, ADR-018), not the
bare decided pending_action — a caller deciding an approval needs to know
what the session's state is *now* (done? failed? paused again on a new
approval?), which the decided action alone can't tell it without a second
round trip.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from langgraph.checkpoint.base import BaseCheckpointSaver
from psycopg_pool import ConnectionPool

from app import repository as repo
from app.api.schemas import RejectRequest, SessionResponse
from app.api.sessions import session_with_pending_action
from app.config import Settings, get_settings
from app.db import get_checkpointer, get_db_pool
from app.dependencies import get_llm_provider
from app.llm.base import LLMProvider
from app.session_runner import resume_session_run

router = APIRouter(tags=["approvals"])


def _decide(
    pending_action_id: UUID,
    *,
    approve: bool,
    reason: str | None,
    pool: ConnectionPool,
    checkpointer: BaseCheckpointSaver,
    llm: LLMProvider,
    settings: Settings,
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

    resume_session_run(
        pool,
        checkpointer,
        llm,
        session_id=decided["session_id"],
        approved=approve,
        tavily_api_key=settings.tavily_api_key,
    )
    if approve:
        # "executed" specifically means "the tool this pending_action named
        # was attempted" — set right after the resume that let it run, not
        # tied to whether the REST of the session's run goes on to succeed.
        repo.mark_pending_action_executed(pool, pending_action_id)

    session = repo.get_session(pool, decided["session_id"])
    return session_with_pending_action(pool, session)


@router.post("/approvals/{pending_action_id}/approve", response_model=SessionResponse)
def approve(
    pending_action_id: UUID,
    pool: ConnectionPool = Depends(get_db_pool),
    checkpointer: BaseCheckpointSaver = Depends(get_checkpointer),
    llm: LLMProvider = Depends(get_llm_provider),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    return _decide(
        pending_action_id,
        approve=True,
        reason=None,
        pool=pool,
        checkpointer=checkpointer,
        llm=llm,
        settings=settings,
    )


@router.post("/approvals/{pending_action_id}/reject", response_model=SessionResponse)
def reject(
    pending_action_id: UUID,
    body: RejectRequest,
    pool: ConnectionPool = Depends(get_db_pool),
    checkpointer: BaseCheckpointSaver = Depends(get_checkpointer),
    llm: LLMProvider = Depends(get_llm_provider),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    return _decide(
        pending_action_id,
        approve=False,
        reason=body.reason,
        pool=pool,
        checkpointer=checkpointer,
        llm=llm,
        settings=settings,
    )
