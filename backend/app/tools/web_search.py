"""Web search tool (ADR-011): Tavily, verified live 2026-08-23.

Free "Development" API key: 1,000 credits/month, 100 requests/min, no card
(1 credit per basic search) — see ADR-011 and the update to ADR-003's table.
Auth is a bearer header (`Authorization: Bearer tvly-...`), not a body field
— verified against Tavily's own API reference, not assumed from convention.
"""

from __future__ import annotations

from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field, field_validator

from app.tools.errors import ToolError

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
_REQUEST_TIMEOUT_SECONDS = 15


class WebSearchArgs(BaseModel):
    query: str = Field(min_length=1, max_length=500, description="Search query")
    include_domains: list[str] = Field(
        default_factory=list,
        max_length=5,
        description="Official domains that every returned result must match",
    )

    @field_validator("query")
    @classmethod
    def trim_query(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("search query must not be blank")
        return value

    @field_validator("include_domains")
    @classmethod
    def normalize_domains(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for raw_domain in value:
            domain = raw_domain.strip().lower().rstrip(".")
            if (
                not domain
                or "://" in domain
                or "/" in domain
                or "@" in domain
                or ":" in domain
                or "." not in domain
                or any(
                    not label
                    or len(label) > 63
                    or label.startswith("-")
                    or label.endswith("-")
                    or not all(
                        character in "abcdefghijklmnopqrstuvwxyz0123456789-" for character in label
                    )
                    for label in domain.split(".")
                )
            ):
                raise ValueError("include_domains entries must be plain hostnames")
            if domain not in normalized:
                normalized.append(domain)
        return normalized


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
        return self.run(query=args.query, include_domains=args.include_domains)

    def run(self, *, query: str, include_domains: list[str] | None = None) -> str:
        if not self._api_key:
            raise ToolError("TAVILY_API_KEY not configured", transient=False)

        try:
            payload: dict[str, object] = {"query": query, "max_results": 5}
            if include_domains:
                payload["include_domains"] = include_domains
            response = self._client.post(
                TAVILY_SEARCH_URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
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

        if not isinstance(data, dict):
            raise ToolError("web search returned an invalid response", transient=False)

        raw_results = data.get("results", [])
        if not isinstance(raw_results, list):
            raise ToolError("web search returned an invalid response", transient=False)

        results = []
        for result in raw_results:
            if not isinstance(result, dict):
                continue
            parsed_url = urlparse(str(result.get("url", "")))
            if parsed_url.scheme not in {"http", "https"} or not parsed_url.hostname:
                continue
            results.append(result)

        if include_domains:
            allowed_domains = tuple(include_domains)
            results = [
                result
                for result in results
                if (
                    (hostname := urlparse(str(result.get("url", ""))).hostname)
                    and any(
                        hostname == domain or hostname.endswith(f".{domain}")
                        for domain in allowed_domains
                    )
                )
            ]
        if not results:
            if include_domains:
                return "No results found from the requested official domains."
            return "No results found."
        lines = [
            f"- {r.get('title', '')}: {r.get('url', '')} — {str(r.get('content', ''))[:200]}"
            for r in results
        ]
        return "\n".join(lines)
