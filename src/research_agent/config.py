"""Central configuration. Every tunable lives here, not scattered in modules."""
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    # --- API keys ---
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    tavily_api_key: str = os.getenv("TAVILY_API_KEY", "")

    # --- Models: cheap for planning/reflection, stronger for synthesis ---
    planner_model: str = os.getenv("PLANNER_MODEL", "gpt-4o-mini")
    synth_model: str = os.getenv("SYNTH_MODEL", "gpt-4o")

    # --- Timeouts and retries ---
    llm_timeout_s: float = 60.0
    llm_max_retries: int = 3          # transient errors only (timeout, 429, 5xx)
    llm_max_repairs: int = 1          # re-prompts after schema violation
    tool_timeout_s: float = 15.0
    tool_max_retries: int = 2

    # --- Agent loop limits (cost and latency control) ---
    max_rounds: int = 2               # initial pass + at most one follow-up
    max_results_per_search: int = 5
    max_pages_to_fetch: int = 6       # per round
    max_excerpt_chars: int = 3000     # per source sent to the LLM
    max_page_bytes: int = 1_000_000   # download size cap

    # --- Filtering thresholds ---
    min_relevance: float = 0.3
    min_quality: float = 0.2

    # --- Confidence guardrail ---
    min_confidence_to_answer: float = 0.25   # below this -> refuse / hedge

    # --- Paths ---
    log_dir: Path = ROOT / "logs"
    cache_dir: Path = ROOT / ".cache"

    # --- Domain lists for source quality scoring (starter lists, extend later) ---
    preferred_domains: tuple[str, ...] = (
        "github.com", "docs.", "arxiv.org", "readthedocs.io",
        "wikipedia.org", "openai.com", "anthropic.com",
    )
    blocked_domains: tuple[str, ...] = (
        "pinterest.com", "quora.com", "facebook.com", "instagram.com",
    )


# Price per 1M tokens (input, output) in USD.
# These are approximate. Check your provider's pricing page and update them.
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
}


settings = Settings()