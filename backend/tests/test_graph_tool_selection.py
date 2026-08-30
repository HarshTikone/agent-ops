"""Planner tool-selection logic, end to end through delegate -> tool_call:
given a (mocked) LLM decision to use tool X, the graph must invoke X's real
implementation — and only X's, never one of the other two.

Each test asserts on the SPY TOOLS' OWN CALL LOGS, not just on the final
state, so a graph that routes every step to the same tool regardless of the
plan cannot pass by accident (this is exactly the mutation verified in
ADR-013: hardcoding tool_call_node to always resolve "calculator" turns two
of these three parametrized cases red).
"""

from __future__ import annotations

import pytest

from app.graph.build import build_graph
from app.graph.state import initial_state
from app.llm.base import LLMResponse, ToolCallRequest


class _SpyTool:
    def __init__(self, name: str) -> None:
        self.name = name
        self.description = f"spy tool {name}"
        self.args_schema = None  # unused: these tests never call to_langchain_tools()
        self.calls: list[dict] = []

    def invoke(self, arguments: dict[str, object]) -> str:
        self.calls.append(arguments)
        return f"{self.name} result"


class _ScriptedLLM:
    """Returns one canned `LLMResponse` per call, in order — the first
    "answers" the planner's tool-selection decision, the second answers
    `finalize`'s synthesis call.
    """

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    def generate(self, messages, tools=None) -> LLMResponse:
        self.calls.append({"messages": messages, "tools": tools})
        return self._responses.pop(0)


def _spy_registry() -> dict[str, _SpyTool]:
    return {name: _SpyTool(name) for name in ("calculator", "web_search", "notes_store")}


@pytest.mark.parametrize(
    ("selected_tool", "arguments"),
    [
        ("calculator", {"expression": "2 + 2"}),
        ("web_search", {"query": "current weather"}),
        ("notes_store", {"action": "list"}),
    ],
)
def test_planner_selected_tool_is_the_one_actually_invoked(
    selected_tool: str, arguments: dict
) -> None:
    tools = _spy_registry()
    llm = _ScriptedLLM(
        [
            LLMResponse(
                content="",
                tool_calls=[ToolCallRequest(id="call_1", name=selected_tool, arguments=arguments)],
                provider="gemini",
            ),
            LLMResponse(content="done", tool_calls=[], provider="gemini"),
        ]
    )
    graph = build_graph(llm, tools, langchain_tools=[])

    result = graph.invoke(initial_state("a task"))

    assert tools[selected_tool].calls == [arguments]
    for other_name, other_tool in tools.items():
        if other_name != selected_tool:
            assert other_tool.calls == [], f"{other_name} should not have been invoked"
    assert result["status"] == "done"
    final_prompt = llm.calls[-1]["messages"][-1].content
    assert "Cite every web-derived claim with the exact result URL" in final_prompt


def test_planner_needing_no_tool_finishes_without_calling_any_tool() -> None:
    tools = _spy_registry()
    llm = _ScriptedLLM(
        [LLMResponse(content="just an answer, no tool needed", tool_calls=[], provider="gemini")]
    )
    graph = build_graph(llm, tools, langchain_tools=[])

    result = graph.invoke(initial_state("say hello"))

    assert all(tool.calls == [] for tool in tools.values())
    assert result["status"] == "done"
    assert result["final_answer"] == "just an answer, no tool needed"
    assert len(llm.calls) == 1  # no finalize call needed — planner's own answer is final
    assert "include_domains" in llm.calls[0]["messages"][0].content


def test_multi_step_plan_invokes_each_tool_in_order() -> None:
    tools = _spy_registry()
    llm = _ScriptedLLM(
        [
            LLMResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        id="call_1", name="calculator", arguments={"expression": "3 * 3"}
                    ),
                    ToolCallRequest(id="call_2", name="notes_store", arguments={"action": "list"}),
                ],
                provider="gemini",
            ),
            LLMResponse(content="both steps done", tool_calls=[], provider="gemini"),
        ]
    )
    graph = build_graph(llm, tools, langchain_tools=[])

    result = graph.invoke(initial_state("compute then list notes"))

    assert tools["calculator"].calls == [{"expression": "3 * 3"}]
    assert tools["notes_store"].calls == [{"action": "list"}]
    assert tools["web_search"].calls == []
    assert result["status"] == "done"
