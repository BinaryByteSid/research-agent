from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from research_agent.config import Settings
from research_agent.llm import LLMClient, LLMError


class Toy(BaseModel):
    name: str
    count: int


def fake_response(content: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50),
    )


class FakeOpenAI:
    """Returns queued responses in order; records every call."""

    def __init__(self, outputs: list[str]):
        self.outputs = list(outputs)
        self.calls = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls += 1
        return fake_response(self.outputs.pop(0))


def make_client(outputs):
    fake = FakeOpenAI(outputs)
    return LLMClient(cfg=Settings(), client=fake), fake


def test_valid_output_first_try():
    llm, fake = make_client(['{"name": "a", "count": 3}'])
    result = llm.structured(model="gpt-4o-mini", system="s", user="u", schema=Toy)
    assert result.count == 3
    assert fake.calls == 1
    assert llm.usage.repairs == 0


def test_repair_succeeds_on_second_try():
    llm, fake = make_client(['{"name": "a", "count": "not-a-number"}', '{"name": "a", "count": 7}'])
    result = llm.structured(model="gpt-4o-mini", system="s", user="u", schema=Toy)
    assert result.count == 7
    assert fake.calls == 2
    assert llm.usage.repairs == 1


def test_repair_exhausted_raises():
    llm, _ = make_client(["not json at all", "still not json"])
    with pytest.raises(LLMError):
        llm.structured(model="gpt-4o-mini", system="s", user="u", schema=Toy)


def test_cost_is_tracked():
    llm, _ = make_client(['{"name": "a", "count": 1}'])
    llm.structured(model="gpt-4o-mini", system="s", user="u", schema=Toy)
    assert llm.usage.prompt_tokens == 100
    assert llm.usage.completion_tokens == 50
    assert llm.usage.cost_usd > 0
def test_fenced_json_is_accepted():
    llm, _ = make_client(['```json\n{"name": "a", "count": 2}\n```'])
    result = llm.structured(model="m", system="s", user="u", schema=Toy)
    assert result.count == 2