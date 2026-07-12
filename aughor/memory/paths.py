"""Resolved paths for the agent procedural-memory JSON stores.

WP-4 — ``agent_runs.json`` (per-run reflection signals) and ``learned_actions.json``
(crystallized skills) were hardcoded to the live ``data/`` dir with no env override, so
the suite wrote a developer's real files whenever a memory path was exercised. These
resolve ``AUGHOR_MEMORY_DIR`` (default ``data``) once, so the test conftest can redirect
them at a temp dir — and on-prem operators get per-store path control for free.
"""
from __future__ import annotations

from pathlib import Path

from aughor.db.sqlite_util import resolve_db_path


def memory_dir() -> Path:
    return resolve_db_path("AUGHOR_MEMORY_DIR", Path("data"))


def agent_runs_path() -> str:
    return str(memory_dir() / "agent_runs.json")


def learned_actions_path() -> str:
    return str(memory_dir() / "learned_actions.json")
