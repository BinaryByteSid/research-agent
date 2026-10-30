"""Non-agentic baseline: one LLM call, no tools, no retrieval, no citations."""
import time

from pydantic import BaseModel, Field

from research_agent.config import settings
from research_agent.llm import LLMClient, LLMError


class BaselineAnswer(BaseModel):
    short_answer: str
    key_findings: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)


SYSTEM = "You are a research assistant. Answer the question as well as you can."


def run_baseline(question: str) -> dict:
    llm = LLMClient(settings)
    start = time.monotonic()
    try:
        ans = llm.structured(model=settings.synth_model, system=SYSTEM, user=question, schema=BaselineAnswer)
        err = None
    except LLMError as e:
        ans, err = None, str(e)[:200]
    return {
        "answer": ans.model_dump() if ans else None,
        "error": err,
        "latency_s": round(time.monotonic() - start, 2),
        "usage": llm.usage.as_dict(),
        "sources_cited": 0,
    }