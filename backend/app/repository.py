"""Thin CRUD helpers over the Day 3 schema (migrations/0001_initial_schema.sql).

No ORM: the schema is five small tables and the query shapes are simple
enough that SQLAlchemy would be more machinery than this project's scale
justifies (ADR-014). Every function takes the pool explicitly rather than
reaching for a global, so tests can pass a real pool pointed at the same
database the rest of the suite uses.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from psycopg.types.json import Jsonb

from app.db import DbConnection, DbPool

TraceLevel = Literal["info", "success", "warning", "error"]
_UNSET = object()


def _required_row(row: dict[str, Any] | None, *, operation: str) -> dict[str, Any]:
    if row is None:
        raise RuntimeError(f"{operation} did not return the inserted row")
    return row


def create_session(pool: DbPool, *, task: str = "") -> dict[str, Any]:
    """`task` is normally left blank at creation time — ARCHITECTURE.md's
    flow is create-session-first, then the first `POST /messages` call
    supplies the task via `start_session` below. The optional override
    exists for tests/scripts that want a one-step session with a known task.
    """
    with pool.connection() as conn:
        if task:
            return _required_row(
                conn.execute(
                    "INSERT INTO sessions (task, status) VALUES (%s, 'running') "
                    "RETURNING id, task, status, final_answer, archived_at, created_at, updated_at",
                    (task,),
                ).fetchone(),
                operation="create session",
            )
        return _required_row(
            conn.execute(
                "INSERT INTO sessions DEFAULT VALUES "
                "RETURNING id, task, status, final_answer, archived_at, created_at, updated_at"
            ).fetchone(),
            operation="create session",
        )


def start_session(pool: DbPool, session_id: UUID, *, task: str) -> dict[str, Any] | None:
    """Moves a session from 'created' to 'running' and records its task —
    only succeeds if it's still 'created', so a second message can't
    silently restart an already-running session (the API layer turns a
    None here into a 409)."""
    with pool.connection() as conn:
        return conn.execute(
            """
            UPDATE sessions SET task = %s, status = 'running', updated_at = now()
            WHERE id = %s AND status = 'created'
            RETURNING id, task, status, final_answer, archived_at, created_at, updated_at
            """,
            (task, session_id),
        ).fetchone()


def restart_session(pool: DbPool, session_id: UUID, *, task: str) -> dict[str, Any] | None:
    """Sibling to `start_session` for a session's SECOND (or later) message
    (ADR-030 supersedes ADR-015's one-task-per-session boundary): only
    succeeds if the session reached a terminal, answer-or-failure-bearing
    status from a prior turn. A session still 'running' or
    'awaiting_approval' is genuinely mid-flight -- a second message there
    would race the first, so those correctly match neither this WHERE
    clause nor `start_session`'s, and the API layer's 409 still applies."""
    with pool.connection() as conn:
        return conn.execute(
            """
            UPDATE sessions SET task = %s, status = 'running', updated_at = now()
            WHERE id = %s AND status IN ('done', 'degraded', 'failed')
            RETURNING id, task, status, final_answer, archived_at, created_at, updated_at
            """,
            (task, session_id),
        ).fetchone()


def get_session(pool: DbPool, session_id: UUID) -> dict[str, Any] | None:
    with pool.connection() as conn:
        return conn.execute(
            "SELECT id, task, status, final_answer, archived_at, created_at, updated_at "
            "FROM sessions WHERE id = %s",
            (session_id,),
        ).fetchone()


def list_sessions(
    pool: DbPool, *, limit: int = 50, include_archived: bool = False
) -> list[dict[str, Any]]:
    """Most recently created first — Day 4's session list (ADR-015 flagged
    this as deferred until the UI shape was known; it's a plain list, no
    pagination cursor, which is all a single-page session list needs).

    Excludes archived sessions by default so QA/demo fixtures don't crowd
    out real activity; `include_archived` is a fixed boolean flag interpolated
    into the query, never user input, so it carries no injection risk."""
    where_clause = "" if include_archived else "WHERE s.archived_at IS NULL"
    with pool.connection() as conn:
        return conn.execute(
            f"""
            SELECT
                s.id,
                s.task,
                s.status,
                s.final_answer,
                s.archived_at,
                s.created_at,
                s.updated_at,
                CASE WHEN pa.id IS NULL THEN NULL ELSE jsonb_build_object(
                    'id', pa.id,
                    'session_id', pa.session_id,
                    'tool_name', pa.tool_name,
                    'tool_args', pa.tool_args,
                    'status', pa.status,
                    'reason', pa.reason,
                    'created_at', pa.created_at,
                    'decided_at', pa.decided_at
                ) END AS pending_action
            FROM sessions AS s
            LEFT JOIN LATERAL (
                SELECT id, session_id, tool_name, tool_args, status, reason, created_at, decided_at
                FROM pending_actions
                WHERE session_id = s.id AND status = 'pending'
                ORDER BY created_at DESC
                LIMIT 1
            ) AS pa ON TRUE
            {where_clause}
            ORDER BY s.created_at DESC
            LIMIT %s
            """,
            (limit,),
        ).fetchall()


def list_sessions_for_maintenance(pool: DbPool) -> list[dict[str, Any]]:
    """Every session, unpaginated and including archived ones -- for offline
    maintenance scripts (archiving, stranded-session reaping) that need the
    full table rather than the API's paginated, unarchived-by-default view."""
    with pool.connection() as conn:
        return conn.execute(
            "SELECT id, task, status, archived_at, created_at, updated_at "
            "FROM sessions ORDER BY created_at"
        ).fetchall()


def archive_session(pool: DbPool, session_id: UUID) -> dict[str, Any] | None:
    """Idempotent: archiving an already-archived session leaves its original
    archived_at timestamp untouched rather than bumping it. None means the
    session doesn't exist."""
    with pool.connection() as conn:
        return conn.execute(
            """
            UPDATE sessions SET archived_at = COALESCE(archived_at, now()), updated_at = now()
            WHERE id = %s
            RETURNING id, task, status, final_answer, archived_at, created_at, updated_at
            """,
            (session_id,),
        ).fetchone()


def restore_session(pool: DbPool, session_id: UUID) -> dict[str, Any] | None:
    """Idempotent: restoring a session that isn't archived is a no-op
    success. None means the session doesn't exist."""
    with pool.connection() as conn:
        return conn.execute(
            """
            UPDATE sessions SET archived_at = NULL, updated_at = now()
            WHERE id = %s
            RETURNING id, task, status, final_answer, archived_at, created_at, updated_at
            """,
            (session_id,),
        ).fetchone()


def update_session_status(
    pool: DbPool,
    session_id: UUID,
    *,
    status: str,
    final_answer: str | None | object = _UNSET,
) -> None:
    with pool.connection() as conn:
        update_session_status_on_connection(
            conn, session_id, status=status, final_answer=final_answer
        )


def update_session_status_on_connection(
    conn: DbConnection,
    session_id: UUID,
    *,
    status: str,
    final_answer: str | None | object = _UNSET,
) -> None:
    if final_answer is _UNSET:
        conn.execute(
            "UPDATE sessions SET status = %s, updated_at = now() WHERE id = %s",
            (status, session_id),
        )
        return
    conn.execute(
        "UPDATE sessions SET status = %s, final_answer = %s, updated_at = now() WHERE id = %s",
        (status, final_answer, session_id),
    )


def add_message(pool: DbPool, session_id: UUID, *, role: str, content: str) -> dict[str, Any]:
    with pool.connection() as conn:
        return add_message_on_connection(conn, session_id, role=role, content=content)


def add_message_on_connection(
    conn: DbConnection, session_id: UUID, *, role: str, content: str
) -> dict[str, Any]:
    return _required_row(
        conn.execute(
            """
        INSERT INTO messages (session_id, role, content) VALUES (%s, %s, %s)
        RETURNING id, session_id, role, content, created_at
        """,
            (session_id, role, content),
        ).fetchone(),
        operation="add message",
    )


def list_messages(pool: DbPool, session_id: UUID) -> list[dict[str, Any]]:
    with pool.connection() as conn:
        return conn.execute(
            "SELECT id, session_id, role, content, created_at FROM messages "
            "WHERE session_id = %s ORDER BY created_at",
            (session_id,),
        ).fetchall()


def add_trace_event(
    pool: DbPool,
    session_id: UUID,
    *,
    node: str,
    detail: str,
    sequence: int | None = None,
    level: TraceLevel = "info",
    provider: str | None = None,
    started_at: str | None = None,
    duration_ms: int | None = None,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    cost_usd: str | None = None,
) -> dict[str, Any] | None:
    with pool.connection() as conn:
        return add_trace_event_on_connection(
            conn,
            session_id,
            node=node,
            detail=detail,
            sequence=sequence,
            level=level,
            provider=provider,
            started_at=started_at,
            duration_ms=duration_ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
        )


def add_trace_event_on_connection(
    conn: DbConnection,
    session_id: UUID,
    *,
    node: str,
    detail: str,
    sequence: int | None = None,
    level: TraceLevel = "info",
    provider: str | None = None,
    started_at: str | None = None,
    duration_ms: int | None = None,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    cost_usd: str | None = None,
) -> dict[str, Any] | None:
    if sequence is None:
        row = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence "
            "FROM trace_events WHERE session_id = %s",
            (session_id,),
        ).fetchone()
        if row is None:
            raise RuntimeError("trace sequence query returned no row")
        sequence = row["sequence"]
    return conn.execute(
        """
        INSERT INTO trace_events (
            session_id, sequence, node, detail, level, provider,
            started_at, duration_ms, tokens_in, tokens_out, cost_usd
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (session_id, sequence) DO NOTHING
        RETURNING id, session_id, sequence, node, detail, level, provider, created_at,
            started_at, duration_ms, tokens_in, tokens_out, cost_usd
        """,
        (
            session_id,
            sequence,
            node,
            detail,
            level,
            provider,
            started_at,
            duration_ms,
            tokens_in,
            tokens_out,
            cost_usd,
        ),
    ).fetchone()


def list_trace_events(pool: DbPool, session_id: UUID) -> list[dict[str, Any]]:
    with pool.connection() as conn:
        return conn.execute(
            "SELECT id, session_id, sequence, node, detail, level, provider, created_at, "
            "started_at, duration_ms, tokens_in, tokens_out, cost_usd "
            "FROM trace_events WHERE session_id = %s ORDER BY sequence",
            (session_id,),
        ).fetchall()


def create_pending_action(
    pool: DbPool, session_id: UUID, *, tool_name: str, tool_args: dict[str, Any]
) -> dict[str, Any]:
    with pool.connection() as conn:
        return create_pending_action_on_connection(
            conn, session_id, tool_name=tool_name, tool_args=tool_args
        )


def create_pending_action_on_connection(
    conn: DbConnection, session_id: UUID, *, tool_name: str, tool_args: dict[str, Any]
) -> dict[str, Any]:
    return _required_row(
        conn.execute(
            """
        INSERT INTO pending_actions (session_id, tool_name, tool_args) VALUES (%s, %s, %s)
        RETURNING id, session_id, tool_name, tool_args, status, reason, created_at, decided_at
        """,
            (session_id, tool_name, Jsonb(tool_args)),
        ).fetchone(),
        operation="create pending action",
    )


def get_pending_action(pool: DbPool, pending_action_id: UUID) -> dict[str, Any] | None:
    with pool.connection() as conn:
        return conn.execute(
            "SELECT id, session_id, tool_name, tool_args, status, reason, created_at, decided_at "
            "FROM pending_actions WHERE id = %s",
            (pending_action_id,),
        ).fetchone()


def get_pending_action_for_session(pool: DbPool, session_id: UUID) -> dict[str, Any] | None:
    """The one 'pending' action currently blocking a session's run, if any —
    at most one at a time, since the graph itself blocks on interrupt()
    until it's decided (ADR-015). Lets a session response embed the exact
    thing the approval modal needs without a second round trip."""
    with pool.connection() as conn:
        return conn.execute(
            "SELECT id, session_id, tool_name, tool_args, status, reason, created_at, decided_at "
            "FROM pending_actions WHERE session_id = %s AND status = 'pending'",
            (session_id,),
        ).fetchone()


def decide_pending_action(
    pool: DbPool, pending_action_id: UUID, *, status: str, reason: str | None = None
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


def mark_pending_action_executed(pool: DbPool, pending_action_id: UUID) -> None:
    with pool.connection() as conn:
        conn.execute(
            "UPDATE pending_actions SET status = 'executed' WHERE id = %s AND status = 'approved'",
            (pending_action_id,),
        )


def write_note(pool: DbPool, session_id: UUID, *, key: str, content: str) -> None:
    with pool.connection() as conn:
        conn.execute(
            """
            INSERT INTO session_memory (session_id, key, content) VALUES (%s, %s, %s)
            ON CONFLICT (session_id, key) DO UPDATE SET content = EXCLUDED.content, updated_at = now()
            """,
            (session_id, key, content),
        )


def read_note(pool: DbPool, session_id: UUID, *, key: str) -> str | None:
    with pool.connection() as conn:
        row = conn.execute(
            "SELECT content FROM session_memory WHERE session_id = %s AND key = %s",
            (session_id, key),
        ).fetchone()
    return row["content"] if row else None


def list_note_keys(pool: DbPool, session_id: UUID) -> list[str]:
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT key FROM session_memory WHERE session_id = %s ORDER BY key",
            (session_id,),
        ).fetchall()
    return [row["key"] for row in rows]
