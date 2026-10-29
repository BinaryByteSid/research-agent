"""Validator: code-level checks on the LLM draft + computed confidence + guardrail.

Nothing here calls an LLM. It enforces:
- every cited source ID must be one the model was actually shown
- findings with no valid citation are dropped
- findings that look like injected instructions are dropped
- confidence comes from independent domains, sub-question coverage and citation integrity
- below a threshold the answer is replaced by an explicit refusal
"""
from __future__ import annotations

from typing import Optional
from urllib.parse import urlparse

from .config import Settings, settings as default_settings
from .executor import ExecutionResult
from .safety import scan_for_injection
from .schemas import (
    Confidence, ConfidenceLevel, Evidence, FinalAnswer, Finding, Plan, Source, SynthDraft,
)


def registered_domain(url: str) -> str:
    """Rough registered domain (last two labels). Good enough to count independent sites."""
    host = (urlparse(url).hostname or "").lower()
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def _level(score: float, n_domains: int, coverage: float) -> ConfidenceLevel:
    if score >= 0.75 and n_domains >= 3 and coverage >= 1.0:
        return ConfidenceLevel.HIGH
    if score >= 0.45:
        return ConfidenceLevel.MEDIUM
    return ConfidenceLevel.LOW


def build_final_answer(
    question: str,
    plan: Plan,
    result: ExecutionResult,
    used: list[Evidence],
    draft: Optional[SynthDraft],
    synth_error: str = "",
    cfg: Settings = default_settings,
) -> FinalAnswer:
    by_id = {e.source_id: e for e in used}
    limitations: list[str] = []
    next_steps: list[str] = []

    # --- 1. clean the draft's findings ---
    clean: list[Finding] = []
    n_draft = 0
    n_bad = 0
    if draft is not None:
        n_draft = len(draft.key_findings)
        for f in draft.key_findings:
            ids = [i for i in dict.fromkeys(f.source_ids) if i in by_id]
            if not ids or scan_for_injection(f.claim):
                n_bad += 1
                continue
            clean.append(Finding(claim=f.claim, source_ids=ids))
        limitations += draft.limitations
        next_steps += draft.next_steps
    else:
        limitations.append("The synthesis step produced no usable draft (no evidence or LLM failure).")

    if n_bad:
        limitations.append(
            f"{n_bad} drafted finding(s) were removed because their citations were invalid or the text looked unsafe."
        )

    # --- 2. sources = only what was actually cited ---
    cited_ids: list[str] = []
    for f in clean:
        for i in f.source_ids:
            if i not in cited_ids:
                cited_ids.append(i)
    sources = [Source(source_id=i, url=by_id[i].url, title=by_id[i].title) for i in cited_ids]

    # --- 3. deterministic limitations from the run itself ---
    for s in plan.steps:
        if result.coverage.get(s.id, 0) == 0:
            limitations.append(f"No usable sources were found for: {s.sub_question}")
    flagged = sum(1 for e in result.evidence if e.injection_flagged)
    if flagged:
        limitations.append(f"{flagged} source(s) were excluded as possible prompt-injection attempts.")
    if result.search_failures:
        limitations.append(f"{result.search_failures} search call(s) failed, so coverage may be incomplete.")

    # --- 4. confidence (heuristic, not calibrated) ---
    domains = {registered_domain(by_id[i].url) for i in cited_ids}
    domain_score = min(1.0, len(domains) / 3)
    coverage_score = (
        sum(1 for c in result.coverage.values() if c > 0) / len(result.coverage)
        if result.coverage else 0.0
    )
    integrity = (len(clean) / n_draft) if n_draft else 0.0
    score = round(0.40 * domain_score + 0.35 * coverage_score + 0.25 * integrity, 2)
    level = _level(score, len(domains), coverage_score)
    reasons = [
        f"{len(clean)} cited finding(s) drawn from {len(domains)} independent domain(s)",
        f"{round(coverage_score * 100)}% of sub-questions had usable sources",
        f"{round(integrity * 100)}% of drafted findings passed citation checks",
        "Score is a heuristic and has not been calibrated against ground truth",
    ]

    # --- 5. low-confidence guardrail ---
    if not clean or score < cfg.min_confidence_to_answer:
        return FinalAnswer(
            question=question,
            short_answer="Insufficient reliable evidence to answer this question.",
            key_findings=[],
            sources=[],
            confidence=Confidence(level=ConfidenceLevel.LOW, score=score, reasons=reasons),
            limitations=limitations or ["No usable evidence was retrieved."],
            next_steps=next_steps or ["Rephrase the question, narrow its scope, or try again later."],
        )

    short = draft.short_answer if draft else ""
    if level == ConfidenceLevel.LOW:
        short = f"Low confidence: {short}"
        limitations.append("Overall confidence is low; treat this answer as a starting point only.")

    return FinalAnswer(
        question=question,
        short_answer=short,
        key_findings=clean,
        sources=sources,
        confidence=Confidence(level=level, score=score, reasons=reasons),
        limitations=limitations,
        next_steps=next_steps,
    )