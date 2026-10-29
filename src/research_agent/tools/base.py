"""Tool framework: timeout, retry with backoff, output validation, tracing data.

Contract: Tool.run() NEVER raises. It returns a ToolResult (ok=True with
validated data, or ok=False with an error string). The executor can therefore
continue with partial results instead of crashing on one bad tool call.
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional, Type

from pydantic import BaseModel, ValidationError

from ..config import Settings, settings as default_settings

log = logging.getLogger(__name__)


class ToolError(Exception):
    """Permanent failure: retrying will not help (bad key, 404, blocked URL)."""


class TransientToolError(ToolError):
    """Temporary failure worth retrying: timeout, connection error, 429, 5xx."""


@dataclass
class ToolResult:
    tool: str
    ok: bool
    data: Optional[BaseModel] = None
    error: Optional[str] = None
    latency_s: float = 0.0
    attempts: int = 0
    fallback_errors: list[str] = field(default_factory=list)  # errors from providers tried before this one

    def trace(self) -> dict:
        """Compact dict for structured logging (no payload, just metadata)."""
        return {
            "tool": self.tool,
            "ok": self.ok,
            "error": self.error,
            "latency_s": round(self.latency_s, 3),
            "attempts": self.attempts,
            "fallback_errors": self.fallback_errors,
        }


class Tool(ABC):
    name: str
    output_model: Type[BaseModel]

    def __init__(self, cfg: Settings = default_settings):
        self.cfg = cfg

    @abstractmethod
    def _execute(self, **kwargs: Any) -> Any:
        """Do the actual work. Raise TransientToolError or ToolError on failure."""

    def run(self, **kwargs: Any) -> ToolResult:
        start = time.monotonic()
        max_attempts = 1 + self.cfg.tool_max_retries
        error = "unknown error"
        attempts = 0

        for attempt in range(1, max_attempts + 1):
            attempts = attempt
            try:
                raw = self._execute(**kwargs)
                data = self.output_model.model_validate(raw)  # malformed output -> ValidationError
                return ToolResult(
                    tool=self.name, ok=True, data=data,
                    latency_s=time.monotonic() - start, attempts=attempt,
                )
            except TransientToolError as e:
                error = f"transient: {e}"
                log.warning("%s attempt %d/%d failed: %s", self.name, attempt, max_attempts, e)
                if attempt < max_attempts:
                    time.sleep(min(self.cfg.tool_backoff_base_s * 2 ** (attempt - 1), 8.0))
            except ToolError as e:
                error = str(e)
                break  # permanent: do not retry
            except ValidationError as e:
                error = f"malformed output: {str(e)[:300]}"
                break
            except Exception as e:  # last line of defence: a tool bug must not kill the run
                error = f"unexpected {type(e).__name__}: {e}"
                log.exception("%s crashed", self.name)
                break

        return ToolResult(
            tool=self.name, ok=False, error=error,
            latency_s=time.monotonic() - start, attempts=attempts,
        )


class FallbackTool:
    """Try providers in order; the first successful result wins.

    Presents the same run() interface as Tool, so the executor does not need
    to know that a fallback exists.
    """

    def __init__(self, name: str, tools: list[Tool]):
        self.name = name
        self.tools = tools

    def run(self, **kwargs: Any) -> ToolResult:
        start = time.monotonic()
        errors: list[str] = []
        total_attempts = 0

        for tool in self.tools:
            res = tool.run(**kwargs)
            total_attempts += res.attempts
            if res.ok:
                return ToolResult(
                    tool=self.name, ok=True, data=res.data,
                    latency_s=time.monotonic() - start,
                    attempts=total_attempts, fallback_errors=errors,
                )
            errors.append(f"{tool.name}: {res.error}")

        return ToolResult(
            tool=self.name, ok=False, error=" | ".join(errors),
            latency_s=time.monotonic() - start, attempts=total_attempts,
            fallback_errors=errors,
        )