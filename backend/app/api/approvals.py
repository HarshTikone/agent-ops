"""Approval endpoints — the pending_actions state machine's HTTP surface
(ARCHITECTURE.md §2, ADR-015): pending -> approved/rejected -> executed.
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
from app.session_runner import resume_session_run

router = APIRouter(tags=["approvals"])


class PendingActionResponse(BaseModel):
    id: UUID
    session_id: UUID
    tool_name: str
    tool_args: dict
    status: str
    reason: str | None
    created_at: datetime
    decided_at: datetime | None


class RejectRequest(BaseModel):
    reason: str | None = None


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

    return repo.get_pending_action(pool, pending_action_id)


@router.post("/approvals/{pending_action_id}/approve", response_model=PendingActionResponse)
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


@router.post("/approvals/{pending_action_id}/reject", response_model=PendingActionResponse)
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
