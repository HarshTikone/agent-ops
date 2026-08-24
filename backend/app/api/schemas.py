"""Response/request models shared across the sessions and approvals
routers — `PendingActionResponse` is embedded inside `SessionResponse`
(ADR-018), so both routers need the same shape.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class PendingActionResponse(BaseModel):
    id: UUID
    session_id: UUID
    tool_name: str
    tool_args: dict
    status: str
    reason: str | None
    created_at: datetime
    decided_at: datetime | None


class SessionResponse(BaseModel):
    id: UUID
    task: str
    status: str
    final_answer: str | None
    created_at: datetime
    updated_at: datetime
    # Populated only when status == "awaiting_approval" (ADR-015/ADR-018) —
    # the approval modal's entire data need in one fetch, no second round
    # trip to find out what's pending.
    pending_action: PendingActionResponse | None = None


class TraceEventResponse(BaseModel):
    id: int
    session_id: UUID
    node: str
    detail: str
    provider: str | None
    created_at: datetime


class CreateMessageRequest(BaseModel):
    content: str


class RejectRequest(BaseModel):
    reason: str | None = None
