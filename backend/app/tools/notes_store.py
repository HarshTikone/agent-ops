"""Notes/document store tool — Supabase-backed (ADR-014), per session.

Day 2 shipped this as an in-process dict and promised (ADR-011) it would be
"repointed at Supabase's session_memory table on Day 3 without changing this
class's interface" — only the constructor changed (pool + session_id instead
of nothing); `run()`'s signature and behavior are identical.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

import psycopg
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, Field

from app import repository as repo
from app.tools.errors import ToolError


class NotesStoreArgs(BaseModel):
    action: Literal["write", "read", "list"]
    key: str | None = Field(default=None, description="Note key — required for write/read")
    content: str | None = Field(default=None, description="Note content — required for write")


class NotesStoreTool:
    name = "notes_store"
    description = (
        "Read, write, or list session notes. Use to persist information "
        "produced by one step so a later step can read it back."
    )
    args_schema = NotesStoreArgs

    def __init__(self, pool: ConnectionPool, session_id: UUID) -> None:
        self._pool = pool
        self._session_id = session_id

    def run(self, *, action: str, key: str | None = None, content: str | None = None) -> str:
        try:
            return self._run(action=action, key=key, content=content)
        except psycopg.OperationalError as exc:
            # Connection lost / couldn't reach Postgres — transient, unlike
            # every other failure path here (ARCHITECTURE.md §6).
            raise ToolError(f"notes store database error: {exc}", transient=True) from exc

    def _run(self, *, action: str, key: str | None, content: str | None) -> str:
        if action == "write":
            if not key or content is None:
                raise ToolError("write requires both 'key' and 'content'", transient=False)
            repo.write_note(self._pool, self._session_id, key=key, content=content)
            return f"saved note {key!r}"
        if action == "read":
            if not key:
                raise ToolError("read requires 'key'", transient=False)
            result = repo.read_note(self._pool, self._session_id, key=key)
            if result is None:
                raise ToolError(f"no note found for key {key!r}", transient=False)
            return result
        if action == "list":
            keys = repo.list_note_keys(self._pool, self._session_id)
            return ", ".join(keys) or "(no notes saved yet)"
        raise ToolError(f"unknown action {action!r}", transient=False)
