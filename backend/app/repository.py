"""Thin CRUD helpers over the Day 3 schema (migrations/0001_initial_schema.sql).

No ORM: the schema is five small tables and the query shapes are simple
enough that SQLAlchemy would be more machinery than this project's scale
justifies (ADR-014). Every function takes the pool explicitly rather than
reaching for a global, so tests can pass a real pool pointed at the same
database the rest of the suite uses.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool


def create_session(pool: ConnectionPool, *, task: str = "") -> dict[str, Any]:
    """`task` is normally left blank at creation time — ARCHITECTURE.md's
    flow is create-session-first, then the first `POST /messages` call
    supplies the task via `start_session` below. The optional override
    exists for tests/scripts that want a one-step session with a known task.
    """
    with pool.connection() as conn:
        if task:
            return conn.execute(
                "INSERT INTO sessions (task, status) VALUES (%s, 'running') "
                "RETURNING id, task, status, final_answer, created_at, updated_at",
                (task,),
            ).fetchone()
        return conn.execute(
            "INSERT INTO sessions DEFAULT VALUES "
            "RETURNING id, task, status, final_answer, created_at, updated_at"
        ).fetchone()


def start_session(pool: ConnectionPool, session_id: UUID, *, task: str) -> dict[str, Any] | None:
    """Moves a session from 'created' to 'running' and records its task —
    only succeeds if it's still 'created', so a second message can't
    silently restart an already-running session (the API layer turns a
    None here into a 409)."""
    with pool.connection() as conn:
        return conn.execute(
            """
            UPDATE sessions SET task = %s, status = 'running', updated_at = now()
            WHERE id = %s AND status = 'created'
            RETURNING id, task, status, final_answer, created_at, updated_at
            """,
            (task, session_id),
        ).fetchone()


def get_session(pool: ConnectionPool, session_id: UUID) -> dict[str, Any] | None:
    with pool.connection() as conn:
        return conn.execute(
            "SELECT id, task, status, final_answer, created_at, updated_at "
            "FROM sessions WHERE id = %s",
            (session_id,),
        ).fetchone()


def update_session_status(
    pool: ConnectionPool, session_id: UUID, *, status: str, final_answer: str | None = None
) -> None:
    with pool.connection() as conn:
        conn.execute(
            "UPDATE sessions SET status = %s, final_answer = %s, updated_at = now() WHERE id = %s",
            (status, final_answer, session_id),
        )


def add_message(
    pool: ConnectionPool, session_id: UUID, *, role: str, content: str
) -> dict[str, Any]:
    with pool.connection() as conn:
        return conn.execute(
            """
            INSERT INTO messages (session_id, role, content) VALUES (%s, %s, %s)
            RETURNING id, session_id, role, content, created_at
            """,
            (session_id, role, content),
        ).fetchone()


def list_messages(pool: ConnectionPool, session_id: UUID) -> list[dict[str, Any]]:
    with pool.connection() as conn:
        return conn.execute(
            "SELECT id, session_id, role, content, created_at FROM messages "
            "WHERE session_id = %s ORDER BY created_at",
            (session_id,),
        ).fetchall()


def add_trace_event(
    pool: ConnectionPool, session_id: UUID, *, node: str, detail: str, provider: str | None = None
) -> dict[str, Any]:
    with pool.connection() as conn:
        return conn.execute(
            """
            INSERT INTO trace_events (session_id, node, detail, provider) VALUES (%s, %s, %s, %s)
            RETURNING id, session_id, node, detail, provider, created_at
            """,
            (session_id, node, detail, provider),
        ).fetchone()


def list_trace_events(pool: ConnectionPool, session_id: UUID) -> list[dict[str, Any]]:
    with pool.connection() as conn:
        return conn.execute(
            "SELECT id, session_id, node, detail, provider, created_at FROM trace_events "
            "WHERE session_id = %s ORDER BY id",
            (session_id,),
        ).fetchall()


def create_pending_action(
    pool: ConnectionPool, session_id: UUID, *, tool_name: str, tool_args: dict[str, Any]
) -> dict[str, Any]:
    with pool.connection() as conn:
        return conn.execute(
            """
            INSERT INTO pending_actions (session_id, tool_name, tool_args) VALUES (%s, %s, %s)
            RETURNING id, session_id, tool_name, tool_args, status, reason, created_at, decided_at
            """,
            (session_id, tool_name, Jsonb(tool_args)),
        ).fetchone()


def get_pending_action(pool: ConnectionPool, pending_action_id: UUID) -> dict[str, Any] | None:
    with pool.connection() as conn:
        return conn.execute(
            "SELECT id, session_id, tool_name, tool_args, status, reason, created_at, decided_at "
            "FROM pending_actions WHERE id = %s",
            (pending_action_id,),
        ).fetchone()


def decide_pending_action(
    pool: ConnectionPool, pending_action_id: UUID, *, status: str, reason: str | None = None
) -> dict[str, Any] | None:
    """Moves a pending_action out of 'pending'. Only succeeds if it is still
    'pending' -- the WHERE clause makes double-deciding (e.g. two concurrent
    approve calls) a no-op that returns None rather than a silent double
    apply, so the caller can tell "already decided" apart from "decided by
    this call."
    """
    with pool.connection() as conn:
        return conn.execute(
            """
            UPDATE pending_actions SET status = %s, reason = %s, decided_at = now()
            WHERE id = %s AND status = 'pending'
            RETURNING id, session_id, tool_name, tool_args, status, reason, created_at, decided_at
            """,
            (status, reason, pending_action_id),
        ).fetchone()


def mark_pending_action_executed(pool: ConnectionPool, pending_action_id: UUID) -> None:
    with pool.connection() as conn:
        conn.execute(
            "UPDATE pending_actions SET status = 'executed' WHERE id = %s AND status = 'approved'",
            (pending_action_id,),
        )


def write_note(pool: ConnectionPool, session_id: UUID, *, key: str, content: str) -> None:
    with pool.connection() as conn:
        conn.execute(
            """
            INSERT INTO session_memory (session_id, key, content) VALUES (%s, %s, %s)
            ON CONFLICT (session_id, key) DO UPDATE SET content = EXCLUDED.content, updated_at = now()
            """,
            (session_id, key, content),
        )


def read_note(pool: ConnectionPool, session_id: UUID, *, key: str) -> str | None:
    with pool.connection() as conn:
        row = conn.execute(
            "SELECT content FROM session_memory WHERE session_id = %s AND key = %s",
            (session_id, key),
        ).fetchone()
    return row["content"] if row else None


def list_note_keys(pool: ConnectionPool, session_id: UUID) -> list[str]:
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT key FROM session_memory WHERE session_id = %s ORDER BY key",
            (session_id,),
        ).fetchall()
    return [row["key"] for row in rows]
