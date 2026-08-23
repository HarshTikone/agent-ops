"""`decide_next`'s retry / re-plan / give-up logic (ADR-012) — Day 2's most
interview-relevant piece of logic, per the brief: "the run where the planner
picked the wrong tool and the retry logic caught it."

Each test drives the REAL compiled graph (`build_graph`) with a scripted LLM
and scripted tools, and asserts on the tools' own call logs plus the run's
final state/trace — not just on the final answer text — so the distinction
between "retried the same step" and "re-planned" is actually verified, not
assumed.
"""

from __future__ import annotations

from app.graph.build import build_graph
from app.graph.limits import MAX_REPLANS, MAX_STEP_RETRIES, MAX_TOOL_CALLS
from app.graph.state import initial_state
from app.llm.base import LLMResponse, ToolCallRequest
from app.tools.errors import ToolError


class _ScriptedTool:
    """Returns/raises one scripted outcome per call, in order. Calling it
    more times than scripted is a test bug, not a silent no-op — it raises
    loudly so an over-calling regression can't hide.
    """

    def __init__(self, name: str, outcomes: list) -> None:
        self.name = name
        self.description = "scripted"
        self.args_schema = None
        self.calls: list[dict] = []
        self._outcomes = list(outcomes)

    def run(self, **kwargs) -> str:
        self.calls.append(kwargs)
        if not self._outcomes:
            raise AssertionError(f"{self.name}.run() called more times than scripted")
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _ScriptedLLM:
    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    def generate(self, messages, tools=None) -> LLMResponse:
        self.calls.append({"messages": messages, "tools": tools})
        if not self._responses:
            raise AssertionError("llm.generate() called more times than scripted")
        return self._responses.pop(0)


def _empty_tool(name: str) -> _ScriptedTool:
    return _ScriptedTool(name, [])


def test_transient_tool_failure_retries_the_same_step_then_succeeds() -> None:
    calc = _ScriptedTool("calculator", [ToolError("network blip", transient=True), "4"])
    tools = {
        "calculator": calc,
        "web_search": _empty_tool("web_search"),
        "notes_store": _empty_tool("notes_store"),
    }
    llm = _ScriptedLLM(
        [
            LLMResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(id="c1", name="calculator", arguments={"expression": "2+2"})
                ],
                provider="gemini",
            ),
            LLMResponse(content="final", tool_calls=[], provider="gemini"),
        ]
    )
    graph = build_graph(llm, tools, langchain_tools=[])

    result = graph.invoke(initial_state("compute"))

    assert calc.calls == [{"expression": "2+2"}, {"expression": "2+2"}]
    assert result["status"] == "done"
    assert result["replans"] == 0  # pure retry — planner was never re-invoked
    assert len(llm.calls) == 2  # planner once, finalize once
    retry_events = [
        e for e in result["trace"] if e["node"] == "decide_next" and "retry" in e["detail"]
    ]
    assert len(retry_events) == 1


def test_permanent_tool_failure_skips_retry_and_replans_immediately() -> None:
    calc = _ScriptedTool("calculator", [ToolError("could not parse expression", transient=False)])
    notes = _ScriptedTool("notes_store", ["saved note 'x'"])
    tools = {"calculator": calc, "web_search": _empty_tool("web_search"), "notes_store": notes}
    llm = _ScriptedLLM(
        [
            LLMResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(id="c1", name="calculator", arguments={"expression": "bad"})
                ],
                provider="gemini",
            ),
            LLMResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        id="c2",
                        name="notes_store",
                        arguments={"action": "write", "key": "x", "content": "y"},
                    )
                ],
                provider="gemini",
            ),
            LLMResponse(content="final", tool_calls=[], provider="gemini"),
        ]
    )
    graph = build_graph(llm, tools, langchain_tools=[])

    result = graph.invoke(initial_state("do something"))

    assert calc.calls == [{"expression": "bad"}]  # exactly once — no retry on a permanent failure
    assert notes.calls == [{"action": "write", "key": "x", "content": "y"}]
    assert result["replans"] == 1
    assert result["status"] == "done"

    replan_call_messages = llm.calls[1]["messages"]
    assert any(
        "failed" in getattr(m, "content", "") for m in replan_call_messages
    ), "the re-plan LLM call must see why the previous step failed"


def test_transient_failures_exhaust_retries_then_replan_then_give_up() -> None:
    """The full escalation path: retry the step (MAX_STEP_RETRIES times) ->
    re-plan (once, MAX_REPLANS) -> the new step also keeps failing -> give up.
    """
    calc_outcomes = [ToolError(f"blip{i}", transient=True) for i in range(MAX_STEP_RETRIES + 1)]
    web_outcomes = [ToolError(f"blip{i}", transient=True) for i in range(MAX_STEP_RETRIES + 1)]
    calc = _ScriptedTool("calculator", calc_outcomes)
    web = _ScriptedTool("web_search", web_outcomes)
    tools = {"calculator": calc, "web_search": web, "notes_store": _empty_tool("notes_store")}
    llm = _ScriptedLLM(
        [
            LLMResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(id="c1", name="calculator", arguments={"expression": "1/1"})
                ],
                provider="gemini",
            ),
            LLMResponse(
                content="",
                tool_calls=[ToolCallRequest(id="c2", name="web_search", arguments={"query": "q"})],
                provider="gemini",
            ),
        ]
    )
    graph = build_graph(llm, tools, langchain_tools=[])

    result = graph.invoke(initial_state("flaky task"))

    assert len(calc.calls) == MAX_STEP_RETRIES + 1
    assert len(web.calls) == MAX_STEP_RETRIES + 1
    assert result["replans"] == MAX_REPLANS
    assert result["status"] == "failed"
    assert f"blip{MAX_STEP_RETRIES}" in result["final_answer"]
    assert (
        result["tool_calls_made"] < MAX_TOOL_CALLS
    ), "should give up on the replan budget, not the hard cap"


def test_hard_tool_call_cap_stops_a_long_plan_even_when_every_step_succeeds() -> None:
    step_count = MAX_TOOL_CALLS + 1
    calc = _ScriptedTool("calculator", [str(i) for i in range(step_count)])
    tools = {
        "calculator": calc,
        "web_search": _empty_tool("web_search"),
        "notes_store": _empty_tool("notes_store"),
    }
    plan = [
        ToolCallRequest(id=f"c{i}", name="calculator", arguments={"expression": str(i)})
        for i in range(step_count)
    ]
    llm = _ScriptedLLM([LLMResponse(content="", tool_calls=plan, provider="gemini")])
    graph = build_graph(llm, tools, langchain_tools=[])

    result = graph.invoke(initial_state("long plan"))

    assert len(calc.calls) == MAX_TOOL_CALLS  # stopped exactly at the cap
    assert result["status"] == "failed"
    assert f"Stopped after {MAX_TOOL_CALLS} tool calls" in result["final_answer"]
    cap_events = [e for e in result["trace"] if "safety cap" in e["detail"]]
    assert len(cap_events) == 1


def test_unknown_tool_selection_is_treated_as_a_permanent_failure_and_replans() -> None:
    """The scenario the brief calls out by name: the planner picks a tool
    that doesn't exist. Not a crash — decide_next routes it through the same
    replan path as any other permanent step failure."""
    notes = _ScriptedTool("notes_store", ["saved note 'x'"])
    tools = {
        "calculator": _empty_tool("calculator"),
        "web_search": _empty_tool("web_search"),
        "notes_store": notes,
    }
    llm = _ScriptedLLM(
        [
            LLMResponse(
                content="",
                tool_calls=[ToolCallRequest(id="c1", name="time_machine", arguments={})],
                provider="gemini",
            ),
            LLMResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        id="c2",
                        name="notes_store",
                        arguments={"action": "write", "key": "x", "content": "y"},
                    )
                ],
                provider="gemini",
            ),
            LLMResponse(content="final", tool_calls=[], provider="gemini"),
        ]
    )
    graph = build_graph(llm, tools, langchain_tools=[])

    result = graph.invoke(initial_state("use a nonexistent tool"))

    assert result["replans"] == 1
    assert result["status"] == "done"
    assert notes.calls == [{"action": "write", "key": "x", "content": "y"}]
