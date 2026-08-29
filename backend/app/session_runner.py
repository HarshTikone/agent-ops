"""Bridges the in-memory LangGraph world (app/graph/) and the persisted
world (app/repository.py) — the one place that runs a session's graph and
writes the result back to Postgres (ADR-014, ADR-015).

Every call here runs the graph to completion OR to its next interrupt
within a single synchronous `.invoke()`; nothing is held open across
requests except the checkpointed graph state itself.
"""

from __future__ import annotations

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
from app.graph.state import initial_state
from app.llm.base import LLMProvider
from app.tools.registry import build_tool_registry, to_langchain_tools


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
    """Insert by durable sequence; replaying the same graph result is safe."""
    for event in trace:
        repo.add_trace_event_on_connection(
            conn,
            session_id,
            sequence=event["sequence"],
            node=event["node"],
            detail=event["detail"],
            level=event["level"],
            provider=event["provider"],
        )


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
        if status == "done":
            repo.add_message_on_connection(
                conn, session_id, role="assistant", content=final_answer or ""
            )
            repo.update_session_status_on_connection(
                conn, session_id, status="done", final_answer=final_answer
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


def resume_session_run(
    pool: DbPool,
    checkpointer: BaseCheckpointSaver,
    llm: LLMProvider,
    *,
    session_id: UUID,
    approved: bool,
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
        graph.invoke(Command[Any](resume=approved), config=_thread_config(session_id)),
    )
    _apply_result(pool, session_id, result)
