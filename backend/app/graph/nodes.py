"""The five node types plus `finalize` (ARCHITECTURE.md §2, amended — see
ARCHITECTURE.md's Day 2 note): `planner`, `delegate`, `tool_call`, `observe`,
and `decide_next` as a real node whose output a tiny router (`route_after_decide`)
dispatches on, plus `finalize` for the "plan succeeded, synthesize an answer"
path.

`decide_next` is Day 2's most interview-relevant piece of logic (ADR-012):
kept as one explicit, testable node rather than an implicit if-chain spread
across the other nodes.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END
from langgraph.types import interrupt

from app.graph.limits import MAX_REPLANS, MAX_STEP_RETRIES, MAX_TOOL_CALLS
from app.graph.state import GraphState
from app.llm.base import LLMProvider, ai_message_from_llm_response
from app.tools.base import Tool
from app.tools.errors import ToolError

logger = logging.getLogger("agent_ops.graph")

PLANNER_SYSTEM_PROMPT = (
    "You are the planning stage of a tool-using agent. Break the user's task "
    "into the minimum sequence of tool calls needed to complete it. Call the "
    "available tools directly — each tool call you make becomes one step of "
    "the plan, executed in the order you call them. If the task needs no "
    "tool, answer directly instead of calling a tool."
)


def make_planner_node(llm: LLMProvider, langchain_tools: list) -> Callable[[GraphState], dict]:
    def planner_node(state: GraphState) -> dict:
        messages = state["messages"] or [
            SystemMessage(content=PLANNER_SYSTEM_PROMPT),
            HumanMessage(content=state["task"]),
        ]
        response = llm.generate(messages, tools=langchain_tools)
        new_messages = [*messages, ai_message_from_llm_response(response)]
        trace_entry = {
            "node": "planner",
            "detail": f"provider={response.provider} steps={[tc.name for tc in response.tool_calls]}",
        }

        if not response.tool_calls:
            return {
                "messages": new_messages,
                "plan": [],
                "status": "done",
                "final_answer": response.content,
                "trace": [*state["trace"], trace_entry],
            }

        return {
            "messages": new_messages,
            "plan": response.tool_calls,
            "step_index": 0,
            "step_attempts": 0,
            "last_failure": None,
            "last_failure_transient": None,
            "trace": [*state["trace"], trace_entry],
        }

    return planner_node


def route_after_planner(state: GraphState) -> str:
    return "delegate" if state["plan"] else END


def delegate_node(state: GraphState) -> dict:
    step = state["plan"][state["step_index"]]
    trace_entry = {
        "node": "delegate",
        "detail": f"step={state['step_index']} tool={step.name} args={step.arguments}",
    }
    return {"trace": [*state["trace"], trace_entry]}


# The one irreversible action in Day 3's tool set (ADR-016): writing a note
# can't be undone by a later step the way a read or a computation can be
# retried harmlessly. A (tool_name, action) pair, not a per-Tool flag on the
# uniform Tool interface -- kept as an explicit, small, graph-level table
# rather than growing the Tool protocol for one case; revisit if a second
# tool ever needs write-approval semantics too.
IRREVERSIBLE_STEPS = {("notes_store", "write")}


def _needs_approval(step) -> bool:
    return (step.name, step.arguments.get("action")) in IRREVERSIBLE_STEPS


def approval_gate_node(state: GraphState) -> dict:
    """Pauses the graph for human approval before an irreversible step runs
    (ADR-015, ADR-016) -- the ONLY node that calls `interrupt()`. Kept as its
    own node, separate from tool_call, because LangGraph re-runs a node's
    entire function body from the top on resume (interrupt() itself is what
    short-circuits replay, not the surrounding node) -- isolating it here
    means only this small, idempotent check re-executes, not tool_call's
    counter increments or tool.run() side effects.
    """
    step = state["plan"][state["step_index"]]
    if not _needs_approval(step):
        return {}

    approved = interrupt({"tool_name": step.name, "tool_args": step.arguments, "step_id": step.id})

    if approved:
        return {
            "trace": [
                *state["trace"],
                {
                    "node": "approval_gate",
                    "detail": f"step={state['step_index']} tool={step.name} APPROVED",
                },
            ]
        }
    return {
        "last_result": None,
        "last_failure": "the pending action was rejected",
        "last_failure_transient": False,
        "trace": [
            *state["trace"],
            {
                "node": "approval_gate",
                "detail": f"step={state['step_index']} tool={step.name} REJECTED",
            },
        ],
    }


def make_tool_call_node(tools: dict[str, Tool]) -> Callable[[GraphState], dict]:
    def tool_call_node(state: GraphState) -> dict:
        if state["last_failure"] is not None:
            # approval_gate already recorded a rejection for this step —
            # nothing to run, pass the failure through untouched so
            # decide_next handles it exactly like any other permanent
            # step failure.
            return {}

        step = state["plan"][state["step_index"]]
        tool_calls_made = state["tool_calls_made"] + 1
        tool = tools.get(step.name)

        if tool is None:
            # The planner selected a tool that doesn't exist in the registry
            # — a real, testable failure mode (a wrong tool-selection
            # decision, not a crash), handled exactly like any other
            # permanent step failure so decide_next's re-plan path covers it
            # uniformly.
            error_text = f"unknown tool {step.name!r} selected by planner"
            logger.error(
                "tool_call_failed step=%s tool=%s error=%s",
                state["step_index"],
                step.name,
                error_text,
            )
            return {
                "last_result": None,
                "last_failure": error_text,
                "last_failure_transient": False,
                "tool_calls_made": tool_calls_made,
                "trace": [
                    *state["trace"],
                    {"node": "tool_call", "detail": f"FAILED (permanent): {error_text}"},
                ],
            }

        try:
            result = tool.run(**step.arguments)
        except ToolError as exc:
            # Hard requirement (ARCHITECTURE.md §6): every tool failure is
            # caught and logged right here, never left to cross this node's
            # boundary as a raw, unclassified exception.
            logger.error(
                "tool_call_failed step=%s tool=%s transient=%s error=%s",
                state["step_index"],
                step.name,
                exc.transient,
                exc,
            )
            return {
                "last_result": None,
                "last_failure": str(exc),
                "last_failure_transient": exc.transient,
                "tool_calls_made": tool_calls_made,
                "trace": [
                    *state["trace"],
                    {
                        "node": "tool_call",
                        "detail": f"FAILED ({'transient' if exc.transient else 'permanent'}): {exc}",
                    },
                ],
            }

        return {
            "last_result": result,
            "last_failure": None,
            "last_failure_transient": None,
            "tool_calls_made": tool_calls_made,
            "trace": [*state["trace"], {"node": "tool_call", "detail": f"OK: {result[:200]}"}],
        }

    return tool_call_node


def observe_node(state: GraphState) -> dict:
    step = state["plan"][state["step_index"]]
    ok = state["last_failure"] is None
    content = state["last_result"] if ok else f"ERROR: {state['last_failure']}"
    tool_message = ToolMessage(content=content or "", tool_call_id=step.id, name=step.name)

    # On a retry, this step's tool_call_id already has a ToolMessage in
    # history from the failed attempt. Replace it rather than appending a
    # second one — verified live against real Gemini (ADR-013): two
    # ToolMessages answering the same tool_call_id is an invalid message
    # sequence that the API accepted (200 OK) but answered with silently
    # empty content, not an error.
    prior_messages = [
        m
        for m in state["messages"]
        if not (isinstance(m, ToolMessage) and m.tool_call_id == step.id)
    ]

    return {
        "messages": [*prior_messages, tool_message],
        "trace": [
            *state["trace"],
            {"node": "observe", "detail": f"step={state['step_index']} ok={ok}"},
        ],
    }


def decide_next_node(state: GraphState) -> dict:
    if state["tool_calls_made"] >= MAX_TOOL_CALLS:
        detail = f"give_up: hit the {MAX_TOOL_CALLS}-tool-call safety cap"
        logger.warning("decide_next %s", detail)
        return {
            "next_action": "give_up",
            "status": "failed",
            "final_answer": f"Stopped after {MAX_TOOL_CALLS} tool calls without finishing the task.",
            "trace": [*state["trace"], {"node": "decide_next", "detail": detail}],
        }

    if state["last_failure"] is None:
        next_index = state["step_index"] + 1
        if next_index >= len(state["plan"]):
            return {
                "next_action": "finalize",
                "step_index": next_index,
                "trace": [
                    *state["trace"],
                    {"node": "decide_next", "detail": "plan complete -> finalize"},
                ],
            }
        return {
            "next_action": "advance",
            "step_index": next_index,
            "step_attempts": 0,
            "trace": [
                *state["trace"],
                {
                    "node": "decide_next",
                    "detail": f"step {state['step_index']} ok -> advance to step {next_index}",
                },
            ],
        }

    # The current step failed. Transient-shaped and still within budget:
    # retry the SAME step. Otherwise, either re-plan (if that budget isn't
    # spent) or give up.
    if state["last_failure_transient"] and state["step_attempts"] < MAX_STEP_RETRIES:
        attempt = state["step_attempts"] + 1
        return {
            "next_action": "retry",
            "step_attempts": attempt,
            # Cleared, not carried into the retry attempt: tool_call_node
            # (ADR-016) reads last_failure to tell "approval_gate just
            # rejected this step" apart from "run the tool normally" — a
            # stale failure from the attempt that's being retried would be
            # misread as a fresh rejection and skip the retry entirely.
            "last_failure": None,
            "last_failure_transient": None,
            "trace": [
                *state["trace"],
                {
                    "node": "decide_next",
                    "detail": f"step {state['step_index']} transient failure -> retry (attempt {attempt}/{MAX_STEP_RETRIES})",
                },
            ],
        }

    if state["replans"] < MAX_REPLANS:
        step = state["plan"][state["step_index"]]
        replan_count = state["replans"] + 1
        failure_context = HumanMessage(
            content=(
                f"Step {state['step_index']} ({step.name}) failed and can't be "
                f"retried as-is: {state['last_failure']}. Re-plan the remaining "
                "work — pick a different tool or different arguments; don't "
                "repeat the exact same call."
            )
        )
        return {
            "next_action": "replan",
            "replans": replan_count,
            "messages": [*state["messages"], failure_context],
            "trace": [
                *state["trace"],
                {
                    "node": "decide_next",
                    "detail": f"step {state['step_index']} not retryable -> replan ({replan_count}/{MAX_REPLANS})",
                },
            ],
        }

    return {
        "next_action": "give_up",
        "status": "failed",
        "final_answer": f"Could not complete the task: {state['last_failure']}",
        "trace": [
            *state["trace"],
            {"node": "decide_next", "detail": "give_up: re-plan budget exhausted"},
        ],
    }


def route_after_decide(state: GraphState) -> str:
    return {
        "advance": "delegate",
        "retry": "delegate",
        "replan": "planner",
        "finalize": "finalize",
        "give_up": END,
    }[state["next_action"]]


def make_finalize_node(llm: LLMProvider) -> Callable[[GraphState], dict]:
    def finalize_node(state: GraphState) -> dict:
        prompt = HumanMessage(
            content="Summarize the results above into a final answer for the user."
        )
        response = llm.generate([*state["messages"], prompt], tools=None)
        return {
            "status": "done",
            "final_answer": response.content,
            "trace": [
                *state["trace"],
                {"node": "finalize", "detail": f"provider={response.provider}"},
            ],
        }

    return finalize_node
