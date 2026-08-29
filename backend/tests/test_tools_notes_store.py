"""NotesStoreTool: Supabase-backed (ADR-014), against the real database —
same rationale as test_repository.py: a mocked cursor wouldn't have caught
the jsonb-adapter bug that live verification found while wiring this up.
"""

from __future__ import annotations

from uuid import uuid4

import psycopg
import pytest

from app import repository as repo
from app.tools.errors import ToolError
from app.tools.notes_store import NotesStoreTool


@pytest.fixture
def notes(db_pool, session_row) -> NotesStoreTool:
    return NotesStoreTool(db_pool, session_row["id"])


def test_write_then_read_round_trips(notes: NotesStoreTool) -> None:
    assert notes.run(action="write", key="topic", content="agent ops") == "saved note 'topic'"
    assert notes.run(action="read", key="topic") == "agent ops"


def test_list_reflects_written_keys(notes: NotesStoreTool) -> None:
    notes.run(action="write", key="a", content="1")
    notes.run(action="write", key="b", content="2")
    assert notes.run(action="list") == "a, b"


def test_list_with_no_notes_is_not_an_error(notes: NotesStoreTool) -> None:
    assert notes.run(action="list") == "(no notes saved yet)"


def test_read_missing_key_raises_permanent_tool_error(notes: NotesStoreTool) -> None:
    with pytest.raises(ToolError) as exc_info:
        notes.run(action="read", key="does-not-exist")
    assert exc_info.value.transient is False


def test_write_without_content_raises_permanent_tool_error(notes: NotesStoreTool) -> None:
    with pytest.raises(ToolError) as exc_info:
        notes.run(action="write", key="k", content=None)
    assert exc_info.value.transient is False


def test_note_schema_rejects_whitespace_only_key() -> None:
    notes = NotesStoreTool(object(), uuid4())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="note key must not be blank"):
        notes.invoke({"action": "read", "key": "   "})


def test_unknown_action_raises_permanent_tool_error(notes: NotesStoreTool) -> None:
    with pytest.raises(ToolError) as exc_info:
        notes.run(action="delete", key="k")
    assert exc_info.value.transient is False


def test_operational_error_is_transient_and_redacts_connection_credentials(monkeypatch) -> None:
    tool = NotesStoreTool(object(), uuid4())  # type: ignore[arg-type]

    def fail(*args, **kwargs):
        raise psycopg.OperationalError("postgresql://operator:secret@db.example/test")

    monkeypatch.setattr(repo, "read_note", fail)
    with pytest.raises(ToolError) as exc_info:
        tool.run(action="read", key="topic")
    assert exc_info.value.transient is True
    assert "secret" not in str(exc_info.value)


def test_integrity_error_is_permanent(monkeypatch) -> None:
    tool = NotesStoreTool(object(), uuid4())  # type: ignore[arg-type]

    def fail(*args, **kwargs):
        raise psycopg.IntegrityError("constraint")

    monkeypatch.setattr(repo, "write_note", fail)
    with pytest.raises(ToolError) as exc_info:
        tool.run(action="write", key="topic", content="value")
    assert exc_info.value.transient is False


def test_two_sessions_do_not_share_notes(db_pool, session_row) -> None:
    """Confirms notes are scoped per session_id, not global — the whole
    point of moving this off an in-process dict (ADR-011)."""
    from app import repository as repo

    other_session = repo.create_session(db_pool, task="other")
    try:
        first = NotesStoreTool(db_pool, session_row["id"])
        second = NotesStoreTool(db_pool, other_session["id"])
        first.run(action="write", key="k", content="only in first")
        with pytest.raises(ToolError):
            second.run(action="read", key="k")
    finally:
        with db_pool.connection() as conn:
            conn.execute("DELETE FROM sessions WHERE id = %s", (other_session["id"],))
