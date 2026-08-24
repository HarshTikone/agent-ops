"""approval_gate_node's pause/resume behavior (ADR-015, ADR-016) — driven
through the real compiled graph with a real (in-memory) checkpointer, since
`interrupt()`/`Command(resume=...)` IS what's under test here, not something
that can be faked with a scripted double the way the LLM/tools are.

`InMemorySaver`, not `PostgresSaver`: fast, no real database needed for this
level — the fact this exact pause/resume mechanism also works against real
Postgres is verified separately (a live smoke test during design, and
tests/test_integration_session.py's full API-level run).
"""

from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.graph.build import build_graph
from app.graph.serde import GRAPH_SERDE
from app.graph.state import initial_state
from app.llm.base import LLMResponse, ToolCallRequest


class _SpyTool:
    def __init__(self, name: str) -> None:
        self.name = name
        self.description = "spy"
        self.args_schema = None
        self.calls: list[dict] = []

    def run(self, **kwargs) -> str:
        self.calls.append(kwargs)
        return f"{self.name} result"


class _ScriptedLLM:
    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    def generate(self, messages, tools=None) -> LLMResponse:
        self.calls.append({"messages": messages, "tools": tools})
        if not self._responses:
            raise AssertionError("llm.generate() called more times than scripted")
        return self._responses.pop(0)


def _tools() -> dict[str, _SpyTool]:
    return {name: _SpyTool(name) for name in ("calculator", "web_search", "notes_store")}


def test_write_action_pauses_before_running_the_tool() -> None:
    tools = _tools()
    llm = _ScriptedLLM(
        [
            LLMResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        id="c1",
                        name="notes_store",
                        arguments={"action": "write", "key": "k", "content": "v"},
                    )
                ],
                provider="gemini",
            )
        ]
    )
    graph = build_graph(
        llm, tools, langchain_tools=[], checkpointer=InMemorySaver(serde=GRAPH_SERDE)
    )
    config = {"configurable": {"thread_id": "t1"}}

    result = graph.invoke(initial_state("save a note"), config=config)

    assert "__interrupt__" in result
    interrupt_payload = result["__interrupt__"][0].value
    assert interrupt_payload == {
        "tool_name": "notes_store",
        "tool_args": {"action": "write", "key": "k", "content": "v"},
        "step_id": "c1",
    }
    assert tools["notes_store"].calls == []  # not run yet


def test_approval_resumes_and_runs_the_tool() -> None:
    tools = _tools()
    checkpointer = InMemorySaver(serde=GRAPH_SERDE)
    llm = _ScriptedLLM(
        [
            LLMResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        id="c1",
                        name="notes_store",
                        arguments={"action": "write", "key": "k", "content": "v"},
                    )
                ],
                provider="gemini",
            ),
            LLMResponse(content="saved it", tool_calls=[], provider="gemini"),
        ]
    )
    graph = build_graph(llm, tools, langchain_tools=[], checkpointer=checkpointer)
    config = {"configurable": {"thread_id": "t2"}}

    graph.invoke(initial_state("save a note"), config=config)
    result = graph.invoke(Command(resume=True), config=config)

    assert "__interrupt__" not in result
    assert tools["notes_store"].calls == [{"action": "write", "key": "k", "content": "v"}]
    assert result["status"] == "done"
    assert result["final_answer"] == "saved it"


def test_rejection_never_runs_the_tool_and_replans() -> None:
    tools = _tools()
    checkpointer = InMemorySaver(serde=GRAPH_SERDE)
    llm = _ScriptedLLM(
        [
            LLMResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        id="c1",
                        name="notes_store",
                        arguments={"action": "write", "key": "k", "content": "v"},
                    )
                ],
                provider="gemini",
            ),
            # the re-plan after rejection
            LLMResponse(content="okay, I won't save it", tool_calls=[], provider="gemini"),
        ]
    )
    graph = build_graph(llm, tools, langchain_tools=[], checkpointer=checkpointer)
    config = {"configurable": {"thread_id": "t3"}}

    graph.invoke(initial_state("save a note"), config=config)
    result = graph.invoke(Command(resume=False), config=config)

    assert tools["notes_store"].calls == []  # rejected — never ran
    assert result["replans"] == 1
    assert result["status"] == "done"
    assert result["final_answer"] == "okay, I won't save it"


def test_read_and_list_actions_never_pause() -> None:
    tools = _tools()
    llm = _ScriptedLLM(
        [
            LLMResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(id="c1", name="notes_store", arguments={"action": "list"})
                ],
                provider="gemini",
            ),
            LLMResponse(content="here they are", tool_calls=[], provider="gemini"),
        ]
    )
    graph = build_graph(
        llm, tools, langchain_tools=[], checkpointer=InMemorySaver(serde=GRAPH_SERDE)
    )
    config = {"configurable": {"thread_id": "t4"}}

    result = graph.invoke(initial_state("list notes"), config=config)

    assert "__interrupt__" not in result
    assert tools["notes_store"].calls == [{"action": "list"}]
    assert result["status"] == "done"


def test_two_write_steps_each_pause_independently() -> None:
    """Confirms interrupt() inside a node that re-runs on every loop
    iteration pauses freshly for EACH step needing approval, not just once
    for the whole run."""
    tools = _tools()
    checkpointer = InMemorySaver(serde=GRAPH_SERDE)
    llm = _ScriptedLLM(
        [
            LLMResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        id="c1",
                        name="notes_store",
                        arguments={"action": "write", "key": "a", "content": "1"},
                    ),
                    ToolCallRequest(
                        id="c2",
                        name="notes_store",
                        arguments={"action": "write", "key": "b", "content": "2"},
                    ),
                ],
                provider="gemini",
            ),
            LLMResponse(content="both saved", tool_calls=[], provider="gemini"),
        ]
    )
    graph = build_graph(llm, tools, langchain_tools=[], checkpointer=checkpointer)
    config = {"configurable": {"thread_id": "t5"}}

    first = graph.invoke(initial_state("save two notes"), config=config)
    assert "__interrupt__" in first
    assert tools["notes_store"].calls == []

    second = graph.invoke(Command(resume=True), config=config)
    assert "__interrupt__" in second, "the second write step must pause too, not be skipped"
    assert tools["notes_store"].calls == [{"action": "write", "key": "a", "content": "1"}]

    third = graph.invoke(Command(resume=True), config=config)
    assert "__interrupt__" not in third
    assert tools["notes_store"].calls == [
        {"action": "write", "key": "a", "content": "1"},
        {"action": "write", "key": "b", "content": "2"},
    ]
    assert third["status"] == "done"
