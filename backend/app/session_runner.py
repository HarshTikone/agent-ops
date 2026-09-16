"""Bridges the in-memory LangGraph world (app/graph/) and the persisted
world (app/repository.py) — the one place that runs a session's graph and
writes the result back to Postgres (ADR-014, ADR-015).

Every call here runs the graph to completion OR to its next interrupt
within a single synchronous `.invoke()`; nothing is held open across
requests except the checkpointed graph state itself.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, cast
from uuid import UUID

import httpx
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from app import repository as repo
from app.db import DbConnection, DbPool
from app.graph.build import build_graph
from app.graph.state import GraphState, TraceEvent, initial_state, resumed_state
from app.llm.base import LLMProvider
from app.tools.registry import build_tool_registry, to_langchain_tools

logger = logging.getLogger("agent_ops.session_runner")


def _thread_config(session_id: UUID) -> RunnableConfig:
    return {"configurable": {"thread_id": str(session_id)}}


def _build_graph_for_session(
    llm: LLMProvider,
    checkpointer: BaseCheckpointSaver,
    *,
    pool: DbPool,
    session_id: UUID,
    tavily_api_key: str,
    http_client: httpx.Client | None = None,
    on_irreversible_tool_attempt: Callable[[], None] | None = None,
) -> CompiledStateGraph:
    tools = build_tool_registry(
        tavily_api_key=tavily_api_key,
        db_pool=pool,
        session_id=session_id,
        http_client=http_client,
    )
    langchain_tools = to_langchain_tools(tools)
    return build_graph(
        llm,
        tools,
        langchain_tools,
        checkpointer=checkpointer,
        on_irreversible_tool_attempt=on_irreversible_tool_attempt,
    )


def _persist_new_trace_events(conn: DbConnection, session_id: UUID, trace: list[dict]) -> None:
    """Insert by durable sequence; replaying the same graph result is safe
    thanks to `ON CONFLICT (session_id, sequence) DO NOTHING` (ADR-024).

    That silence is right for a genuine replay (the same event landing a
    second time), but a conflict can also mean a real event was just lost —
    see ADR-034: a sequence number the checkpoint computed can collide with
    a row written outside the graph entirely (a CRASH or REAPED event).
    `continue_session_run` closes that gap at the source by seeding the next
    turn's trace from the database, not the checkpoint, but this makes any
    conflict that still slips through loud instead of silent.
    """
    for event in trace:
        inserted = repo.add_trace_event_on_connection(
            conn,
            session_id,
            sequence=event["sequence"],
            node=event["node"],
            detail=event["detail"],
            level=event["level"],
            provider=event["provider"],
            started_at=event.get("started_at"),
            duration_ms=event.get("duration_ms"),
            tokens_in=event.get("tokens_in"),
            tokens_out=event.get("tokens_out"),
            cost_usd=event.get("cost_usd"),
        )
        if inserted is not None:
            continue
        existing = repo.get_trace_event_by_sequence(conn, session_id, event["sequence"])
        if existing is not None and (existing["node"], existing["detail"]) == (
            event["node"],
            event["detail"],
        ):
            continue  # idempotent replay of the same event -- expected, not a problem
        logger.warning(
            "trace_sequence_conflict session_id=%s sequence=%s existing_node=%s new_node=%s",
            session_id,
            event["sequence"],
            existing["node"] if existing else "<missing>",
            event["node"],
        )


def _persisted_trace(pool: DbPool, session_id: UUID) -> list[TraceEvent]:
    """The durable trace, as graph-state events. `trace_events` -- not the
    checkpoint -- is the source of truth for sequence numbers (ADR-034):
    rows written outside the graph (REAPED, CRASH) exist only there, so a
    follow-up turn seeded from the checkpoint's own (shorter) trace list
    would compute new sequence numbers that collide with them."""
    return [
        TraceEvent(
            sequence=row["sequence"],
            node=row["node"],
            detail=row["detail"],
            level=row["level"],
            provider=row["provider"],
            started_at=row["started_at"].isoformat() if row["started_at"] else None,
            duration_ms=row["duration_ms"],
            tokens_in=row["tokens_in"],
            tokens_out=row["tokens_out"],
            cost_usd=str(row["cost_usd"]) if row["cost_usd"] is not None else None,
        )
        for row in repo.list_trace_events(pool, session_id)
    ]


def _apply_result(pool: DbPool, session_id: UUID, result: dict[str, Any]) -> None:
    with pool.connection() as conn, conn.transaction():
        _persist_new_trace_events(conn, session_id, result.get("trace", []))

        interrupts = result.get("__interrupt__")
        if interrupts:
            payload = interrupts[0].value
            repo.create_pending_action_on_connection(
                conn,
                session_id,
                tool_name=payload["tool_name"],
                tool_args=payload["tool_args"],
            )
            repo.update_session_status_on_connection(conn, session_id, status="awaiting_approval")
            return

        status = result.get("status", "running")
        final_answer = result.get("final_answer")
        # `done` and `degraded` are both terminal and both answer-bearing, so
        # they persist identically apart from the status itself: a degraded run
        # still produced work worth showing, it just isn't the model's own
        # summary (see `make_finalize_node`). Keeping the two statuses distinct
        # is what lets `scripts/audit_sessions.py` and the UI tell them apart
        # instead of counting a fallback as a clean success.
        if status in ("done", "degraded"):
            repo.add_message_on_connection(
                conn, session_id, role="assistant", content=final_answer or ""
            )
            repo.update_session_status_on_connection(
                conn, session_id, status=status, final_answer=final_answer
            )
        elif status == "failed":
            repo.update_session_status_on_connection(
                conn, session_id, status="failed", final_answer=final_answer
            )
        else:
            raise RuntimeError("graph invocation returned without an interrupt or terminal status")


def start_session_run(
    pool: DbPool,
    checkpointer: BaseCheckpointSaver,
    llm: LLMProvider,
    *,
    session_id: UUID,
    task: str,
    tavily_api_key: str,
    http_client: httpx.Client | None = None,
) -> None:
    graph = _build_graph_for_session(
        llm,
        checkpointer,
        pool=pool,
        session_id=session_id,
        tavily_api_key=tavily_api_key,
        http_client=http_client,
    )
    result = cast(
        dict[str, Any], graph.invoke(initial_state(task), config=_thread_config(session_id))
    )
    _apply_result(pool, session_id, result)


def continue_session_run(
    pool: DbPool,
    checkpointer: BaseCheckpointSaver,
    llm: LLMProvider,
    *,
    session_id: UUID,
    task: str,
    tavily_api_key: str,
    http_client: httpx.Client | None = None,
) -> None:
    """The multi-turn sibling of `start_session_run` (ADR-033): loads the
    prior turn's checkpointed state via `graph.get_state` rather than
    starting from `initial_state`, so a follow-up message builds on the
    messages and trace the agent already produced instead of starting a
    blank conversation on a session the checkpointer already has history
    for. Only called after `repo.restart_session` has already verified the
    session was in a terminal, resumable status."""
    graph = _build_graph_for_session(
        llm,
        checkpointer,
        pool=pool,
        session_id=session_id,
        tavily_api_key=tavily_api_key,
        http_client=http_client,
    )
    prior = graph.get_state(_thread_config(session_id)).values
    # A session can reach a restartable terminal status (repo.restart_session)
    # without the graph ever having been invoked at all -- e.g. a crash in
    # send_message's own add_message call, before start_session_run got the
    # chance to run (C4, ADR-020). No checkpoint then exists for this thread,
    # so `prior` comes back `{}`; resumed_state assumes a real prior turn
    # (its messages already carry the system prompt planner_node seeds only
    # when starting fresh), so an empty prior falls back to initial_state
    # instead, exactly what start_session_run would have done here.
    next_state = resumed_state(cast(GraphState, prior), task) if prior else initial_state(task)
    # ADR-034: trace_events, not the checkpoint, is the source of truth for
    # sequence numbers -- a CRASH or REAPED row written straight to the
    # database (never through the graph) leaves the checkpoint's trace
    # shorter than the database's real row count, so seeding from either
    # `resumed_state` or `initial_state` above computes the next event's
    # sequence at a number a database row already occupies. Overwriting
    # with the database's own trace here closes that gap at the source.
    next_state["trace"] = _persisted_trace(pool, session_id)
    result = cast(
        dict[str, Any],
        graph.invoke(next_state, config=_thread_config(session_id)),
    )
    _apply_result(pool, session_id, result)


def resume_session_run(
    pool: DbPool,
    checkpointer: BaseCheckpointSaver,
    llm: LLMProvider,
    *,
    session_id: UUID,
    approved: bool,
    rejection_reason: str | None = None,
    tavily_api_key: str,
    pending_action_id: UUID | None = None,
    http_client: httpx.Client | None = None,
) -> None:
    on_attempt: Callable[[], None] | None = None
    if approved and pending_action_id is not None:

        def mark_attempted() -> None:
            repo.mark_pending_action_executed(pool, pending_action_id)

        on_attempt = mark_attempted
    graph = _build_graph_for_session(
        llm,
        checkpointer,
        pool=pool,
        session_id=session_id,
        tavily_api_key=tavily_api_key,
        http_client=http_client,
        on_irreversible_tool_attempt=on_attempt,
    )
    result = cast(
        dict[str, Any],
        graph.invoke(
            Command[Any](resume={"approved": approved, "reason": rejection_reason}),
            config=_thread_config(session_id),
        ),
    )
    _apply_result(pool, session_id, result)
