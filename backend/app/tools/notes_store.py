"""Notes/document store tool — Day 2 scope: in-process, per-instance dict.

Repointed at Supabase's `session_memory` table on Day 3 (ARCHITECTURE.md §2)
without changing this class's interface — callers already only see `run()`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

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

    def __init__(self) -> None:
        self._notes: dict[str, str] = {}

    def run(self, *, action: str, key: str | None = None, content: str | None = None) -> str:
        if action == "write":
            if not key or content is None:
                raise ToolError("write requires both 'key' and 'content'", transient=False)
            self._notes[key] = content
            return f"saved note {key!r}"
        if action == "read":
            if not key:
                raise ToolError("read requires 'key'", transient=False)
            if key not in self._notes:
                raise ToolError(f"no note found for key {key!r}", transient=False)
            return self._notes[key]
        if action == "list":
            return ", ".join(sorted(self._notes)) or "(no notes saved yet)"
        raise ToolError(f"unknown action {action!r}", transient=False)
