"""Graph state — in-memory for Day 2 (see `app/graph/__init__.py`)."""

from __future__ import annotations

from typing import Literal, TypedDict

from langchain_core.messages import BaseMessage

from app.llm.base import ToolCallRequest


class TraceEvent(TypedDict):
    sequence: int
    node: str
    detail: str
    level: Literal["info", "success", "warning", "error"]
    provider: str | None


TraceLevel = Literal["info", "success", "warning", "error"]


def new_trace_event(
    state: GraphState,
    *,
    node: str,
    detail: str,
    level: TraceLevel = "info",
    provider: str | None = None,
) -> TraceEvent:
    """Create the next durable event in a session's monotonic trace."""
    return TraceEvent(
        sequence=len(state["trace"]) + 1,
        node=node,
        detail=detail,
        level=level,
        provider=provider,
    )


NextAction = Literal["advance", "retry", "replan", "finalize", "give_up"]


class GraphState(TypedDict):
    task: str
    messages: list[BaseMessage]
    plan: list[ToolCallRequest]
    step_index: int
    step_attempts: int
    replans: int
    tool_calls_made: int
    last_result: str | None
    last_failure: str | None
    last_failure_transient: bool | None
    next_action: NextAction | Literal[""]
    status: Literal["running", "done", "failed"]
    final_answer: str | None
    trace: list[TraceEvent]


def initial_state(task: str) -> GraphState:
    return GraphState(
        task=task,
        messages=[],
        plan=[],
        step_index=0,
        step_attempts=0,
        replans=0,
        tool_calls_made=0,
        last_result=None,
        last_failure=None,
        last_failure_transient=None,
        next_action="",
        status="running",
        final_answer=None,
        trace=[],
    )
