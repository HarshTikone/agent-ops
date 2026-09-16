"""`resumed_state` (ADR-030): the multi-turn sibling of `initial_state`."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.graph.state import initial_state, resumed_state


def test_resumed_state_appends_the_new_task_as_a_human_message() -> None:
    prior = initial_state("first task")
    prior["messages"] = [
        SystemMessage(content="system prompt"),
        HumanMessage(content="first task"),
        AIMessage(content="first answer"),
    ]

    resumed = resumed_state(prior, "second task")

    assert resumed["messages"][:-1] == prior["messages"]
    assert resumed["messages"][-1] == HumanMessage(content="second task")
    assert resumed["task"] == "second task"


def test_resumed_state_carries_the_trace_forward_unchanged() -> None:
    prior = initial_state("first task")
    prior["trace"].append(
        {
            "sequence": 1,
            "node": "planner",
            "detail": "d",
            "level": "info",
            "provider": None,
            "started_at": None,
            "duration_ms": None,
            "tokens_in": None,
            "tokens_out": None,
            "cost_usd": None,
        }
    )

    resumed = resumed_state(prior, "second task")

    assert resumed["trace"] == prior["trace"]


def test_resumed_state_resets_every_per_run_field() -> None:
    prior = initial_state("first task")
    prior.update(
        plan=["not-really-a-tool-call"],  # only shape matters here, not type
        step_index=3,
        step_attempts=2,
        replans=1,
        tool_calls_made=5,
        last_result="some result",
        last_failure="some failure",
        last_failure_transient=True,
        next_action="advance",
        status="done",
        final_answer="first answer",
    )

    resumed = resumed_state(prior, "second task")

    assert resumed["plan"] == []
    assert resumed["step_index"] == 0
    assert resumed["step_attempts"] == 0
    assert resumed["replans"] == 0
    assert resumed["tool_calls_made"] == 0
    assert resumed["last_result"] is None
    assert resumed["last_failure"] is None
    assert resumed["last_failure_transient"] is None
    assert resumed["next_action"] == ""
    assert resumed["status"] == "running"
    assert resumed["final_answer"] is None


def test_resumed_state_works_from_a_blank_prior_state() -> None:
    """A prior state with no messages/trace yet (a session whose first turn
    never got past `planner` before failing) must not crash -- the new
    HumanMessage is just appended to an empty list."""
    prior = initial_state("first task")

    resumed = resumed_state(prior, "second task")

    assert resumed["messages"] == [HumanMessage(content="second task")]
    assert resumed["trace"] == []
