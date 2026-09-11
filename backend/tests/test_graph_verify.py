"""P2: `verify_node` makes going back to `planner` the NORMAL way a
multi-step task progresses, not just a failure-recovery path — the
"replan" edge `decide_next` already used for a failed step is now also how
an incomplete-but-successful plan continues.

Root cause this fixes (confirmed against source, not inferred): the planner
used to be trusted to emit its whole multi-step plan in one turn, which
depended on reliable parallel tool-calling that these models don't actually
do — every multi-step task collapsed to `steps=[one tool]`. Now the planner
calls one tool per turn and `verify` decides, after each one, whether the
task is actually done.
"""

from __future__ import annotations

from app.graph.build import build_graph
from app.graph.limits import MAX_PLANNING_ROUNDS, MAX_TOOL_CALLS
from app.graph.state import initial_state
from app.llm.base import LLMResponse, ToolCallRequest


class _SpyTool:
    def __init__(self, name: str) -> None:
        self.name = name
        self.description = f"spy tool {name}"
        self.args_schema = None
        self.calls: list[dict] = []

    def invoke(self, arguments: dict[str, object]) -> str:
        self.calls.append(arguments)
        return f"{self.name} result"


def _spy_registry() -> dict[str, _SpyTool]:
    return {name: _SpyTool(name) for name in ("calculator", "web_search", "notes_store")}


class _ScriptedLLM:
    """Returns one canned `LLMResponse` per call, in order — raises loudly
    if called more times than scripted, so an unexpected extra round can't
    hide as a silent no-op."""

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    def generate(self, messages, tools=None) -> LLMResponse:
        self.calls.append({"messages": messages, "tools": tools})
        if not self._responses:
            raise AssertionError("llm.generate() called more times than scripted")
        return self._responses.pop(0)


def _tool_call(call_id: str, name: str) -> LLMResponse:
    return LLMResponse(
        content="",
        tool_calls=[ToolCallRequest(id=call_id, name=name, arguments={})],
        provider="gemini",
    )


_DONE = LLMResponse(content="DONE", tool_calls=[], provider="gemini")


def _continue(guidance: str) -> LLMResponse:
    return LLMResponse(content=f"CONTINUE: {guidance}", tool_calls=[], provider="gemini")


class TestMultiRoundPlanning:
    def test_a_three_step_task_makes_three_separate_tool_calls(self) -> None:
        """The exact production bug: 'compute -> save -> read back' used to
        collapse to a single-tool plan. Each of the three planner rounds
        below emits exactly one tool call, exercising the real iterate-via-
        verify loop rather than an upfront multi-call plan."""
        tools = _spy_registry()
        llm = _ScriptedLLM(
            [
                _tool_call("c1", "calculator"),
                _continue("still need to save and read back"),
                _tool_call("c2", "notes_store"),
                _continue("still need to read the value back"),
                _tool_call("c3", "web_search"),
                _DONE,
                LLMResponse(content="All three steps are done.", tool_calls=[], provider="gemini"),
            ]
        )
        graph = build_graph(llm, tools, langchain_tools=[])

        result = graph.invoke(initial_state("compute, save, then read back"))

        assert len(tools["calculator"].calls) == 1
        assert len(tools["notes_store"].calls) == 1
        assert len(tools["web_search"].calls) == 1
        assert result["status"] == "done"
        assert result["final_answer"] == "All three steps are done."
        assert result["replans"] == 2  # two "not complete yet" round-trips
        # 3 planner + 3 verify + 1 finalize, matching the plan's own estimate
        # of a three-step task's LLM-call cost.
        assert len(llm.calls) == 7

    def test_verify_events_are_visible_in_the_trace(self) -> None:
        """ARCHITECTURE.md's "the trace is the product" thesis: a viewer
        must see the agent decide it isn't done yet, not just the final
        answer."""
        tools = _spy_registry()
        llm = _ScriptedLLM(
            [
                _tool_call("c1", "calculator"),
                _continue("keep going"),
                _tool_call("c2", "notes_store"),
                _DONE,
                LLMResponse(content="Done.", tool_calls=[], provider="gemini"),
            ]
        )
        graph = build_graph(llm, tools, langchain_tools=[])

        result = graph.invoke(initial_state("two-step task"))

        verify_events = [e for e in result["trace"] if e["node"] == "verify"]
        assert len(verify_events) == 2
        assert verify_events[0]["level"] == "warning"
        assert "not complete" in verify_events[0]["detail"]
        assert verify_events[1]["level"] == "success"
        assert "complete" in verify_events[1]["detail"]


class TestSingleToolTaskHasNoExtraPlanningRound:
    def test_single_tool_task_calls_planner_exactly_once(self) -> None:
        tools = _spy_registry()
        llm = _ScriptedLLM(
            [
                _tool_call("c1", "calculator"),
                _DONE,
                LLMResponse(content="The result is 4183.", tool_calls=[], provider="gemini"),
            ]
        )
        graph = build_graph(llm, tools, langchain_tools=[])

        result = graph.invoke(initial_state("compute 47 * 89"))

        assert len(tools["calculator"].calls) == 1
        assert result["status"] == "done"
        assert result["final_answer"] == "The result is 4183."
        assert result["replans"] == 0  # no re-planning round was needed
        assert len(llm.calls) == 3  # planner, verify, finalize — no more


class TestImpossibleTaskGivesUpOnTheBudget:
    def test_a_task_verify_never_accepts_gives_up_before_the_tool_call_cap(self) -> None:
        """The scenario the plan calls out by name: a `verify` node that
        always says "not done" must still terminate — on its own
        MAX_PLANNING_ROUNDS budget, not by spinning all the way to
        MAX_TOOL_CALLS. Same tool, same (empty) arguments, every round: nothing
        about this task is ever satisfiable."""
        tools = _spy_registry()
        rounds = MAX_PLANNING_ROUNDS + 1  # one initial attempt + MAX_PLANNING_ROUNDS replans
        responses: list[LLMResponse] = []
        for i in range(rounds):
            responses.append(_tool_call(f"c{i}", "calculator"))
            responses.append(_continue("try something else"))
        llm = _ScriptedLLM(responses)
        graph = build_graph(llm, tools, langchain_tools=[])

        result = graph.invoke(initial_state("an impossible task"))

        assert result["status"] == "failed"
        assert result["replans"] == MAX_PLANNING_ROUNDS
        assert result["tool_calls_made"] == rounds
        assert (
            result["tool_calls_made"] < MAX_TOOL_CALLS
        ), "must give up on the planning-round budget, not spin to the tool-call cap"
        give_up_events = [e for e in result["trace"] if "give_up" in e["detail"]]
        assert len(give_up_events) == 1
        assert give_up_events[0]["node"] == "verify"
