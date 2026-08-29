"""Web search tool (ADR-011): Tavily, verified live 2026-08-23.

Free "Development" API key: 1,000 credits/month, 100 requests/min, no card
(1 credit per basic search) — see ADR-011 and the update to ADR-003's table.
Auth is a bearer header (`Authorization: Bearer tvly-...`), not a body field
— verified against Tavily's own API reference, not assumed from convention.
"""

from __future__ import annotations

import httpx
from pydantic import BaseModel, Field, field_validator

from app.tools.errors import ToolError

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
_REQUEST_TIMEOUT_SECONDS = 15


class WebSearchArgs(BaseModel):
    query: str = Field(min_length=1, max_length=500, description="Search query")

    @field_validator("query")
    @classmethod
    def trim_query(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("search query must not be blank")
        return value


class WebSearchTool:
    name = "web_search"
    description = (
        "Search the live web for current information. Returns a short list "
        "of results with titles, URLs, and snippets."
    )
    args_schema = WebSearchArgs

    def __init__(self, api_key: str, *, client: httpx.Client | None = None) -> None:
        self._api_key = api_key
        self._client = client or httpx.Client(timeout=_REQUEST_TIMEOUT_SECONDS)

    def invoke(self, arguments: dict[str, object]) -> str:
        args = self.args_schema.model_validate(arguments)
        return self.run(query=args.query)

    def run(self, *, query: str) -> str:
        if not self._api_key:
            raise ToolError("TAVILY_API_KEY not configured", transient=False)

        try:
            response = self._client.post(
                TAVILY_SEARCH_URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={"query": query, "max_results": 5},
            )
        except httpx.TimeoutException as exc:
            raise ToolError(f"web search timed out: {exc}", transient=True) from exc
        except httpx.TransportError as exc:
            raise ToolError("web search transport failed", transient=True) from exc

        if response.status_code == 429:
            raise ToolError("web search rate-limited", transient=True)
        if response.status_code >= 500:
            raise ToolError(f"web search server error {response.status_code}", transient=True)
        if response.status_code >= 400:
            raise ToolError(f"web search request error {response.status_code}", transient=False)

        try:
            data = response.json()
        except ValueError as exc:
            raise ToolError(f"web search returned malformed JSON: {exc}", transient=False) from exc

        results = data.get("results", [])
        if not results:
            return "No results found."
        lines = [
            f"- {r.get('title', '')}: {r.get('url', '')} — {r.get('content', '')[:200]}"
            for r in results
        ]
        return "\n".join(lines)
