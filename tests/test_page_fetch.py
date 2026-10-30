import httpx

from research_agent.config import Settings
from research_agent.tools.page_fetch import PageFetchTool

CFG = Settings(tool_max_retries=1, tool_backoff_base_s=0.0, max_excerpt_chars=3000)

HTML = (
    "<html><head><title>Qdrant Docs</title></head><body><article><h1>Qdrant</h1>"
    "<p>Qdrant is an open source vector database written in Rust and built for similarity search.</p>"
    "<p>It supports filtering on payload fields, which is useful for retrieval augmented generation.</p>"
    "<p>Deployment options include Docker, Kubernetes, and a managed cloud offering for startups.</p>"
    "<p>Collections store points, and each point has a vector plus an optional JSON payload.</p>"
    "</article></body></html>"
)


def tool_with(handler):
    return PageFetchTool(CFG, http=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True))


def test_fetch_extracts_text():
    t = tool_with(lambda req: httpx.Response(200, text=HTML, headers={"content-type": "text/html; charset=utf-8"}))
    res = t.run(url="https://qdrant.tech/docs")
    assert res.ok
    assert "vector database" in res.data.text


def test_rejects_non_html_content_type():
    t = tool_with(lambda req: httpx.Response(200, content=b"%PDF-1.4", headers={"content-type": "application/pdf"}))
    res = t.run(url="https://example.com/file.pdf")
    assert not res.ok and "content-type" in res.error


def test_blocks_localhost_and_private_ips():
    t = tool_with(lambda req: httpx.Response(200, text=HTML))
    for url in ("http://localhost:8000/admin", "http://127.0.0.1/x", "http://192.168.1.1/", "http://169.254.169.254/latest/meta-data"):
        res = t.run(url=url)
        assert not res.ok and "blocked" in res.error


def test_rejects_non_http_scheme():
    t = tool_with(lambda req: httpx.Response(200, text=HTML))
    assert not t.run(url="file:///etc/passwd").ok


def test_404_is_permanent_and_500_is_retried():
    state = {"n": 0}

    def handler_500(req):
        state["n"] += 1
        return httpx.Response(500)

    res = tool_with(handler_500).run(url="https://example.com")
    assert not res.ok and state["n"] == 2  # 1 try + 1 retry (CFG.tool_max_retries=1)

    res404 = tool_with(lambda req: httpx.Response(404)).run(url="https://example.com")
    assert not res404.ok and res404.attempts == 1


def test_oversized_page_is_flagged_truncated():
    small_cap = Settings(tool_max_retries=0, max_page_bytes=300, max_excerpt_chars=3000)
    t = PageFetchTool(small_cap, http=httpx.Client(transport=httpx.MockTransport(
        lambda req: httpx.Response(200, text=HTML * 5, headers={"content-type": "text/html"}))))
    res = t.run(url="https://example.com")
    # either extraction succeeds on the partial page (truncated=True) or fails cleanly
    assert (res.ok and res.data.truncated) or (not res.ok and "no extractable text" in res.error)
def test_tls_certificate_error_is_permanent():
    state = {"n": 0}

    def handler(req):
        state["n"] += 1
        raise httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] Hostname mismatch")

    res = tool_with(handler).run(url="https://example.com")
    assert not res.ok and state["n"] == 1 and "TLS" in res.error


def test_redirect_to_private_address_is_blocked():
    def handler(req):
        if req.url.host == "example.com":
            return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data"})
        return httpx.Response(200, text=HTML, headers={"content-type": "text/html"})

    res = tool_with(handler).run(url="https://example.com/x")
    assert not res.ok and "blocked" in res.error