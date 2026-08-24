"""Wires the nodes from `nodes.py` into the compiled LangGraph state graph.

    START -> planner --[route_after_planner]--> delegate | END
    delegate -> approval_gate -> tool_call -> observe -> decide_next
    decide_next --[route_after_decide]--> delegate (advance/retry) | planner (replan) | finalize | END (give_up)
    finalize -> END

`approval_gate` (ADR-015, ADR-016) is a no-op pass-through for every step
except the one irreversible action in Day 3's tool set — it's the only node
that ever calls `interrupt()`.
"""

from __future__ import annotations

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
    observe_node,
    route_after_decide,
    route_after_planner,
)
from app.graph.state import GraphState
from app.llm.base import LLMProvider
from app.tools.base import Tool


def build_graph(
    llm: LLMProvider,
    tools: dict[str, Tool],
    langchain_tools: list,
    *,
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """`checkpointer` is what makes the approval pause survive across two
    separate HTTP requests (ADR-014) -- omit it (e.g. in Day 2-style unit
    tests that run a whole plan in one `.invoke()` call and never touch
    `interrupt()`) to get LangGraph's default in-memory-only behavior.
    """
    graph = StateGraph(GraphState)

    graph.add_node("planner", make_planner_node(llm, langchain_tools))
    graph.add_node("delegate", delegate_node)
    graph.add_node("approval_gate", approval_gate_node)
    graph.add_node("tool_call", make_tool_call_node(tools))
    graph.add_node("observe", observe_node)
    graph.add_node("decide_next", decide_next_node)
    graph.add_node("finalize", make_finalize_node(llm))

    graph.add_edge(START, "planner")
    graph.add_conditional_edges("planner", route_after_planner, {"delegate": "delegate", END: END})
    graph.add_edge("delegate", "approval_gate")
    graph.add_edge("approval_gate", "tool_call")
    graph.add_edge("tool_call", "observe")
    graph.add_edge("observe", "decide_next")
    # route_after_decide already translates next_action -> the actual next
    # node name (see nodes.py) — this path_map is therefore an identity map
    # over its possible return values, not over next_action's labels.
    graph.add_conditional_edges(
        "decide_next",
        route_after_decide,
        {"delegate": "delegate", "planner": "planner", "finalize": "finalize", END: END},
    )
    graph.add_edge("finalize", END)

    return graph.compile(checkpointer=checkpointer)
