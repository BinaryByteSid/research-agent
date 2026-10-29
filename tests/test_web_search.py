import httpx

from research_agent.config import Settings
from research_agent.tools.web_search import (
    DuckDuckGoSearchTool, TavilySearchTool, build_search_tool,
)
from research_agent.tools.base import FallbackTool

CFG = Settings(tavily_api_key="test-key", tool_max_retries=2, tool_backoff_base_s=0.0)


def tavily_with(handler):
    return TavilySearchTool(CFG, http=httpx.Client(transport=httpx.MockTransport(handler)))


def test_tavily_success_and_skips_malformed_hit():
    def handler(request):
        return httpx.Response(200, json={"results": [
            {"title": "Qdrant", "url": "https://qdrant.tech", "content": "vector db", "score": 0.9},
            {"title": "Bad", "url": "not-a-url", "content": "x"},   # malformed: skipped
        ]})
    res = tavily_with(handler).run(query="vector databases")
    assert res.ok
    assert len(res.data.hits) == 1 and res.data.provider == "tavily"


def test_tavily_retries_on_429_then_succeeds():
    state = {"n": 0}

    def handler(request):
        state["n"] += 1
        if state["n"] < 3:
            return httpx.Response(429)
        return httpx.Response(200, json={"results": [
            {"title": "A", "url": "https://a.com", "content": "c"}]})
    res = tavily_with(handler).run(query="q")
    assert res.ok and res.attempts == 3


def test_tavily_bad_key_not_retried():
    state = {"n": 0}

    def handler(request):
        state["n"] += 1
        return httpx.Response(401)
    res = tavily_with(handler).run(query="q")
    assert not res.ok and state["n"] == 1


def test_fallback_to_duckduckgo_when_tavily_down():
    def handler(request):
        return httpx.Response(503)

    def fake_ddg(query, n):
        return [{"title": "DDG hit", "href": "https://example.com", "body": "snippet"}]

    search = FallbackTool("web_search", [
        tavily_with(handler),
        DuckDuckGoSearchTool(CFG, search_fn=fake_ddg),
    ])
    res = search.run(query="q")
    assert res.ok and res.data.provider == "duckduckgo"
    assert len(res.fallback_errors) == 1


def test_build_search_tool_has_two_providers():
    assert len(build_search_tool(CFG).tools) == 2