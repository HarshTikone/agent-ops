"""Graph state — in-memory for Day 2 (see `app/graph/__init__.py`)."""

from __future__ import annotations

from typing import Literal, TypedDict

from langchain_core.messages import BaseMessage

from app.llm.base import ToolCallRequest


class TraceEvent(TypedDict):
    node: str
    detail: str


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
