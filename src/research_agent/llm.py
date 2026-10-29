"""Thin LLM wrapper: structured output, retry, schema repair, cost tracking.

Everything else in the project calls LLMClient.structured(...) and gets back
a validated Pydantic object, or an LLMError. No raw strings leak out.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Optional, Type, TypeVar

from openai import (
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
    OpenAI,
    RateLimitError,
)
from pydantic import BaseModel, ValidationError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .config import MODEL_PRICING, Settings, settings as default_settings

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# Errors worth retrying: network blips, rate limits, server-side 5xx.
TRANSIENT_ERRORS = (APITimeoutError, APIConnectionError, RateLimitError, InternalServerError)


class LLMError(Exception):
    """Raised when the LLM cannot produce a valid result after retries/repairs."""


@dataclass
class Usage:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    repairs: int = 0   # how many schema-repair re-prompts were needed

    def as_dict(self) -> dict:
        return {
            "calls": self.calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "repairs": self.repairs,
        }


class LLMClient:
    def __init__(self, cfg: Settings = default_settings, client: Optional[OpenAI] = None):
        self.cfg = cfg
        # max_retries=0 on the SDK: we own retry behaviour via tenacity, so it is visible and testable.
        self.client = client or OpenAI(
            api_key=cfg.openai_api_key, timeout=cfg.llm_timeout_s, max_retries=0
        )
        self.usage = Usage()

    # ---------- low level ----------

    def _complete(self, model: str, messages: list[dict]) -> str:
        """One chat completion with exponential-backoff retry on transient errors."""

        @retry(
            retry=retry_if_exception_type(TRANSIENT_ERRORS),
            stop=stop_after_attempt(self.cfg.llm_max_retries),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            reraise=True,
        )
        def _call():
            return self.client.chat.completions.create(
                model=model,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0,  # determinism: same input -> as close to same output as possible
            )

        try:
            resp = _call()
        except TRANSIENT_ERRORS as e:
            raise LLMError(f"LLM call failed after retries: {e}") from e

        self._track(model, resp)
        return resp.choices[0].message.content or ""

    def _track(self, model: str, resp) -> None:
        u = getattr(resp, "usage", None)
        if u is None:
            return
        self.usage.calls += 1
        self.usage.prompt_tokens += u.prompt_tokens
        self.usage.completion_tokens += u.completion_tokens
        price_in, price_out = MODEL_PRICING.get(model, (0.0, 0.0))
        if model not in MODEL_PRICING:
            log.warning("No pricing for model %s; cost will be under-reported", model)
        self.usage.cost_usd += (
            u.prompt_tokens * price_in + u.completion_tokens * price_out
        ) / 1_000_000

    # ---------- public API ----------

    def structured(
        self, *, model: str, system: str, user: str, schema: Type[T]
    ) -> T:
        """Call the LLM and return a validated `schema` instance.

        On invalid JSON or schema violation, re-prompt with the error message
        (up to cfg.llm_max_repairs times), then raise LLMError.
        """
        schema_json = json.dumps(schema.model_json_schema())
        full_system = (
            f"{system}\n\n"
            "Respond with ONLY a single JSON object that conforms to this JSON Schema. "
            "No prose, no markdown fences.\n"
            f"JSON Schema:\n{schema_json}"
        )
        messages = [
            {"role": "system", "content": full_system},
            {"role": "user", "content": user},
        ]

        last_error = ""
        for attempt in range(self.cfg.llm_max_repairs + 1):
            raw = self._complete(model, messages)
            try:
                return schema.model_validate_json(raw)
            except (ValidationError, ValueError) as e:
                last_error = str(e)
                log.warning("Schema violation (attempt %d): %s", attempt + 1, last_error[:300])
                if attempt < self.cfg.llm_max_repairs:
                    self.usage.repairs += 1
                    messages.append({"role": "assistant", "content": raw})
                    messages.append({
                        "role": "user",
                        "content": (
                            "Your previous output failed validation with this error:\n"
                            f"{last_error}\n"
                            "Return a corrected JSON object that fixes it."
                        ),
                    })

        raise LLMError(f"Output did not match schema after repair: {last_error[:500]}")