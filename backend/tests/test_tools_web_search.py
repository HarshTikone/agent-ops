"""WebSearchTool: every failure mode is mocked — no real Tavily calls in the
test suite (live verification is done manually, once, outside pytest; see
ADR-011)."""

import httpx
import pytest

from app.tools.errors import ToolError
from app.tools.web_search import WebSearchTool


class _FakeTransport(httpx.BaseTransport):
    def __init__(self, handler):
        self._handler = handler

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return self._handler(request)


def _tool_with_response(
    status_code: int, json_body: dict | None = None, text: str = ""
) -> WebSearchTool:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-key"
        if json_body is not None:
            return httpx.Response(status_code, json=json_body)
        return httpx.Response(status_code, text=text)

    client = httpx.Client(transport=_FakeTransport(handler))
    return WebSearchTool(api_key="test-key", client=client)


def _tool_raising(exc: Exception) -> WebSearchTool:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc

    client = httpx.Client(transport=_FakeTransport(handler))
    return WebSearchTool(api_key="test-key", client=client)


def test_missing_api_key_raises_permanent_tool_error_without_a_network_call() -> None:
    tool = WebSearchTool(api_key="")
    with pytest.raises(ToolError) as exc_info:
        tool.run(query="anything")
    assert exc_info.value.transient is False


def test_query_schema_rejects_whitespace_only_input() -> None:
    with pytest.raises(ValueError, match="search query must not be blank"):
        WebSearchTool(api_key="test-key").invoke({"query": "   "})


def test_successful_search_formats_results() -> None:
    tool = _tool_with_response(
        200,
        {
            "results": [
                {
                    "title": "LangGraph docs",
                    "url": "https://example.com",
                    "content": "graph-based agents",
                }
            ]
        },
    )
    result = tool.run(query="langgraph")
    assert "LangGraph docs" in result
    assert "https://example.com" in result


def test_no_results_is_not_an_error() -> None:
    tool = _tool_with_response(200, {"results": []})
    assert tool.run(query="query with no hits") == "No results found."


def test_timeout_is_a_transient_tool_error() -> None:
    tool = _tool_raising(httpx.TimeoutException("timed out"))
    with pytest.raises(ToolError) as exc_info:
        tool.run(query="anything")
    assert exc_info.value.transient is True


def test_connection_failure_is_a_transient_tool_error() -> None:
    tool = _tool_raising(httpx.ConnectError("connection refused"))
    with pytest.raises(ToolError) as exc_info:
        tool.run(query="anything")
    assert exc_info.value.transient is True


@pytest.mark.parametrize(
    "error_type",
    [httpx.ReadError, httpx.WriteError, httpx.RemoteProtocolError],
)
def test_other_transport_failures_are_transient(error_type) -> None:
    request = httpx.Request("POST", "https://api.tavily.com/search")
    tool = _tool_raising(error_type("transport failed", request=request))
    with pytest.raises(ToolError) as exc_info:
        tool.run(query="anything")
    assert exc_info.value.transient is True


def test_rate_limit_is_a_transient_tool_error() -> None:
    tool = _tool_with_response(429, text="rate limited")
    with pytest.raises(ToolError) as exc_info:
        tool.run(query="anything")
    assert exc_info.value.transient is True


def test_server_error_is_a_transient_tool_error() -> None:
    tool = _tool_with_response(503, text="upstream unavailable")
    with pytest.raises(ToolError) as exc_info:
        tool.run(query="anything")
    assert exc_info.value.transient is True


def test_bad_request_is_a_permanent_tool_error() -> None:
    tool = _tool_with_response(400, text="malformed query")
    with pytest.raises(ToolError) as exc_info:
        tool.run(query="anything")
    assert exc_info.value.transient is False
    assert "malformed query" not in str(exc_info.value)


def test_malformed_json_response_is_a_permanent_tool_error() -> None:
    tool = _tool_with_response(200, json_body=None, text="not json")
    with pytest.raises(ToolError) as exc_info:
        tool.run(query="anything")
    assert exc_info.value.transient is False
