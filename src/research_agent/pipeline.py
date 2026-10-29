"""One entry point that wires planner -> executor -> synthesizer -> validator."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .config import Settings, settings as default_settings
from .executor import Executor
from .llm import LLMClient, LLMConfigError
from .planner import make_plan
from .schemas import Confidence, ConfidenceLevel, FinalAnswer, QueryStatus
from .synthesizer import synthesize
from .tracing import RunTrace
from .validator import build_final_answer


@dataclass
class RunOutput:
    answer: FinalAnswer
    run_id: str
    trace_path: str
    plan_status: str
    latency_s: float
    usage: dict


def _not_researched(question: str, plan) -> FinalAnswer:
    if plan.status == QueryStatus.NEEDS_CLARIFICATION:
        msg, step = plan.clarification_question, "Reply with the missing detail and run again."
    else:
        msg, step = plan.refusal_reason, "Rephrase the question as a researchable topic."
    return FinalAnswer(
        question=question,
        short_answer=msg or "This question could not be researched.",
        key_findings=[], sources=[],
        confidence=Confidence(level=ConfidenceLevel.LOW, score=0.0,
                              reasons=[f"No research performed (planner status: {plan.status.value})"]),
        limitations=["No web research was performed for this query."],
        next_steps=[step],
    )


def run_research(
    question: str,
    llm: Optional[LLMClient] = None,
    search_tool=None,
    fetch_tool=None,
    cfg: Settings = default_settings,
) -> RunOutput:
    trace = RunTrace(question, cfg.log_dir)
    llm = llm or LLMClient(cfg)
    try:
        plan, used_fallback = make_plan(question, llm, cfg)
        trace.event("plan", used_fallback=used_fallback, plan=plan.model_dump(mode="json"))

        if plan.status != QueryStatus.OK:
            answer = _not_researched(question, plan)
        else:
            if search_tool is None:
                from .tools.web_search import build_search_tool
                search_tool = build_search_tool(cfg)
            if fetch_tool is None:
                from .tools.page_fetch import PageFetchTool
                fetch_tool = PageFetchTool(cfg)

            result = Executor(search_tool, fetch_tool, llm, cfg).run(question, plan)
            for e in result.events:
                fields = {k: v for k, v in e.items() if k != "event"}
                trace.event(e["event"], **fields)

            draft, used, err = synthesize(question, plan, result, llm, cfg)
            trace.event("synthesis", ok=draft is not None, sources_used=len(used), error=err or None)
            answer = build_final_answer(question, plan, result, used, draft, synth_error=err, cfg=cfg)

        trace.event(
            "final",
            confidence=answer.confidence.model_dump(mode="json"),
            findings=len(answer.key_findings), sources=len(answer.sources),
            usage=llm.usage.as_dict(), latency_s=trace.elapsed(),
        )
        return RunOutput(answer, trace.run_id, str(trace.path), plan.status.value,
                         trace.elapsed(), llm.usage.as_dict())
    except LLMConfigError as e:
        trace.event("error", kind="config", message=str(e))
        raise
    except Exception as e:  # unexpected bug: record it, then let the CLI show it
        trace.event("error", kind="unexpected", type=type(e).__name__, message=str(e)[:300])
        raise