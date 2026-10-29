"""All data contracts for the research agent live here.

Keeping every Pydantic model in one file gives us:
- one place to read to understand the system's data flow
- deterministic, validated structure at every stage boundary
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------- Planning ----------

class ToolName(str, Enum):
    WEB_SEARCH = "web_search"
    PAGE_FETCH = "page_fetch"


class QueryStatus(str, Enum):
    OK = "ok"                                    # proceed with research
    NEEDS_CLARIFICATION = "needs_clarification"  # ambiguous query
    REFUSED = "refused"                          # nonsense / unsafe / out of scope


class PlanStep(BaseModel):
    id: int
    sub_question: str = Field(min_length=3)
    tool: ToolName
    rationale: str = Field(description="Why this tool for this sub-question")


class Plan(BaseModel):
    status: QueryStatus = QueryStatus.OK
    clarification_question: Optional[str] = None
    refusal_reason: Optional[str] = None
    steps: list[PlanStep] = Field(default_factory=list, max_length=6)
    success_criteria: str = Field(
        default="", description="What a good answer must contain"
    )

    @model_validator(mode="after")
    def check_consistency(self) -> "Plan":
        if self.status == QueryStatus.OK and not self.steps:
            raise ValueError("status=ok requires at least one step")
        if self.status == QueryStatus.NEEDS_CLARIFICATION and not self.clarification_question:
            raise ValueError("needs_clarification requires clarification_question")
        if self.status == QueryStatus.REFUSED and not self.refusal_reason:
            raise ValueError("refused requires refusal_reason")
        return self


# ---------- Evidence (what tools return, after filtering) ----------

class Evidence(BaseModel):
    source_id: str = Field(description="Stable ID like S1, S2 used for citations")
    url: str
    title: str = ""
    excerpt: str
    sub_question_id: Optional[int] = None
    relevance_score: float = Field(default=0.0, ge=0.0, le=1.0)
    quality_score: float = Field(default=0.0, ge=0.0, le=1.0)
    injection_flagged: bool = False
    dropped_reason: Optional[str] = None  # None means the source was kept

    @property
    def kept(self) -> bool:
        return self.dropped_reason is None


# ---------- Final answer ----------

class ConfidenceLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Confidence(BaseModel):
    level: ConfidenceLevel
    score: float = Field(ge=0.0, le=1.0)
    reasons: list[str] = Field(default_factory=list)


class Finding(BaseModel):
    claim: str = Field(min_length=5)
    source_ids: list[str] = Field(
        min_length=1, description="Every claim must cite at least one source"
    )


class Source(BaseModel):
    source_id: str
    url: str
    title: str = ""


class FinalAnswer(BaseModel):
    question: str
    short_answer: str
    key_findings: list[Finding]
    sources: list[Source]
    confidence: Confidence
    limitations: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)

# ---------- Tool outputs ----------

class SearchHit(BaseModel):
    url: str
    title: str = ""
    snippet: str = ""
    score: Optional[float] = None

    @field_validator("url")
    @classmethod
    def must_be_http(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("url must start with http:// or https://")
        return v


class SearchOutput(BaseModel):
    query: str
    provider: str
    hits: list[SearchHit]


class PageContent(BaseModel):
    url: str
    title: str = ""
    text: str = Field(min_length=40)  # near-empty pages count as malformed
    content_type: str = ""
    truncated: bool = False
# ---------- Reflection ----------

class FollowUp(BaseModel):
    sub_question_id: Optional[int] = None
    query: str = Field(min_length=3)


class Reflection(BaseModel):
    covered: bool
    follow_ups: list[FollowUp] = Field(default_factory=list)
    notes: str = ""
# ---------- Synthesizer draft (what the LLM writes; confidence is added by code) ----------

class SynthDraft(BaseModel):
    short_answer: str = Field(min_length=10)
    key_findings: list[Finding] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)