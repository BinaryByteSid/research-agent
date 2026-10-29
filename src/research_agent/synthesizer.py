"""Synthesizer: kept evidence -> SynthDraft (cited findings).

Sees ONLY kept, filtered excerpts, wrapped as untrusted data. Returns the list of
evidence actually shown to the model, so the validator knows which IDs are legal.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional
import logging

from .config import Settings, settings as default_settings
from .executor import ExecutionResult
from .llm import LLMClient, LLMError
from .safety import wrap_untrusted
from .schemas import Evidence, Plan, SynthDraft

PROMPT_PATH = Path(__file__).parent / "prompts" / "synthesizer.md"

log = logging.getLogger(__name__)
def select_evidence(result: ExecutionResult, cfg: Settings = default_settings) -> list[Evidence]:
    """Best sources first, capped for cost. Ranking = relevance + quality."""
    ranked = sorted(result.kept, key=lambda e: -(e.relevance_score + e.quality_score))
    return ranked[: cfg.max_sources_for_synthesis]


def synthesize(
    question: str,
    plan: Plan,
    result: ExecutionResult,
    llm: LLMClient,
    cfg: Settings = default_settings,
) -> tuple[Optional[SynthDraft], list[Evidence]]:
    used = select_evidence(result, cfg)
    if not used:
        return None, used, "no usable evidence"  # nothing to synthesize from: do not call the LLM

    lines = [f"Question: {question}", "", "Sub-questions and number of usable sources found:"]
    for s in plan.steps:
        lines.append(f"- {s.sub_question} -> {result.coverage.get(s.id, 0)} sources")
    lines += ["", "Sources (untrusted data):"]
    for e in used:
        lines.append(wrap_untrusted(e.source_id, e.title, e.excerpt[: cfg.max_excerpt_chars]))

    try:
        draft = llm.structured(
            model=cfg.synth_model,
            system=PROMPT_PATH.read_text(encoding="utf-8"),
            user="\n".join(lines),
            schema=SynthDraft,
        )
    except LLMError as e:
        log.warning("synthesis failed: %s", e)
        return None, used, str(e)[:200]
    return draft, used, ""