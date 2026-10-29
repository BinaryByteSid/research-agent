"""Prompt-injection awareness for untrusted web content.

Two defences:
1. scan_for_injection(): heuristic detector. Flagged sources are quarantined (dropped + logged).
2. wrap_untrusted(): when text must go into a prompt, delimit it and neutralise tag breakouts.

Heuristics are NOT a complete defence. The structural defences matter more:
the planner never sees web text, and the reflection step can only emit search queries.
"""
from __future__ import annotations

import re

_PATTERNS = {
    "ignore_previous": r"\b(ignore|disregard|forget)\b[^.\n]{0,30}\b(previous|prior|above|earlier|all)\b[^.\n]{0,30}\b(instructions?|prompts?|rules|context)\b",
    "reveal_prompt": r"\b(reveal|show|print|repeat|output)\b[^.\n]{0,20}\b(system|hidden|initial)\s+(prompt|instructions?)\b",
    "role_override": r"\byou are now\b|\bfrom now on,? you\b",
    "new_instructions": r"\bnew instructions?\s*:",
    "system_tag": r"</?\s*(system|assistant|developer)\s*>|\[/?(INST|SYSTEM)\]",
    "exfiltrate": r"\b(send|post|email|upload|forward)\b[^.\n]{0,60}\b(api[ _-]?keys?|passwords?|credentials|secrets?|tokens?)\b",
    "hide_from_user": r"\bdo not (tell|mention|inform|reveal)\b[^.\n]{0,30}\buser\b",
    "plan_override": r"\boverride\b[^.\n]{0,20}\b(plan|tools?|rules|instructions?)\b",
}
_COMPILED = {name: re.compile(rx, re.IGNORECASE) for name, rx in _PATTERNS.items()}


def scan_for_injection(text: str) -> list[str]:
    """Return the names of all injection heuristics that match (empty list = clean)."""
    return [name for name, rx in _COMPILED.items() if rx.search(text)]


def wrap_untrusted(source_id: str, title: str, text: str) -> str:
    """Delimit untrusted text for inclusion in a prompt."""
    safe_text = text.replace("</source", "<\\/source").replace("<source", "<\\source")
    safe_title = title.replace('"', "'").replace("<", "").replace(">", "")
    return f'<source id="{source_id}" title="{safe_title}">\n{safe_text}\n</source>'