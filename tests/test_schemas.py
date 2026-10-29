import pytest
from pydantic import ValidationError

from research_agent.schemas import (
    Plan, PlanStep, ToolName, QueryStatus, Finding, Evidence,
)


def test_valid_plan():
    plan = Plan(
        steps=[PlanStep(id=1, sub_question="What is Qdrant?", tool=ToolName.WEB_SEARCH, rationale="need facts")],
        success_criteria="covers top 3 DBs",
    )
    assert plan.status == QueryStatus.OK


def test_ok_plan_without_steps_fails():
    with pytest.raises(ValidationError):
        Plan(status=QueryStatus.OK, steps=[])


def test_clarification_requires_question():
    with pytest.raises(ValidationError):
        Plan(status=QueryStatus.NEEDS_CLARIFICATION)


def test_finding_requires_a_source():
    with pytest.raises(ValidationError):
        Finding(claim="Qdrant is written in Rust", source_ids=[])


def test_evidence_kept_property():
    e = Evidence(source_id="S1", url="https://x.com", excerpt="text")
    assert e.kept
    e.dropped_reason = "low relevance"
    assert not e.kept