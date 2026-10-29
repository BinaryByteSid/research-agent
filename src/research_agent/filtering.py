"""Source filtering: dedupe, relevance, quality, injection quarantine.

Every dropped source gets a human-readable dropped_reason, which feeds the
trace log and the evaluation doc. Recency scoring is NOT implemented (search
results don't reliably carry dates); that is a documented limitation.
"""
from __future__ import annotations

import hashlib
import re
from typing import Optional
from urllib.parse import urlparse

from .config import Settings, settings as default_settings
from .safety import scan_for_injection
from .schemas import Evidence

STOPWORDS = {
    "the", "and", "for", "with", "what", "which", "are", "how", "does", "that", "this",
    "from", "into", "their", "they", "about", "between", "compare", "comparison", "using",
    "used", "use", "best", "top", "main", "major", "key", "aspects", "terms", "relevant",
    "common", "commonly", "widely", "when", "where", "why", "can", "should", "have", "has",
}


def normalize_url(url: str) -> str:
    p = urlparse(url.strip())
    host = (p.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return f"{host}{p.path.rstrip('/')}"


def fingerprint(text: str) -> str:
    norm = re.sub(r"\s+", " ", text.lower()).strip()[:300]
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()


def _terms(text: str) -> set[str]:
    out = set()
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        if len(w) < 3 or w in STOPWORDS:
            continue
        out.add(w[:-1] if w.endswith("s") and len(w) > 3 else w)
    return out


def relevance(query: str, title: str, text: str) -> float:
    """Fraction of the query's meaningful terms that appear in the source."""
    q = _terms(query)
    if not q:
        return 0.5
    d = _terms(f"{title} {text[:3000]}")
    return len(q & d) / len(q)


def domain_quality(url: str, cfg: Settings) -> Optional[float]:
    """None means blocked; otherwise a base quality in [0, 1]."""
    host = (urlparse(url).hostname or "").lower()
    if any(d in host for d in cfg.blocked_domains):
        return None
    score = 0.5
    if any(d in host for d in cfg.preferred_domains):
        score += 0.3
    return score


class SourceFilter:
    """Stateful per run, so duplicates are detected across rounds."""

    def __init__(self, cfg: Settings = default_settings):
        self.cfg = cfg
        self._urls: set[str] = set()
        self._fingerprints: set[str] = set()

    def first_visit(self, url: str) -> bool:
        """True the first time a URL is seen (and registers it)."""
        key = normalize_url(url)
        if key in self._urls:
            return False
        self._urls.add(key)
        return True

    def is_blocked(self, url: str) -> bool:
        return domain_quality(url, self.cfg) is None

    def evaluate(self, ev: Evidence, query: str) -> Evidence:
        """Score the evidence and set dropped_reason if it should not be used."""
        text = ev.excerpt

        # 1. Security first: quarantine anything that looks like an injection attempt.
        hits = scan_for_injection(f"{ev.title}\n{text}")
        if hits:
            ev.injection_flagged = True
            ev.dropped_reason = f"possible prompt injection ({', '.join(hits)})"
            return ev

        # 2. Scores
        ev.relevance_score = relevance(query, ev.title, text)
        base = domain_quality(ev.url, self.cfg)
        if base is None:
            ev.dropped_reason = "blocked domain"
            return ev
        if len(text.strip()) < 150:
            base -= 0.35  # very thin content is weak evidence
        ev.quality_score = max(0.0, min(1.0, base))

        # 3. Thresholds
        if ev.relevance_score < self.cfg.min_relevance:
            ev.dropped_reason = f"low relevance ({ev.relevance_score:.2f})"
        elif ev.quality_score < self.cfg.min_quality:
            ev.dropped_reason = f"low quality ({ev.quality_score:.2f})"
        else:
            fp = fingerprint(text)
            if fp in self._fingerprints:
                ev.dropped_reason = "duplicate content"
            else:
                self._fingerprints.add(fp)
        return ev