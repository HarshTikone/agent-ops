"""`llm_response_from_ai_message`: regression coverage for a bug caught by
live verification against real Gemini (ADR-013), not by any mocked test —
`ChatGoogleGenerativeAI` returns `.content` as a list of content blocks, not
a plain string, and the original `str(ai_message.content)` fallback produced
a stringified Python list (e.g. "[{'type': 'text', 'text': '...', ...}]")
instead of the answer text.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage

from app.llm.base import (
    LLMResponse,
    ToolCallRequest,
    ai_message_from_llm_response,
    llm_response_from_ai_message,
)


def test_extracts_plain_text_from_a_plain_string_content() -> None:
    message = AIMessage(content="47 times 89 is 4,183.")
    response = llm_response_from_ai_message(message, provider="openrouter")
    assert response.content == "47 times 89 is 4,183."


def test_extracts_plain_text_from_gemini_style_content_blocks() -> None:
    """Reproduces the exact shape a real Gemini call returned."""
    message = AIMessage(
        content=[
            {
                "type": "text",
                "text": "47 times 89 is 4,183.",
                "extras": {"signature": "opaque-thought-signature"},
            }
        ]
    )
    response = llm_response_from_ai_message(message, provider="gemini")
    assert response.content == "47 times 89 is 4,183."
    assert "extras" not in response.content
    assert "signature" not in response.content


def test_empty_content_with_only_tool_calls_is_an_empty_string() -> None:
    message = AIMessage(
        content="", tool_calls=[{"name": "calculator", "args": {"expression": "1+1"}, "id": "c1"}]
    )
    response = llm_response_from_ai_message(message, provider="gemini")
    assert response.content == ""
    assert response.tool_calls == [
        ToolCallRequest(id="c1", name="calculator", arguments={"expression": "1+1"})
    ]


def test_ai_message_from_llm_response_round_trips_tool_calls() -> None:
    response = LLMResponse(
        content="using a tool",
        tool_calls=[ToolCallRequest(id="c1", name="calculator", arguments={"expression": "1+1"})],
        provider="gemini",
    )
    message = ai_message_from_llm_response(response)
    assert message.tool_calls == [
        {"name": "calculator", "args": {"expression": "1+1"}, "id": "c1", "type": "tool_call"}
    ]
