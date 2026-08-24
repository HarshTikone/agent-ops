"""Bridges the in-memory LangGraph world (app/graph/) and the persisted
world (app/repository.py) — the one place that runs a session's graph and
writes the result back to Postgres (ADR-014, ADR-015).

Every call here runs the graph to completion OR to its next interrupt
within a single synchronous `.invoke()`; nothing is held open across
requests except the checkpointed graph state itself.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import Command
from psycopg_pool import ConnectionPool

from app import repository as repo
from app.graph.build import build_graph
from app.graph.state import initial_state
from app.llm.base import LLMProvider
from app.tools.registry import build_tool_registry, to_langchain_tools


def _thread_config(session_id: UUID) -> dict[str, Any]:
    return {"configurable": {"thread_id": str(session_id)}}


def _build_graph_for_session(
    llm: LLMProvider,
    checkpointer: BaseCheckpointSaver,
    *,
    pool: ConnectionPool,
    session_id: UUID,
    tavily_api_key: str,
):
    tools = build_tool_registry(tavily_api_key=tavily_api_key, db_pool=pool, session_id=session_id)
    langchain_tools = to_langchain_tools(tools)
    return build_graph(llm, tools, langchain_tools, checkpointer=checkpointer)


def _persist_new_trace_events(pool: ConnectionPool, session_id: UUID, trace: list[dict]) -> None:
    """`trace` accumulates every entry across the WHOLE run (it's part of
    the checkpointed state, carried forward across separate `.invoke()`
    calls) — only the entries past what's already in Postgres are new.
    """
    already_persisted = len(repo.list_trace_events(pool, session_id))
    for event in trace[already_persisted:]:
        repo.add_trace_event(pool, session_id, node=event["node"], detail=event["detail"])


def _apply_result(pool: ConnectionPool, session_id: UUID, result: dict[str, Any]) -> None:
    _persist_new_trace_events(pool, session_id, result.get("trace", []))

    interrupts = result.get("__interrupt__")
    if interrupts:
        payload = interrupts[0].value
        repo.create_pending_action(
            pool, session_id, tool_name=payload["tool_name"], tool_args=payload["tool_args"]
        )
        repo.update_session_status(pool, session_id, status="awaiting_approval")
        return

    status = result.get("status", "running")
    final_answer = result.get("final_answer")
    if status == "done":
        repo.add_message(pool, session_id, role="assistant", content=final_answer or "")
        repo.update_session_status(pool, session_id, status="done", final_answer=final_answer)
    elif status == "failed":
        repo.update_session_status(pool, session_id, status="failed", final_answer=final_answer)
    # A completed .invoke() call always ends in "done"/"failed" or an
    # interrupt — "running" here would mean the graph exited without
    # reaching END, which would itself be a bug worth a loud failure rather
    # than a silently-ignored branch, so no `else` is written on purpose.


def start_session_run(
    pool: ConnectionPool,
    checkpointer: BaseCheckpointSaver,
    llm: LLMProvider,
    *,
    session_id: UUID,
    task: str,
    tavily_api_key: str,
) -> None:
    graph = _build_graph_for_session(
        llm, checkpointer, pool=pool, session_id=session_id, tavily_api_key=tavily_api_key
    )
    result = graph.invoke(initial_state(task), config=_thread_config(session_id))
    _apply_result(pool, session_id, result)


def resume_session_run(
    pool: ConnectionPool,
    checkpointer: BaseCheckpointSaver,
    llm: LLMProvider,
    *,
    session_id: UUID,
    approved: bool,
    tavily_api_key: str,
) -> None:
    graph = _build_graph_for_session(
        llm, checkpointer, pool=pool, session_id=session_id, tavily_api_key=tavily_api_key
    )
    result = graph.invoke(Command(resume=approved), config=_thread_config(session_id))
    _apply_result(pool, session_id, result)
