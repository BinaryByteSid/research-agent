"""Web search: Tavily (primary) with DuckDuckGo fallback."""
from __future__ import annotations

from typing import Any, Callable, Optional

import httpx

from ..config import Settings, settings as default_settings
from ..schemas import SearchHit
from .base import FallbackTool, Tool, ToolError, TransientToolError

TAVILY_URL = "https://api.tavily.com/search"


def _clean_hits(items: list[dict], url_key: str, snippet_key: str) -> list[dict]:
    """Skip individual malformed results instead of failing the whole search."""
    hits = []
    for it in items:
        try:
            hit = SearchHit(
                url=str(it.get(url_key, "")),
                title=str(it.get("title", "") or ""),
                snippet=str(it.get(snippet_key, "") or ""),
                score=it.get("score"),
            )
            hits.append(hit.model_dump())
        except Exception:
            continue  # drop the bad hit, keep the rest
    return hits


class TavilySearchTool(Tool):
    name = "tavily_search"
    output_model = None  # set below (avoids circular import ordering issues)

    def __init__(self, cfg: Settings = default_settings, http: Optional[httpx.Client] = None):
        super().__init__(cfg)
        self.http = http or httpx.Client(timeout=cfg.tool_timeout_s)

    def _execute(self, query: str, max_results: Optional[int] = None) -> dict:
        if not self.cfg.tavily_api_key:
            raise ToolError("TAVILY_API_KEY not set")
        if not query.strip():
            raise ToolError("empty query")

        try:
            r = self.http.post(
                TAVILY_URL,
                headers={"Authorization": f"Bearer {self.cfg.tavily_api_key}"},
                json={
                    "query": query,
                    "max_results": max_results or self.cfg.max_results_per_search,
                    "search_depth": "basic",
                },
            )
        except (httpx.TimeoutException, httpx.TransportError) as e:
            raise TransientToolError(f"{type(e).__name__}: {e}") from e

        if r.status_code == 429 or r.status_code >= 500:
            raise TransientToolError(f"HTTP {r.status_code}")
        if r.status_code >= 400:
            raise ToolError(f"HTTP {r.status_code} (check API key / quota)")

        try:
            payload = r.json()
        except ValueError as e:
            raise TransientToolError("response was not valid JSON") from e

        hits = _clean_hits(payload.get("results", []) or [], "url", "content")
        if not hits:
            raise ToolError("no usable results")  # lets the fallback provider try
        return {"query": query, "provider": "tavily", "hits": hits}


class DuckDuckGoSearchTool(Tool):
    name = "duckduckgo_search"
    output_model = None

    def __init__(
        self,
        cfg: Settings = default_settings,
        search_fn: Optional[Callable[[str, int], list[dict]]] = None,
    ):
        super().__init__(cfg)
        self._search_fn = search_fn  # injectable so tests need no network

    def _default_search(self, query: str, n: int) -> list[dict]:
        try:
            from ddgs import DDGS
        except ImportError as e:
            raise ToolError("ddgs package not installed") from e
        return DDGS(timeout=int(self.cfg.tool_timeout_s)).text(query, max_results=n)

    def _execute(self, query: str, max_results: Optional[int] = None) -> dict:
        if not query.strip():
            raise ToolError("empty query")
        n = max_results or self.cfg.max_results_per_search
        fn = self._search_fn or self._default_search
        try:
            items = fn(query, n)
        except ToolError:
            raise
        except Exception as e:  # rate limits / network errors from ddgs
            raise TransientToolError(f"{type(e).__name__}: {e}") from e

        hits = _clean_hits(items or [], "href", "body")
        if not hits:
            raise ToolError("no usable results")
        return {"query": query, "provider": "duckduckgo", "hits": hits}


# Assign output models after imports to keep the class bodies readable.
from ..schemas import SearchOutput  # noqa: E402

TavilySearchTool.output_model = SearchOutput
DuckDuckGoSearchTool.output_model = SearchOutput


def build_search_tool(cfg: Settings = default_settings) -> FallbackTool:
    """The 'web_search' tool the planner refers to: Tavily first, DuckDuckGo if it fails."""
    return FallbackTool("web_search", [TavilySearchTool(cfg), DuckDuckGoSearchTool(cfg)])