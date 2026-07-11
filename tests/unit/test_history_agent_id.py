"""Slice 1 of the MLflow-underneath Agent Workspace (Databricks-OSS study E1/E5):
the ``agent_id`` column on the ``investigations`` run row.

Before this, the active user-agent (persona) lived only in the LangGraph
checkpoint, so per-agent run history was not joinable in the history store.
These tests pin: the additive Migration(3) adds the column, is idempotent, and
backfills existing rows to ''; create/get round-trips the value; and it surfaces
in ``list_investigations``.
"""
from __future__ import annotations

import sqlite3

import pytest

from aughor.db import history
from aughor.db.migrations import run_migrations
from aughor.db.sqlite_util import tune


@pytest.fixture()
def hist_db(tmp_path, monkeypatch):
    """Point the history store at an isolated temp DB (never the live data/ store)."""
    monkeypatch.setattr(history, "_DB_PATH", str(tmp_path / "history.db"))
    return tmp_path / "history.db"


def _columns(path) -> set[str]:
    c = sqlite3.connect(str(path))
    try:
        return {r[1] for r in c.execute("PRAGMA table_info(investigations)").fetchall()}
    finally:
        c.close()


def test_fresh_db_has_agent_id_column(hist_db):
    # Any write path calls _ensure_schema, which runs migrations on a fresh DB.
    history.create_investigation("q", "conn1")
    assert "agent_id" in _columns(hist_db)


def test_create_and_get_round_trips_agent_id(hist_db):
    inv = history.create_investigation("why did churn spike", "conn1", agent_id="churn-analyst")
    row = history.get_investigation(inv)
    assert row is not None
    assert row["agent_id"] == "churn-analyst"


def test_agent_id_defaults_to_empty(hist_db):
    inv = history.create_investigation("no persona", "conn1")
    row = history.get_investigation(inv)
    assert row is not None
    assert row["agent_id"] == ""


def test_list_investigations_surfaces_agent_id(hist_db):
    history.create_investigation("bound run", "conn1", agent_id="finance")
    rows = history.list_investigations()
    inv_rows = [r for r in rows if r.get("kind") == "investigation"]
    assert len(inv_rows) == 1
    assert inv_rows[0]["agent_id"] == "finance"


def test_migration_upgrades_legacy_db_and_backfills_empty(hist_db):
    """The live-DB upgrade path: a DB already at user_version=2 (agent_id absent,
    a pre-existing row) gains the column with the old row backfilled to ''."""
    c = tune(sqlite3.connect(str(hist_db)))
    c.execute(
        """CREATE TABLE investigations (
            id TEXT PRIMARY KEY, question TEXT NOT NULL, connection_id TEXT NOT NULL,
            started_at TEXT NOT NULL, completed_at TEXT, status TEXT DEFAULT 'running',
            hypothesis_count INTEGER DEFAULT 0, query_count INTEGER DEFAULT 0,
            headline TEXT, report_json TEXT, hypotheses_json TEXT, query_history_json TEXT,
            kind TEXT DEFAULT 'investigation', session_id TEXT, canvas_id TEXT,
            origin_insight_id TEXT, org_id TEXT NOT NULL DEFAULT 'default')"""
    )
    c.execute("PRAGMA user_version = 2")
    c.execute(
        "INSERT INTO investigations (id, question, connection_id, started_at) VALUES (?,?,?,?)",
        ("legacy01", "old question", "conn1", "2026-01-01T00:00:00Z"),
    )
    c.commit()
    assert "agent_id" not in _columns(hist_db)

    run_migrations(c, history._MIGRATIONS, store="history")
    c.close()

    assert "agent_id" in _columns(hist_db)
    row = history.get_investigation("legacy01")
    assert row is not None and row["agent_id"] == ""


def test_migration_is_idempotent(hist_db):
    history.create_investigation("q", "conn1")  # builds + migrates to v3
    c = tune(sqlite3.connect(str(hist_db)))
    before = c.execute("PRAGMA user_version").fetchone()[0]
    run_migrations(c, history._MIGRATIONS, store="history")  # no-op second pass
    after = c.execute("PRAGMA user_version").fetchone()[0]
    c.close()
    assert before == after == 3
    assert "agent_id" in _columns(hist_db)
