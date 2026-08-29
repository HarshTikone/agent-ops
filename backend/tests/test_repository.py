"""Repository functions against the real Supabase Postgres project
(ADR-014) — these tests exist to catch exactly the kind of bug live
verification already caught once while building this module: `tool_args`
being a plain `dict` silently fails to adapt to a `jsonb` column with
psycopg3 unless wrapped in `Jsonb(...)`, something a mocked cursor would
never have surfaced.
"""

from __future__ import annotations

import uuid

from app import repository as repo


def test_create_and_get_session(db_pool) -> None:
    row = repo.create_session(db_pool, task="what is 2 + 2?")
    try:
        assert row["status"] == "running"
        assert row["final_answer"] is None

        fetched = repo.get_session(db_pool, row["id"])
        assert fetched["task"] == "what is 2 + 2?"
    finally:
        with db_pool.connection() as conn:
            conn.execute("DELETE FROM sessions WHERE id = %s", (row["id"],))


def test_get_session_returns_none_when_missing(db_pool) -> None:
    assert repo.get_session(db_pool, uuid.uuid4()) is None


def test_create_session_with_no_task_starts_in_created_status(db_pool) -> None:
    row = repo.create_session(db_pool)
    try:
        assert row["status"] == "created"
        assert row["task"] == ""
    finally:
        with db_pool.connection() as conn:
            conn.execute("DELETE FROM sessions WHERE id = %s", (row["id"],))


def test_start_session_moves_created_to_running_and_sets_task(db_pool) -> None:
    created = repo.create_session(db_pool)
    started = repo.start_session(db_pool, created["id"], task="what is 2+2?")
    try:
        assert started["status"] == "running"
        assert started["task"] == "what is 2+2?"
    finally:
        with db_pool.connection() as conn:
            conn.execute("DELETE FROM sessions WHERE id = %s", (created["id"],))


def test_start_session_is_a_no_op_on_an_already_started_session(db_pool) -> None:
    created = repo.create_session(db_pool)
    repo.start_session(db_pool, created["id"], task="first task")
    second_attempt = repo.start_session(db_pool, created["id"], task="second task")
    try:
        assert second_attempt is None
        assert repo.get_session(db_pool, created["id"])["task"] == "first task"
    finally:
        with db_pool.connection() as conn:
            conn.execute("DELETE FROM sessions WHERE id = %s", (created["id"],))


def test_list_sessions_returns_most_recent_first(db_pool) -> None:
    older = repo.create_session(db_pool, task="older")
    newer = repo.create_session(db_pool, task="newer")
    try:
        ids_in_order = [s["id"] for s in repo.list_sessions(db_pool)]
        assert ids_in_order.index(newer["id"]) < ids_in_order.index(older["id"])
    finally:
        with db_pool.connection() as conn:
            conn.execute("DELETE FROM sessions WHERE id IN (%s, %s)", (older["id"], newer["id"]))


def test_list_sessions_embeds_pending_action_in_same_query(db_pool, session_row) -> None:
    action = repo.create_pending_action(
        db_pool,
        session_row["id"],
        tool_name="notes_store",
        tool_args={"action": "write", "key": "release", "content": "ready"},
    )

    listed = next(row for row in repo.list_sessions(db_pool) if row["id"] == session_row["id"])

    assert listed["pending_action"]["id"] == str(action["id"])
    assert listed["pending_action"]["session_id"] == str(session_row["id"])
    assert listed["pending_action"]["tool_args"]["key"] == "release"


def test_get_pending_action_for_session_finds_the_live_one(db_pool, session_row) -> None:
    assert repo.get_pending_action_for_session(db_pool, session_row["id"]) is None

    created = repo.create_pending_action(
        db_pool, session_row["id"], tool_name="notes_store", tool_args={"action": "write"}
    )
    found = repo.get_pending_action_for_session(db_pool, session_row["id"])
    assert found["id"] == created["id"]

    repo.decide_pending_action(db_pool, created["id"], status="approved")
    # decided — no longer the "live" pending one
    assert repo.get_pending_action_for_session(db_pool, session_row["id"]) is None


def test_update_session_status_sets_final_answer(db_pool, session_row) -> None:
    repo.update_session_status(
        db_pool, session_row["id"], status="done", final_answer="the answer is 4"
    )
    fetched = repo.get_session(db_pool, session_row["id"])
    assert fetched["status"] == "done"
    assert fetched["final_answer"] == "the answer is 4"


def test_status_only_update_preserves_existing_final_answer(db_pool, session_row) -> None:
    repo.update_session_status(
        db_pool, session_row["id"], status="done", final_answer="keep this answer"
    )
    repo.update_session_status(db_pool, session_row["id"], status="failed")
    assert repo.get_session(db_pool, session_row["id"])["final_answer"] == "keep this answer"


def test_messages_round_trip_in_order(db_pool, session_row) -> None:
    repo.add_message(db_pool, session_row["id"], role="user", content="first")
    repo.add_message(db_pool, session_row["id"], role="assistant", content="second")

    messages = repo.list_messages(db_pool, session_row["id"])
    assert [m["content"] for m in messages] == ["first", "second"]
    assert [m["role"] for m in messages] == ["user", "assistant"]


def test_trace_events_round_trip_in_order(db_pool, session_row) -> None:
    repo.add_trace_event(db_pool, session_row["id"], node="planner", detail="a", provider="gemini")
    repo.add_trace_event(db_pool, session_row["id"], node="delegate", detail="b", provider=None)

    events = repo.list_trace_events(db_pool, session_row["id"])
    assert [e["node"] for e in events] == ["planner", "delegate"]
    assert [e["sequence"] for e in events] == [1, 2]
    assert [e["level"] for e in events] == ["info", "info"]
    assert events[0]["provider"] == "gemini"
    assert events[1]["provider"] is None


def test_trace_sequence_makes_replayed_event_idempotent(db_pool, session_row) -> None:
    first = repo.add_trace_event(
        db_pool,
        session_row["id"],
        sequence=1,
        node="planner",
        detail="planned",
        level="success",
        provider="gemini",
    )
    replay = repo.add_trace_event(
        db_pool,
        session_row["id"],
        sequence=1,
        node="planner",
        detail="planned",
        level="success",
        provider="gemini",
    )
    assert first is not None
    assert replay is None
    assert len(repo.list_trace_events(db_pool, session_row["id"])) == 1


def test_pending_action_jsonb_args_round_trip(db_pool, session_row) -> None:
    """The regression case: a nested dict as tool_args, verified against a
    REAL jsonb column, not a mock that would happily accept any Python
    object without ever checking psycopg's adapter behavior."""
    args = {"action": "write", "key": "x", "content": "y", "nested": {"a": [1, 2, 3]}}
    created = repo.create_pending_action(
        db_pool, session_row["id"], tool_name="notes_store", tool_args=args
    )
    assert created["status"] == "pending"
    assert created["tool_args"] == args

    fetched = repo.get_pending_action(db_pool, created["id"])
    assert fetched["tool_args"] == args


def test_decide_pending_action_moves_out_of_pending(db_pool, session_row) -> None:
    created = repo.create_pending_action(
        db_pool, session_row["id"], tool_name="calculator", tool_args={"expression": "1+1"}
    )
    decided = repo.decide_pending_action(db_pool, created["id"], status="approved")
    assert decided["status"] == "approved"
    assert decided["decided_at"] is not None


def test_deciding_an_already_decided_action_is_a_no_op_not_a_double_apply(
    db_pool, session_row
) -> None:
    created = repo.create_pending_action(
        db_pool, session_row["id"], tool_name="calculator", tool_args={"expression": "1+1"}
    )
    first = repo.decide_pending_action(db_pool, created["id"], status="approved")
    second = repo.decide_pending_action(db_pool, created["id"], status="rejected")

    assert first is not None
    assert second is None  # already decided — must not silently flip to rejected
    assert repo.get_pending_action(db_pool, created["id"])["status"] == "approved"


def test_mark_pending_action_executed_requires_prior_approval(db_pool, session_row) -> None:
    created = repo.create_pending_action(
        db_pool, session_row["id"], tool_name="calculator", tool_args={"expression": "1+1"}
    )
    # still 'pending' — marking executed must be a no-op, not a status skip
    repo.mark_pending_action_executed(db_pool, created["id"])
    assert repo.get_pending_action(db_pool, created["id"])["status"] == "pending"

    repo.decide_pending_action(db_pool, created["id"], status="approved")
    repo.mark_pending_action_executed(db_pool, created["id"])
    assert repo.get_pending_action(db_pool, created["id"])["status"] == "executed"


def test_write_note_then_read_note_round_trips(db_pool, session_row) -> None:
    repo.write_note(db_pool, session_row["id"], key="topic", content="agent ops")
    assert repo.read_note(db_pool, session_row["id"], key="topic") == "agent ops"


def test_write_note_upserts_on_repeat_key(db_pool, session_row) -> None:
    repo.write_note(db_pool, session_row["id"], key="topic", content="first")
    repo.write_note(db_pool, session_row["id"], key="topic", content="second")
    assert repo.read_note(db_pool, session_row["id"], key="topic") == "second"
    assert repo.list_note_keys(db_pool, session_row["id"]) == ["topic"]


def test_read_note_returns_none_when_missing(db_pool, session_row) -> None:
    assert repo.read_note(db_pool, session_row["id"], key="does-not-exist") is None


def test_notes_are_scoped_per_session(db_pool) -> None:
    session_a = repo.create_session(db_pool, task="a")
    session_b = repo.create_session(db_pool, task="b")
    try:
        repo.write_note(db_pool, session_a["id"], key="k", content="only in a")
        assert repo.read_note(db_pool, session_b["id"], key="k") is None
    finally:
        with db_pool.connection() as conn:
            conn.execute(
                "DELETE FROM sessions WHERE id IN (%s, %s)", (session_a["id"], session_b["id"])
            )


def test_deleting_a_session_cascades_to_children(db_pool) -> None:
    session = repo.create_session(db_pool, task="to be deleted")
    repo.add_message(db_pool, session["id"], role="user", content="hi")
    repo.add_trace_event(db_pool, session["id"], node="planner", detail="d")
    repo.create_pending_action(db_pool, session["id"], tool_name="calculator", tool_args={})
    repo.write_note(db_pool, session["id"], key="k", content="v")

    with db_pool.connection() as conn:
        conn.execute("DELETE FROM sessions WHERE id = %s", (session["id"],))

    assert repo.get_session(db_pool, session["id"]) is None
    assert repo.list_messages(db_pool, session["id"]) == []
    assert repo.list_trace_events(db_pool, session["id"]) == []
