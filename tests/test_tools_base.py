from pydantic import BaseModel

from research_agent.config import Settings
from research_agent.tools.base import FallbackTool, Tool, ToolError, TransientToolError

FAST = Settings(tool_max_retries=2, tool_backoff_base_s=0.0)


class Out(BaseModel):
    value: int


class Flaky(Tool):
    """Fails transiently `fail_times`, then succeeds."""
    name = "flaky"
    output_model = Out

    def __init__(self, fail_times=0, cfg=FAST):
        super().__init__(cfg)
        self.fail_times = fail_times
        self.calls = 0

    def _execute(self):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise TransientToolError("boom")
        return {"value": 1}


class Permanent(Tool):
    name = "permanent"
    output_model = Out

    def __init__(self):
        super().__init__(FAST)
        self.calls = 0

    def _execute(self):
        self.calls += 1
        raise ToolError("bad key")


class Malformed(Tool):
    name = "malformed"
    output_model = Out

    def _execute(self):
        return {"value": "not-an-int"}


def test_retries_then_succeeds():
    t = Flaky(fail_times=2)
    res = t.run()
    assert res.ok and res.attempts == 3


def test_gives_up_after_retries():
    t = Flaky(fail_times=10)
    res = t.run()
    assert not res.ok and t.calls == 3 and "transient" in res.error


def test_permanent_error_not_retried():
    t = Permanent()
    res = t.run()
    assert not res.ok and t.calls == 1


def test_malformed_output_is_caught():
    res = Malformed(FAST).run()
    assert not res.ok and "malformed" in res.error


def test_fallback_uses_second_tool():
    fb = FallbackTool("search", [Permanent(), Flaky(fail_times=0)])
    res = fb.run()
    assert res.ok and len(res.fallback_errors) == 1


def test_fallback_all_fail():
    fb = FallbackTool("search", [Permanent(), Malformed(FAST)])
    res = fb.run()
    assert not res.ok and "permanent" in res.error and "malformed" in res.error