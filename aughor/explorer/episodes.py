"""
SkyRL-SQL episode collector.

Writes (think, sql, observation) turns to data/episodes_{connection_id}.jsonl
so they can be used as training data for fine-tuning.

Each entry is one JSONL line:
  {"episode_id": "...", "connection_id": "...", "phase": "...",
   "ts": 1234567890.0, "think": "...", "sql": "...", "observation": "..."}

The episode_id groups related turns within one phase.  A new episode_id is
assigned each time EpisodeCollector is constructed (i.e. per exploration run).
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from aughor.db.sqlite_util import resolve_db_path

# WP-4 — env override (AUGHOR_EPISODES_DIR) for test isolation; the episodes JSONL
# files were written into the live data/ dir with no override (a non-hermetic hole).
_DATA_DIR = resolve_db_path("AUGHOR_EPISODES_DIR", Path("data"))


def episodes_dir() -> Path:
    """The directory episode JSONL files live in (honours AUGHOR_EPISODES_DIR).

    The single source of truth for both writers (EpisodeCollector) and the readers in
    the exploration router / explorer agent, so a redirected dir keeps them consistent.
    """
    return _DATA_DIR


class EpisodeCollector:
    def __init__(self, connection_id: str, phase: str = "exploration") -> None:
        self.connection_id = connection_id
        self.phase = phase
        self.episode_id = str(uuid.uuid4())
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._path = _DATA_DIR / f"episodes_{connection_id}.jsonl"

    def add(self, think: str, sql: str, observation: str) -> None:
        """Append one (think, sql, observation) turn."""
        entry = {
            "episode_id": self.episode_id,
            "connection_id": self.connection_id,
            "phase": self.phase,
            "ts": time.time(),
            "think": think,
            "sql": sql,
            "observation": observation,
        }
        try:
            with self._path.open("a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass
