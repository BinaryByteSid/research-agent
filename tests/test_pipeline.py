import json

from research_agent.config import Settings
from research_agent.pipeline import run_research
from research_agent.schemas import Plan, QueryStatus


class FakeLLM:
    def __init__(self, result):
        self.result = result
        self.usage = type("U", (), {"as_dict": lambda s: {"calls": 1, "prompt_tokens": 1,
                                                          "completion_tokens": 1, "cost_usd": 0, "repairs": 0}})()

    def structured(self, **kw):
        return self.result


class Boom:
    def run(self, **kw):
        raise AssertionError("tools must not run for non-researchable queries")


def test_clarification_skips_research_and_writes_trace(tmp_path):
    cfg = Settings(log_dir=tmp_path)
    plan = Plan(status=QueryStatus.NEEDS_CLARIFICATION, clarification_question="Compare what?")
    out = run_research("compare the best ones", llm=FakeLLM(plan), search_tool=Boom(), fetch_tool=Boom(), cfg=cfg)
    assert out.answer.short_answer == "Compare what?"
    assert out.answer.key_findings == []
    events = [json.loads(l)["event"] for l in open(out.trace_path, encoding="utf-8")]
    assert events[0] == "run_start" and "plan" in events and events[-1] == "final"


def test_refusal_is_reported(tmp_path):
    cfg = Settings(log_dir=tmp_path)
    plan = Plan(status=QueryStatus.REFUSED, refusal_reason="Not a researchable question.")
    out = run_research("asdf", llm=FakeLLM(plan), search_tool=Boom(), fetch_tool=Boom(), cfg=cfg)
    assert out.plan_status == "refused" and out.answer.confidence.score == 0.0