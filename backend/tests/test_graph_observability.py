"""P3 observability: timing/token/cost fields on trace events.

Root cause fixed here (see migrations/0006 and ADR-012's neighbor, the P3
plan): trace events used to be persisted as a whole batch after the graph
run completed, with no per-node clock reading ever captured — every row in
a run landed on the exact same instant. These tests assert timing is
captured INSIDE the node, at the moment the work happens, not backfilled at
persist time (which would reproduce the same bug).
"""

from __future__ import annotations

import time

from langchain_core.messages import HumanMessage

from app.graph.nodes import (
    approval_gate_node,
    make_finalize_node,
    make_planner_node,
    make_tool_call_node,
)
from app.graph.state import GraphState, initial_state
from app.llm.base import LLMResponse, TokenUsage, ToolCallRequest
from app.tools.errors import ToolError

_SLEEP_SECONDS = 0.02


class _ScriptedLLM:
    def __init__(self, *responses: LLMResponse) -> None:
        self._responses = list(responses)

    def generate(self, messages, tools=None) -> LLMResponse:
        return self._responses.pop(0)


class _SlowTool:
    """Sleeps a small, real amount of time so `duration_ms` is provably > 0."""

    name = "calculator"
    description = "spy"
    args_schema = None

    def __init__(self, *, error: ToolError | None = None) -> None:
        self._error = error

    def invoke(self, arguments: dict[str, object]) -> str:
        time.sleep(_SLEEP_SECONDS)
        if self._error is not None:
            raise self._error
        return "4183"


def _state_at_step(**overrides: object) -> GraphState:
    state = initial_state("a task")
    state["plan"] = [ToolCallRequest(id="c1", name="calculator", arguments={"expression": "1+1"})]
    state["step_index"] = 0
    for key, value in overrides.items():
        state[key] = value  # type: ignore[literal-required]
    return state


class TestPlannerTiming:
    def test_planner_records_started_at_duration_tokens_and_cost(self) -> None:
        response = LLMResponse(
            content="",
            tool_calls=[
                ToolCallRequest(id="c1", name="calculator", arguments={"expression": "1+1"})
            ],
            provider="gemini",
            usage=TokenUsage(input_tokens=100, output_tokens=20),
            model="gemini-3.1-flash-lite",
        )
        node = make_planner_node(_ScriptedLLM(response), langchain_tools=[])

        event = node(initial_state("compute 1+1"))["trace"][0]

        assert event["started_at"] is not None
        assert isinstance(event["duration_ms"], int)
        assert event["duration_ms"] >= 0
        assert event["tokens_in"] == 100
        assert event["tokens_out"] == 20
        assert event["cost_usd"] is not None

    def test_planner_leaves_tokens_and_cost_null_when_the_provider_reports_no_usage(self) -> None:
        response = LLMResponse(content="an answer", tool_calls=[], provider="gemini")
        node = make_planner_node(_ScriptedLLM(response), langchain_tools=[])

        event = node(initial_state("say hi"))["trace"][0]

        assert event["tokens_in"] is None
        assert event["tokens_out"] is None
        assert event["cost_usd"] is None
        # Still timed, even though there's nothing to price.
        assert event["started_at"] is not None
        assert event["duration_ms"] is not None

    def test_planner_does_not_guess_a_price_for_an_unrecognized_model(self) -> None:
        """A confidently wrong cost is worse than a blank one (the P3 plan's
        own framing) — an unpriced model must yield `cost_usd = None`, never
        a fabricated number."""
        response = LLMResponse(
            content="an answer",
            tool_calls=[],
            provider="openrouter",
            usage=TokenUsage(input_tokens=10, output_tokens=5),
            model="some/unpriced-model:free",
        )
        node = make_planner_node(_ScriptedLLM(response), langchain_tools=[])

        event = node(initial_state("say hi"))["trace"][0]

        assert event["tokens_in"] == 10  # usage is still captured...
        assert event["cost_usd"] is None  # ...but cost is never guessed


class TestToolCallTiming:
    def test_successful_tool_call_records_started_at_and_a_real_duration(self) -> None:
        node = make_tool_call_node({"calculator": _SlowTool()})

        event = node(_state_at_step())["trace"][0]

        assert event["started_at"] is not None
        # Windows' clock granularity can shave a few ms off a 20ms sleep;
        # the point under test is "measured a real, positive gap," not
        # microsecond precision.
        assert event["duration_ms"] > 0
        # Timing is universal; usage/cost are LLM-only concepts.
        assert event["tokens_in"] is None
        assert event["cost_usd"] is None

    def test_failed_tool_call_still_records_timing(self) -> None:
        node = make_tool_call_node(
            {"calculator": _SlowTool(error=ToolError("boom", transient=True))}
        )

        event = node(_state_at_step())["trace"][0]

        assert event["started_at"] is not None
        assert event["duration_ms"] > 0

    def test_unknown_tool_selection_is_not_a_timed_operation(self) -> None:
        """No tool ever ran, so there's nothing to time — this must not
        crash trying to measure work that never started."""
        node = make_tool_call_node({})

        event = node(_state_at_step())["trace"][0]

        assert event["duration_ms"] is None
        assert event["started_at"] is None


class TestApprovalGateIsDeliberatelyUntimed:
    """The pause between `interrupt()` and resume is operator think time,
    not system latency (see `approval_gate_node`'s docstring) — its trace
    events must never claim a `duration_ms`."""

    def _step_state(self) -> GraphState:
        state = initial_state("save a note")
        state["plan"] = [
            ToolCallRequest(
                id="c1",
                name="notes_store",
                arguments={"action": "write", "key": "k", "content": "v"},
            )
        ]
        state["step_index"] = 0
        return state

    def test_approved_decision_carries_no_duration(self, monkeypatch) -> None:
        monkeypatch.setattr("app.graph.nodes.interrupt", lambda payload: True)

        event = approval_gate_node(self._step_state())["trace"][0]

        assert event["duration_ms"] is None
        assert event["started_at"] is None

    def test_rejected_decision_carries_no_duration(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "app.graph.nodes.interrupt", lambda payload: {"approved": False, "reason": "no"}
        )

        event = approval_gate_node(self._step_state())["trace"][0]

        assert event["duration_ms"] is None
        assert event["started_at"] is None


class _ScriptedFinalizeProvider:
    def __init__(
        self,
        content: str,
        *,
        name: str,
        usage: TokenUsage | None = None,
        model: str | None = None,
    ) -> None:
        self.name = name
        self._content = content
        self._usage = usage
        self._model = model

    def generate(self, messages, tools=None) -> LLMResponse:
        return LLMResponse(
            content=self._content,
            tool_calls=[],
            provider=self.name,
            usage=self._usage,
            model=self._model,
        )


class TestFinalizeTiming:
    def test_success_event_carries_timing_tokens_and_cost(self) -> None:
        provider = _ScriptedFinalizeProvider(
            "The result is 4183.",
            name="gemini",
            usage=TokenUsage(input_tokens=50, output_tokens=10),
            model="gemini-3.1-flash-lite",
        )
        node = make_finalize_node(provider)
        state = initial_state("compute something")
        state["messages"] = [HumanMessage(content="compute something")]

        event = node(state)["trace"][0]

        assert event["started_at"] is not None
        assert event["duration_ms"] is not None
        assert event["tokens_in"] == 50
        assert event["tokens_out"] == 10
        assert event["cost_usd"] is not None

    def test_each_retry_attempt_is_timed_independently(self) -> None:
        rejected = _ScriptedFinalizeProvider("", name="gemini")
        accepted = _ScriptedFinalizeProvider(
            "A real answer that passes validation easily.", name="openrouter"
        )
        node = make_finalize_node(rejected, accepted)
        state = initial_state("do work")
        state["messages"] = [HumanMessage(content="do work")]

        events = node(state)["trace"]

        assert len(events) == 2
        assert all(event["started_at"] is not None for event in events)
        assert all(event["duration_ms"] is not None for event in events)
