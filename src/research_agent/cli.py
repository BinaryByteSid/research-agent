"""CLI: python -m research_agent "your question" [--json] [--save samples/name]"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .llm import LLMConfigError
from .pipeline import RunOutput, run_research
from .schemas import FinalAnswer


def render_markdown(a: FinalAnswer) -> str:
    out = [f"# {a.question}", "", "## Short answer", a.short_answer, ""]
    if a.key_findings:
        out += ["## Key findings"]
        out += [f"- {f.claim} [{', '.join(f.source_ids)}]" for f in a.key_findings]
        out += [""]
    if a.sources:
        out += ["## Sources"]
        out += [f"- [{s.source_id}] {s.title or s.url} - {s.url}" for s in a.sources]
        out += [""]
    out += [f"## Confidence: {a.confidence.level.value} ({a.confidence.score:.2f})"]
    out += [f"- {r}" for r in a.confidence.reasons] + [""]
    if a.limitations:
        out += ["## Limitations"] + [f"- {x}" for x in a.limitations] + [""]
    if a.next_steps:
        out += ["## Suggested next steps"] + [f"- {x}" for x in a.next_steps] + [""]
    return "\n".join(out)


def _save(out: RunOutput, base: str) -> None:
    p = Path(base)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.with_suffix(".json").write_text(out.answer.model_dump_json(indent=2), encoding="utf-8")
    p.with_suffix(".md").write_text(render_markdown(out.answer), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="research_agent", description="Production-oriented research agent")
    ap.add_argument("question", nargs="+", help="the research question")
    ap.add_argument("--json", action="store_true", help="print JSON instead of markdown")
    ap.add_argument("--save", metavar="PATH", help="save .json and .md, e.g. samples/sample_2")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO if args.verbose else logging.ERROR)
    question = " ".join(args.question)

    try:
        out = run_research(question)
    except LLMConfigError as e:
        print(f"Configuration error: {e}\nFix your .env (key, base URL, model name) and try again.",
              file=sys.stderr)
        return 2
    except Exception as e:
        print(f"Run failed unexpectedly: {type(e).__name__}: {e}\nSee the latest file in logs/.",
              file=sys.stderr)
        return 1

    print(out.answer.model_dump_json(indent=2) if args.json else render_markdown(out.answer))
    print(f"\n[run {out.run_id} | {out.latency_s}s | llm calls: {out.usage['calls']} | "
          f"tokens in/out: {out.usage['prompt_tokens']}/{out.usage['completion_tokens']} | trace: {out.trace_path}]")
    if args.save:
        _save(out, args.save)
    return 0


if __name__ == "__main__":
    sys.exit(main())