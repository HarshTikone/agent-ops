"""Response/request models shared across the sessions and approvals
routers — `PendingActionResponse` is embedded inside `SessionResponse`
(ADR-018), so both routers need the same shape.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import Query
from pydantic import BaseModel, Field, field_validator


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
    sequence: int
    node: str
    detail: str
    level: str
    provider: str | None
    created_at: datetime


class CreateMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=8_000)

    @field_validator("content")
    @classmethod
    def trim_content(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("message content must not be blank")
        return value


class RejectRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=1_000)

    @field_validator("reason")
    @classmethod
    def trim_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


def validate_message_request(body: CreateMessageRequest) -> CreateMessageRequest:
    """Dependency wrapper ensures body validation precedes infrastructure."""
    return body


def validate_reject_request(body: RejectRequest) -> RejectRequest:
    return body


def validate_session_limit(limit: int = Query(default=50, ge=1, le=100)) -> int:
    return limit
