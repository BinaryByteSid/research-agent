from research_agent.config import Settings
from research_agent.llm import LLMError
from research_agent.planner import make_plan
from research_agent.schemas import Plan, PlanStep, QueryStatus, ToolName


class FakeLLM:
    def __init__(self, result=None, error=None):
        self.result, self.error = result, error
        self.last_user = None

    def structured(self, *, model, system, user, schema):
        self.last_user = user
        if self.error:
            raise self.error
        return self.result


def ok_plan(first_tool=ToolName.WEB_SEARCH):
    return Plan(
        steps=[
            PlanStep(id=7, sub_question="What is Qdrant?", tool=first_tool, rationale="r"),
            PlanStep(id=9, sub_question="Read Qdrant docs", tool=ToolName.PAGE_FETCH, rationale="r"),
        ],
        success_criteria="covers 3 DBs",
    )


def test_ok_plan_is_renumbered():
    plan, fb = make_plan("compare vector dbs", FakeLLM(ok_plan()))
    assert not fb
    assert [s.id for s in plan.steps] == [1, 2]


def test_first_step_forced_to_search():
    plan, _ = make_plan("q", FakeLLM(ok_plan(first_tool=ToolName.PAGE_FETCH)))
    assert plan.steps[0].tool == ToolName.WEB_SEARCH


def test_empty_question_asks_for_clarification_without_llm_call():
    llm = FakeLLM(error=AssertionError("LLM should not be called"))
    plan, _ = make_plan("   ", llm)
    assert plan.status == QueryStatus.NEEDS_CLARIFICATION


def test_clarification_passes_through():
    p = Plan(status=QueryStatus.NEEDS_CLARIFICATION, clarification_question="Which ones?")
    plan, _ = make_plan("compare the best ones", FakeLLM(p))
    assert plan.status == QueryStatus.NEEDS_CLARIFICATION and plan.steps == []


def test_llm_failure_uses_fallback_plan():
    plan, fb = make_plan("compare vector dbs", FakeLLM(error=LLMError("down")))
    assert fb and plan.status == QueryStatus.OK and len(plan.steps) == 1


def test_question_is_wrapped_and_truncated():
    llm = FakeLLM(ok_plan())
    make_plan("x" * 5000, llm)
    assert "<question>" in llm.last_user and len(llm.last_user) < 1300