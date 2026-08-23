"""`observe_node`: folding a tool result/failure back into `messages`.

Regression coverage for a bug caught by live verification against real
Gemini (ADR-013), not by any mocked/scripted test: on a retry, the SAME
`tool_call_id` gets observed twice (once for the failed attempt, once for
the retry). Appending both ToolMessages produced an invalid history — two
tool responses answering one tool call — which the real API accepted
(200 OK) but silently answered with empty content instead of erroring, so
no mocked test built around "does this raise" would ever have caught it.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.messages.tool import tool_call as make_tool_call

from app.graph.nodes import observe_node
from app.graph.state import initial_state
from app.llm.base import ToolCallRequest


def _state_with_pending_step(*, messages, last_failure, last_result):
    state = initial_state("task")
    state["plan"] = [
        ToolCallRequest(id="c1", name="calculator", arguments={"expression": "47 * 89"})
    ]
    state["step_index"] = 0
    state["messages"] = messages
    state["last_failure"] = last_failure
    state["last_failure_transient"] = True if last_failure else None
    state["last_result"] = last_result
    return state


def _base_messages() -> list:
    return [
        HumanMessage(content="what is 47 * 89?"),
        AIMessage(
            content="",
            tool_calls=[make_tool_call(name="calculator", args={"expression": "47 * 89"}, id="c1")],
        ),
    ]


def test_first_observation_appends_exactly_one_tool_message() -> None:
    state = _state_with_pending_step(
        messages=_base_messages(), last_failure=None, last_result="4183"
    )
    update = observe_node(state)

    tool_messages = [m for m in update["messages"] if isinstance(m, ToolMessage)]
    assert len(tool_messages) == 1
    assert tool_messages[0].content == "4183"


def test_retry_replaces_the_stale_tool_message_instead_of_duplicating_it() -> None:
    messages_after_failed_attempt = [
        *_base_messages(),
        ToolMessage(content="ERROR: simulated blip", tool_call_id="c1", name="calculator"),
    ]
    state = _state_with_pending_step(
        messages=messages_after_failed_attempt, last_failure=None, last_result="4183"
    )

    update = observe_node(state)

    tool_messages = [m for m in update["messages"] if isinstance(m, ToolMessage)]
    assert (
        len(tool_messages) == 1
    ), "a retry must replace the prior attempt's ToolMessage, not add a second one"
    assert tool_messages[0].content == "4183"


def test_a_different_steps_tool_message_is_left_alone() -> None:
    other_step_message = ToolMessage(
        content="unrelated result", tool_call_id="other-call", name="notes_store"
    )
    state = _state_with_pending_step(
        messages=[*_base_messages(), other_step_message], last_failure=None, last_result="4183"
    )

    update = observe_node(state)

    tool_messages = {
        m.tool_call_id: m.content for m in update["messages"] if isinstance(m, ToolMessage)
    }
    assert tool_messages == {"other-call": "unrelated result", "c1": "4183"}
