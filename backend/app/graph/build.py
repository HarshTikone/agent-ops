"""Wires the nodes from `nodes.py` into the compiled LangGraph state graph.

    START -> planner --[route_after_planner]--> delegate | END
    delegate -> approval_gate -> tool_call -> observe -> decide_next
    decide_next --[route_after_decide]--> delegate (advance/retry) | planner (replan) | verify | END (give_up)
    verify --[route_after_verify]--> finalize | planner (replan) | END (give_up)
    finalize -> END

`approval_gate` (ADR-015, ADR-016) is a no-op pass-through for every step
except the one irreversible action in Day 3's tool set — it's the only node
that ever calls `interrupt()`.

`verify` (P2) sits between `decide_next` and `finalize`: a plan running out
of steps no longer means the task is done, only that this round of steps
is — `verify` is what checks whether the task itself is complete, and
routes back to `planner` (the SAME "replan" edge `decide_next` already used
for a failed, un-retryable step) when it isn't.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.graph.nodes import (
    approval_gate_node,
    decide_next_node,
    delegate_node,
    make_finalize_node,
    make_planner_node,
    make_tool_call_node,
    make_verify_node,
    observe_node,
    route_after_approval,
    route_after_decide,
    route_after_planner,
    route_after_verify,
)
from app.graph.state import GraphState
from app.llm.base import LLMProvider
from app.llm.failover import FailoverProvider
from app.tools.base import Tool


def build_graph(
    llm: LLMProvider,
    tools: dict[str, Tool],
    langchain_tools: list,
    *,
    checkpointer: BaseCheckpointSaver | None = None,
    on_irreversible_tool_attempt: Callable[[], None] | None = None,
    finalize_retry_llm: LLMProvider | None = None,
) -> CompiledStateGraph:
    """`checkpointer` is what makes the approval pause survive across two
    separate HTTP requests (ADR-014) -- omit it (e.g. in Day 2-style unit
    tests that run a whole plan in one `.invoke()` call and never touch
    `interrupt()`) to get LangGraph's default in-memory-only behavior.

    `finalize_retry_llm` is the *second* provider `finalize` retries on when
    the first returns an unusable answer (empty, or leaking tool-call markup).
    Left unset, it is derived from `llm` when that is a `FailoverProvider`, by
    swapping its primary and fallback -- the common case, and the reason
    callers rarely pass it. Pass it explicitly in tests, or to opt out with a
    provider of your own. When there is no second provider to reach for,
    finalize still validates; it just degrades instead of retrying.
    """
    if finalize_retry_llm is None and isinstance(llm, FailoverProvider):
        finalize_retry_llm = llm.swapped()

    graph = StateGraph(GraphState)

    graph.add_node("planner", cast(Any, make_planner_node(llm, langchain_tools)))
    graph.add_node("delegate", delegate_node)
    graph.add_node("approval_gate", approval_gate_node)
    graph.add_node("tool_call", cast(Any, make_tool_call_node(tools, on_irreversible_tool_attempt)))
    graph.add_node("observe", observe_node)
    graph.add_node("decide_next", decide_next_node)
    graph.add_node("verify", cast(Any, make_verify_node(llm)))
    graph.add_node("finalize", cast(Any, make_finalize_node(llm, finalize_retry_llm)))

    graph.add_edge(START, "planner")
    graph.add_conditional_edges("planner", route_after_planner, {"delegate": "delegate", END: END})
    graph.add_edge("delegate", "approval_gate")
    graph.add_conditional_edges(
        "approval_gate", route_after_approval, {"tool_call": "tool_call", END: END}
    )
    graph.add_edge("tool_call", "observe")
    graph.add_edge("observe", "decide_next")
    # route_after_decide already translates next_action -> the actual next
    # node name (see nodes.py) — this path_map is therefore an identity map
    # over its possible return values, not over next_action's labels.
    graph.add_conditional_edges(
        "decide_next",
        route_after_decide,
        {"delegate": "delegate", "planner": "planner", "verify": "verify", END: END},
    )
    graph.add_conditional_edges(
        "verify",
        route_after_verify,
        {"finalize": "finalize", "planner": "planner", END: END},
    )
    graph.add_edge("finalize", END)

    return graph.compile(checkpointer=checkpointer)
