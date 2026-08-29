"""Shared types for the LLM provider layer.

`LLMProvider` is a `Protocol`, not an ABC — `GeminiProvider`, `OpenRouterProvider`,
`FailoverProvider`, and any test double just need to structurally match
`generate(messages, tools) -> LLMResponse`; nothing needs to inherit from
anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.messages.tool import tool_call as make_tool_call
from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict


class ToolCallRequest(BaseModel):
    """One planner-selected tool call — one step of the plan.

    A Pydantic model, not a `@dataclass` (ADR-014): `state["plan"]` is part
    of the graph state LangGraph's checkpointer persists to Postgres for the
    approval pause/resume flow, and its serializer gives Pydantic v2 models
    a dedicated, natively-supported round-trip path. A plain dataclass here
    triggered "Deserializing unregistered type ... This will be blocked in
    a future version" — verified live against a real checkpointed run, not
    assumed from the warning text alone.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class LLMResponse:
    """A provider's answer, normalized regardless of which one produced it.

    `provider` records which concrete provider actually answered ("gemini" or
    "openrouter") — this is what makes a failover visible to a caller (and,
    from Day 3, to the trace log) without the caller needing to know which
    provider it asked.
    """

    content: str
    tool_calls: list[ToolCallRequest]
    provider: str


@runtime_checkable
class LLMProvider(Protocol):
    name: str

    def generate(
        self, messages: list[BaseMessage], tools: list[BaseTool] | None = None
    ) -> LLMResponse: ...


def llm_response_from_ai_message(ai_message: AIMessage, *, provider: str) -> LLMResponse:
    """Convert a LangChain `AIMessage` into our provider-agnostic `LLMResponse`.

    `.text` (not `.content`) is the correct extraction here — verified live
    against Gemini (ADR-013): `ChatGoogleGenerativeAI` returns `.content` as a
    list of content blocks (`[{"type": "text", "text": ..., "extras": {...}}]`),
    not a plain string, so `str(ai_message.content)` produced a stringified
    Python list instead of the answer text. `.text` normalizes both that
    shape and OpenAI's plain-string shape to a real `str`.
    """
    content = str(ai_message.text)
    tool_calls = [
        ToolCallRequest(id=tc["id"], name=tc["name"], arguments=tc["args"])
        for tc in ai_message.tool_calls
    ]
    return LLMResponse(content=content, tool_calls=tool_calls, provider=provider)


def ai_message_from_llm_response(response: LLMResponse) -> AIMessage:
    """Rebuild a LangChain `AIMessage` (with proper `tool_calls`) from an
    `LLMResponse`, so it can be appended back into the running `messages`
    history — a `ToolMessage` answering a tool call is only valid in that
    history if it follows an `AIMessage` that requested the matching id.
    """
    tool_calls = [
        make_tool_call(name=tc.name, args=tc.arguments, id=tc.id) for tc in response.tool_calls
    ]
    return AIMessage(content=response.content, tool_calls=tool_calls)
