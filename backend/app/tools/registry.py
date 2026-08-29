"""Wires the three Tool adapters into (a) a name-keyed registry the graph's
`tool_call` node dispatches through, and (b) LangChain `StructuredTool`
schemas the planner binds to the LLM so it can select among them.
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

import httpx
from langchain_core.tools import StructuredTool

from app.db import DbPool
from app.tools.base import Tool
from app.tools.calculator import CalculatorTool
from app.tools.notes_store import NotesStoreTool
from app.tools.web_search import WebSearchTool


def build_tool_registry(
    *,
    tavily_api_key: str,
    db_pool: DbPool,
    session_id: UUID,
    http_client: httpx.Client | None = None,
) -> dict[str, Tool]:
    tools: list[Tool] = [
        CalculatorTool(),
        NotesStoreTool(db_pool, session_id),
        WebSearchTool(tavily_api_key, client=http_client),
    ]
    return {t.name: t for t in tools}


def to_langchain_tools(registry: dict[str, Tool]) -> list[StructuredTool]:
    """Schema-only wrappers for `bind_tools()` — the graph never calls these
    directly; `tool_call_node` invokes `registry[name].run(**args)` instead.
    """
    return [
        StructuredTool.from_function(
            func=_make_forwarder(tool),
            name=tool.name,
            description=tool.description,
            args_schema=tool.args_schema,
        )
        for tool in registry.values()
    ]


def _make_forwarder(tool: Tool) -> Callable[..., str]:
    def _forward(**kwargs: object) -> str:
        return tool.invoke(kwargs)

    return _forward
