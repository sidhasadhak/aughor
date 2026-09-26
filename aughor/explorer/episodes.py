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
        self._steps = 0
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._path = _DATA_DIR / f"episodes_{connection_id}.jsonl"

    def add(self, think: str, sql: str, observation: str) -> None:
        """Append one (think, sql, observation) turn — to this file, and as one `step`
        event on the session log (TJ-2), so an explorer run leaves the same record every
        tool loop leaves and `trajectory_of` walks it. The file stays for its readers
        (the exploration router's episode pages) until they read the log instead."""
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
        self._steps += 1
        self._emit_step(think, sql, observation)

    def _emit_step(self, think: str, sql: str, observation: str) -> None:
        """The work-artifact fields always (the statement, the phase, the episode); the
        model's reasoning and what it observed only under an open capture window — the
        lawful lane, as `tool_loop._emit_step` keeps it. No bound trace (an exploration
        run is a job and binds its job id), nothing written."""
        try:
            from aughor.obs import prompt_window, session_log
            payload = {
                "index": self._steps, "site": "explorer", "tool": "explorer.step",
                "ok": True, "sql": str(sql or "")[:4000], "error": "", "guards": [],
                "result_chars": len(observation or ""), "phase": self.phase,
                "episode_id": self.episode_id, "captured": False,
            }
            if prompt_window.active():
                payload["captured"] = True
                payload["arguments"] = str(think or "")[:2000]
                payload["result_excerpt"] = str(observation or "")[:400]
            session_log.emit(session_log.STEP, name="explorer.step", ok=True,
                             conn_id=self.connection_id or None, payload=payload)
        except Exception as exc:  # noqa: BLE001 — observation never fails the observed
            from aughor.kernel.errors import tolerate
            tolerate(exc, "an explorer step that could not be logged still happened",
                     counter="explorer.step_event")
