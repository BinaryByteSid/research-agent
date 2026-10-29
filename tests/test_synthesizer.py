from research_agent.executor import ExecutionResult
from research_agent.llm import LLMError
from research_agent.schemas import Evidence, Finding, Plan, PlanStep, SynthDraft, ToolName
from research_agent.synthesizer import synthesize


class FakeLLM:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.user = result, error, None

    def structured(self, **kw):
        self.user = kw["user"]
        if self.error:
            raise self.error
        return self.result


def plan1():
    return Plan(steps=[PlanStep(id=1, sub_question="what is it", tool=ToolName.WEB_SEARCH, rationale="r")],
                success_criteria="x")


def result(evidence):
    return ExecutionResult(evidence=evidence, events=[], rounds=1, search_failures=0, coverage={1: 1})


def good(sid):
    return Evidence(source_id=sid, url=f"https://{sid}.com", title=sid, excerpt="useful text",
                    relevance_score=0.9, quality_score=0.5)


def test_only_kept_sources_are_sent_and_wrapped():
    dropped = Evidence(source_id="S2", url="https://bad.com", excerpt="evil", dropped_reason="blocked domain")
    llm = FakeLLM(SynthDraft(short_answer="An answer that is long enough.",
                             key_findings=[Finding(claim="A claim here", source_ids=["S1"])]))
    draft, used, _ = synthesize("q", plan1(), result([good("S1"), dropped]), llm)
    assert [e.source_id for e in used] == ["S1"]
    assert '<source id="S1"' in llm.user and "evil" not in llm.user
    assert draft is not None


def test_no_evidence_skips_llm():
    llm = FakeLLM(error=AssertionError("must not be called"))
    draft, used, _ = synthesize("q", plan1(), result([]), llm)
    assert draft is None and used == []


def test_llm_failure_returns_none_draft():
    draft, used, _ = synthesize("q", plan1(), result([good("S1")]), FakeLLM(error=LLMError("down")))
    assert draft is None and len(used) == 1