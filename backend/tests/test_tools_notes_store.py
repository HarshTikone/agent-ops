"""NotesStoreTool: in-process, per-instance dict (Day 2 stand-in for Day 3's
Supabase-backed session_memory)."""

import pytest

from app.tools.errors import ToolError
from app.tools.notes_store import NotesStoreTool


@pytest.fixture
def notes() -> NotesStoreTool:
    return NotesStoreTool()


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


def test_unknown_action_raises_permanent_tool_error(notes: NotesStoreTool) -> None:
    with pytest.raises(ToolError) as exc_info:
        notes.run(action="delete", key="k")
    assert exc_info.value.transient is False


def test_two_instances_do_not_share_state() -> None:
    """Confirms the store is per-instance, not module-global — important
    since each session gets its own NotesStoreTool (ADR-011)."""
    first, second = NotesStoreTool(), NotesStoreTool()
    first.run(action="write", key="k", content="only in first")
    with pytest.raises(ToolError):
        second.run(action="read", key="k")
