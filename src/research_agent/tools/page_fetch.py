"""Fetch a URL and extract clean main-content text.

Guards: http(s) only, private/localhost blocked, content-type check,
download size cap, timeout, near-empty extraction treated as failure.
"""
from __future__ import annotations

import ipaddress
from typing import Optional
from urllib.parse import urlparse

import httpx
import trafilatura

from ..config import Settings, settings as default_settings
from ..schemas import PageContent
from .base import Tool, ToolError, TransientToolError

ALLOWED_CONTENT_TYPES = ("text/html", "application/xhtml+xml", "text/plain")
USER_AGENT = "Mozilla/5.0 (compatible; ResearchAgentBot/0.1)"


def _is_blocked_host(host: str) -> bool:
    host = host.lower().strip("[]")
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".internal"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False  # a normal hostname
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved


class PageFetchTool(Tool):
    name = "page_fetch"
    output_model = PageContent

    def __init__(self, cfg: Settings = default_settings, http: Optional[httpx.Client] = None):
        super().__init__(cfg)
        self.http = http or httpx.Client(timeout=cfg.tool_timeout_s, follow_redirects=True)

    def _execute(self, url: str) -> dict:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ToolError(f"unsupported URL: {url}")
        if _is_blocked_host(parsed.hostname):
            raise ToolError("blocked host (private/local address)")

        try:
            with self.http.stream("GET", url, headers={"User-Agent": USER_AGENT}) as r:
                if r.status_code == 429 or r.status_code >= 500:
                    raise TransientToolError(f"HTTP {r.status_code}")
                if r.status_code >= 400:
                    raise ToolError(f"HTTP {r.status_code}")

                ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
                if ctype and ctype not in ALLOWED_CONTENT_TYPES:
                    raise ToolError(f"unsupported content-type: {ctype}")

                chunks, total, oversize = [], 0, False
                for chunk in r.iter_bytes():
                    total += len(chunk)
                    if total > self.cfg.max_page_bytes:
                        oversize = True
                        break
                    chunks.append(chunk)
                encoding = r.encoding or "utf-8"
        except (httpx.TimeoutException, httpx.TransportError) as e:
            raise TransientToolError(f"{type(e).__name__}: {e}") from e

        html = b"".join(chunks).decode(encoding, errors="replace")

        text = trafilatura.extract(html, include_comments=False, include_tables=True) or ""
        if not text.strip():
            raise ToolError("no extractable text")

        meta = trafilatura.extract_metadata(html)
        title = (meta.title or "") if meta else ""

        truncated = oversize
        if len(text) > self.cfg.max_excerpt_chars:
            text = text[: self.cfg.max_excerpt_chars]
            truncated = True

        return {
            "url": url, "title": title, "text": text,
            "content_type": ctype, "truncated": truncated,
        }