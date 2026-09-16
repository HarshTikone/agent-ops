"""Graph state — in-memory for Day 2 (see `app/graph/__init__.py`)."""

from __future__ import annotations

from typing import Literal, TypedDict

from langchain_core.messages import BaseMessage, HumanMessage

from app.llm.base import ToolCallRequest


class TraceEvent(TypedDict):
    sequence: int
    node: str
    detail: str
    level: Literal["info", "success", "warning", "error"]
    provider: str | None
    # P3 observability fields. Nullable in every sense: a node that doesn't
    # time itself (or ran before P3 shipped) still produces a valid event —
    # see migrations/0006_trace_timing_and_cost.sql, which adds these as
    # nullable columns for exactly that reason.
    started_at: str | None
    duration_ms: int | None
    tokens_in: int | None
    tokens_out: int | None
    cost_usd: str | None  # Decimal serialized as str to survive the checkpointer


TraceLevel = Literal["info", "success", "warning", "error"]


def new_trace_event(
    state: GraphState,
    *,
    node: str,
    detail: str,
    level: TraceLevel = "info",
    provider: str | None = None,
    started_at: str | None = None,
    duration_ms: int | None = None,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    cost_usd: str | None = None,
) -> TraceEvent:
    """Create the next durable event in a session's monotonic trace."""
    return trace_event_after(
        state["trace"],
        node=node,
        detail=detail,
        level=level,
        provider=provider,
        started_at=started_at,
        duration_ms=duration_ms,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=cost_usd,
    )


def trace_event_after(
    trace: list[TraceEvent],
    *,
    node: str,
    detail: str,
    level: TraceLevel = "info",
    provider: str | None = None,
    started_at: str | None = None,
    duration_ms: int | None = None,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    cost_usd: str | None = None,
) -> TraceEvent:
    """Same as `new_trace_event`, but keyed on a trace list rather than state.

    A node that emits more than one event in a single pass cannot use
    `new_trace_event` for the second one: `state["trace"]` is stale the moment
    the first event is appended, so every later event would be handed the same
    `sequence`. `_persist_new_trace_events` inserts by sequence, so duplicates
    collide instead of ordering. `finalize_node` needs this when a rejected
    answer is followed by a retry on the other provider.

    Timing/cost must be captured by the caller and passed in here, not
    computed from wall-clock time at this call site: this function (and
    `_persist_new_trace_events`, which writes the whole batch after the graph
    run completes) runs long after the work happened, so a clock reading
    taken here would collapse every event in a batch back onto the same
    instant — the exact bug this field set exists to fix.
    """
    return TraceEvent(
        sequence=len(trace) + 1,
        node=node,
        detail=detail,
        level=level,
        provider=provider,
        started_at=started_at,
        duration_ms=duration_ms,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=cost_usd,
    )


NextAction = Literal["advance", "retry", "replan", "verify", "finalize", "give_up"]


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
    # `degraded` is terminal and answer-bearing, like `done`: the plan ran, but
    # no provider produced an answer that passed `validate_answer`, so the
    # answer is the deterministic one built from tool results. Distinct from
    # `failed`, where the work itself did not complete.
    status: Literal["running", "done", "degraded", "failed"]
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


def resumed_state(prior: GraphState, task: str) -> GraphState:
    """Starts a new turn on a session that already reached a terminal status
    (ADR-033 supersedes ADR-015's one-task-per-session boundary): keeps
    `messages` (with the new task appended as a `HumanMessage`, so the
    planner sees it) and `trace` (so trace sequence numbers keep climbing
    instead of restarting at 1) from the prior turn, and resets every other
    field to what `initial_state` would give a brand-new session — a
    follow-up turn is a fresh planning run, just one with history.

    Returns a COMPLETE state dict, not a partial update, deliberately: an
    `.invoke()` on a thread whose checkpoint already exists could in
    principle merge a partial dict against the checkpointed values field by
    field (LangGraph's default per-channel behavior for a `TypedDict` state
    with no reducer is "last value wins", i.e. whatever value the checkpoint
    holds survives to the invoke if not passed here — but that must not be
    relied on to infer this design without being checked against the
    installed version). Supplying every field here removes the question
    entirely: whichever way the merge works, this IS the resulting state.
    """
    return GraphState(
        task=task,
        messages=[*prior["messages"], HumanMessage(content=task)],
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
        trace=prior["trace"],
    )
