"""Run every query through the agent (and the baseline for live queries).

Usage:
  python eval/run_eval.py                 # everything
  python eval/run_eval.py --only q7_injection
  python eval/run_eval.py --no-baseline
"""
import argparse
import json
import sys
import time
from pathlib import Path

import yaml

from baseline import run_baseline
from research_agent.llm import LLMConfigError
from research_agent.pipeline import run_research
from scenarios import tools_for

HERE = Path(__file__).parent


def trace_events(path: str) -> list[dict]:
    return [json.loads(line) for line in open(path, encoding="utf-8")]


def run_checks(q: dict, out) -> list[tuple[str, bool]]:
    a, ev = out.answer, trace_events(out.trace_path)
    text = a.model_dump_json().lower()
    checks: list[tuple[str, bool]] = []
    if "expect_plan_status" in q:
        checks.append((f"plan status = {q['expect_plan_status']}", out.plan_status == q["expect_plan_status"]))
    if "min_sources" in q:
        checks.append((f">= {q['min_sources']} cited sources", len(a.sources) >= q["min_sources"]))
    for s in q.get("must_not_contain", []):
        checks.append((f"answer lacks '{s}'", s.lower() not in text))
    if "expect_dropped_reason" in q:
        found = any(e["event"] == "source_dropped" and q["expect_dropped_reason"] in (e.get("reason") or "") for e in ev)
        checks.append((f"a source was dropped for '{q['expect_dropped_reason']}'", found))
    if q.get("expect_refusal"):
        checks.append(("guardrail refused cleanly", a.short_answer.startswith("Insufficient")))
    if "limitation_contains" in q:
        checks.append((f"limitations mention '{q['limitation_contains']}'",
                       any(q["limitation_contains"].lower() in l.lower() for l in a.limitations)))
    return checks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--no-baseline", action="store_true")
    args = ap.parse_args()

    queries = yaml.safe_load((HERE / "queries.yaml").read_text(encoding="utf-8"))
    if args.only:
        queries = [q for q in queries if q["id"] == args.only]

    results = []
    for q in queries:
        print(f"\n=== {q['id']} ({q['type']}) ===", flush=True)
        search, fetch = tools_for(q["scenario"])
        rec = {"id": q["id"], "type": q["type"], "query": q["query"], "expected": q["expected"]}
        try:
            out = run_research(q["query"], search_tool=search, fetch_tool=fetch)
            checks = run_checks(q, out)
            a = out.answer
            rec.update({
                "plan_status": out.plan_status,
                "latency_s": out.latency_s,
                "llm_calls": out.usage["calls"],
                "tokens_in": out.usage["prompt_tokens"],
                "tokens_out": out.usage["completion_tokens"],
                "repairs": out.usage["repairs"],
                "findings": len(a.key_findings),
                "sources": len(a.sources),
                "confidence": f"{a.confidence.level.value} ({a.confidence.score})",
                "short_answer": a.short_answer,
                "limitations": a.limitations,
                "checks": [{"check": c, "pass": ok} for c, ok in checks],
                "passed": all(ok for _, ok in checks),
                "trace": out.trace_path,
            })
            for c, ok in checks:
                print(("  PASS " if ok else "  FAIL ") + c)
        except LLMConfigError as e:
            print(f"Config error, stopping: {e}")
            return 2
        except Exception as e:
            rec.update({"crashed": f"{type(e).__name__}: {e}", "passed": False})
            print(f"  CRASH {type(e).__name__}: {e}")

        if q["scenario"] == "live" and q.get("expect_plan_status") == "ok" and not args.no_baseline:
            try:
                rec["baseline"] = run_baseline(q["query"])
                b = rec["baseline"]
                print(f"  baseline: {b['latency_s']}s, tokens {b['usage']['prompt_tokens']}/{b['usage']['completion_tokens']}, sources 0")
            except LLMConfigError as e:
                print(f"Config error, stopping: {e}")
                return 2

        results.append(rec)
        time.sleep(5)  # be gentle with free-tier rate limits

    (HERE / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")

    lines = ["| id | type | passed | confidence | findings | sources | latency s | calls | tokens in/out |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r['id']} | {r['type']} | {'yes' if r.get('passed') else 'NO'} | {r.get('confidence', '-')} | "
                     f"{r.get('findings', '-')} | {r.get('sources', '-')} | {r.get('latency_s', '-')} | "
                     f"{r.get('llm_calls', '-')} | {r.get('tokens_in', '-')}/{r.get('tokens_out', '-')} |")
    (HERE / "results.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n" + "\n".join(lines))
    print("\nSaved eval/results.json and eval/results.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())