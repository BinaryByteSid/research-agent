"""Structured JSON-lines trace: one file per run, one event per line.

Events: run_start, plan, search, fetch, source_kept, source_dropped, reflection,
synthesis, final, error. Payloads are metadata (no full page text) to keep logs small.
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class RunTrace:
    def __init__(self, question: str, log_dir: Path):
        self.run_id = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        log_dir.mkdir(parents=True, exist_ok=True)
        self.path = log_dir / f"{self.run_id}.jsonl"
        self._start = time.monotonic()
        self.event("run_start", question=question[:500])

    def event(self, name: str, **fields: Any) -> None:
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "run_id": self.run_id,
            "event": name,
            "t_s": round(time.monotonic() - self._start, 3),
            **fields,
        }
        try:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, default=str) + "\n")
        except OSError:
            pass  # tracing must never break a run

    def elapsed(self) -> float:
        return round(time.monotonic() - self._start, 3)