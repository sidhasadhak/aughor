"""Wave A1 — SQLite persistence for Automations and their run history.

Two tables in ``data/automations.db`` (env ``AUGHOR_AUTOMATIONS_DB``), following the
:mod:`aughor.monitors.store` idiom exactly — ``resolve_db_path`` so the suite can never touch the
live store (DATA-01), a module lock, and the forward-only migration framework (DATA-05) registered
from day one so the first additive column rides it instead of an ad-hoc ALTER.

  automations     — configuration rows; mutable (upsert by id)
  automation_runs — append-only tick history, INCLUDING ticks that did nothing

The second table is the point. ``monitor_alerts`` records only alerts that fired, so "did my monitor
run at 03:00, and if so why did nothing happen?" is unanswerable today. Every tick writes exactly one
row here with an ``outcome`` and a human ``reason``.

Composite fields (conditions, effects, per-effect outcomes) are stored as JSON columns rather than
child tables: they are always read as a whole automation, never queried across, and JSON keeps the
pydantic model the single source of truth for their shape.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Optional

from aughor.automations.models import Automation, AutomationRun
from aughor.db.migrations import Migration, run_migrations
from aughor.db.sqlite_util import resolve_db_path, tune
from aughor.util.time import now_iso_z

logger = logging.getLogger(__name__)

_DB_PATH = resolve_db_path("AUGHOR_AUTOMATIONS_DB", Path("data") / "automations.db")
_LOCK = threading.Lock()


# ── Schema ────────────────────────────────────────────────────────────────────

_DDL = """
CREATE TABLE IF NOT EXISTS automations (
    id                    TEXT PRIMARY KEY,
    conn_id               TEXT NOT NULL,
    name                  TEXT NOT NULL,
    description           TEXT NOT NULL DEFAULT '',
    conditions            TEXT NOT NULL DEFAULT '[]',
    condition_logic       TEXT NOT NULL DEFAULT 'all',
    effects               TEXT NOT NULL DEFAULT '[]',
    fallback_effect       TEXT,
    enabled               INTEGER NOT NULL DEFAULT 1,
    paused_until          TEXT,
    expires_at            TEXT,
    max_retries           INTEGER NOT NULL DEFAULT 1,
    retry_backoff_seconds REAL NOT NULL DEFAULT 30.0,
    created_at            TEXT NOT NULL DEFAULT '',
    updated_at            TEXT NOT NULL DEFAULT '',
    last_run_at           TEXT,
    last_status           TEXT
);

CREATE TABLE IF NOT EXISTS automation_runs (
    id               TEXT PRIMARY KEY,
    automation_id    TEXT NOT NULL,
    automation_name  TEXT NOT NULL DEFAULT '',
    conn_id          TEXT NOT NULL DEFAULT '',
    started_at       TEXT NOT NULL,
    finished_at      TEXT,
    duration_ms      INTEGER NOT NULL DEFAULT 0,
    outcome          TEXT NOT NULL,
    reason           TEXT NOT NULL DEFAULT '',
    conditions_fired TEXT NOT NULL DEFAULT '[]',
    effects          TEXT NOT NULL DEFAULT '[]',
    fallback_used    INTEGER NOT NULL DEFAULT 0,
    error            TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_auto_conn      ON automations (conn_id);
CREATE INDEX IF NOT EXISTS idx_runs_automation ON automation_runs (automation_id);
CREATE INDEX IF NOT EXISTS idx_runs_conn       ON automation_runs (conn_id);
CREATE INDEX IF NOT EXISTS idx_runs_time       ON automation_runs (started_at DESC);
"""

# Base DDL is conceptually v1; every later additive change is a versioned step (DATA-05).
_MIGRATIONS: list[Migration] = []


def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = tune(sqlite3.connect(str(_DB_PATH), check_same_thread=False))
    conn.row_factory = sqlite3.Row
    return conn


def _init_schema() -> None:
    with _LOCK:
        conn = _connect()
        try:
            conn.executescript(_DDL)
            conn.commit()
            run_migrations(conn, _MIGRATIONS, store="automations")
        finally:
            conn.close()


_init_schema()


# ── Automation CRUD ───────────────────────────────────────────────────────────

def _row_to_automation(row: sqlite3.Row) -> Automation:
    d = dict(row)
    d["enabled"] = bool(d["enabled"])
    d["conditions"] = json.loads(d["conditions"] or "[]")
    d["effects"] = json.loads(d["effects"] or "[]")
    d["fallback_effect"] = json.loads(d["fallback_effect"]) if d.get("fallback_effect") else None
    return Automation(**d)


def _automation_params(a: Automation) -> dict:
    p = a.model_dump()
    p["conditions"] = json.dumps([c.model_dump() for c in a.conditions])
    p["effects"] = json.dumps([e.model_dump() for e in a.effects])
    p["fallback_effect"] = json.dumps(a.fallback_effect.model_dump()) if a.fallback_effect else None
    p["enabled"] = int(a.enabled)
    return p


def list_automations(conn_id: Optional[str] = None,
                     enabled_only: bool = False) -> list[Automation]:
    clauses, params = [], []
    if conn_id:
        clauses.append("conn_id = ?"); params.append(conn_id)
    if enabled_only:
        clauses.append("enabled = 1")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _LOCK:
        conn = _connect()
        try:
            rows = conn.execute(
                f"SELECT * FROM automations {where} ORDER BY name", params
            ).fetchall()
            return [_row_to_automation(r) for r in rows]
        finally:
            conn.close()


def get_automation(automation_id: str) -> Optional[Automation]:
    with _LOCK:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT * FROM automations WHERE id = ?", (automation_id,)
            ).fetchone()
            return _row_to_automation(row) if row else None
        finally:
            conn.close()


def upsert_automation(automation: Automation) -> Automation:
    """Create or update an automation (full replace by id)."""
    now = now_iso_z()
    if not automation.created_at:
        automation = automation.model_copy(update={"created_at": now})
    automation = automation.model_copy(update={"updated_at": now})

    with _LOCK:
        conn = _connect()
        try:
            conn.execute("""
                INSERT INTO automations (
                    id, conn_id, name, description, conditions, condition_logic, effects,
                    fallback_effect, enabled, paused_until, expires_at, max_retries,
                    retry_backoff_seconds, created_at, updated_at, last_run_at, last_status
                ) VALUES (
                    :id, :conn_id, :name, :description, :conditions, :condition_logic, :effects,
                    :fallback_effect, :enabled, :paused_until, :expires_at, :max_retries,
                    :retry_backoff_seconds, :created_at, :updated_at, :last_run_at, :last_status
                )
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    description=excluded.description,
                    conditions=excluded.conditions,
                    condition_logic=excluded.condition_logic,
                    effects=excluded.effects,
                    fallback_effect=excluded.fallback_effect,
                    enabled=excluded.enabled,
                    paused_until=excluded.paused_until,
                    expires_at=excluded.expires_at,
                    max_retries=excluded.max_retries,
                    retry_backoff_seconds=excluded.retry_backoff_seconds,
                    updated_at=excluded.updated_at,
                    last_run_at=excluded.last_run_at,
                    last_status=excluded.last_status
            """, _automation_params(automation))
            conn.commit()
        finally:
            conn.close()
    return automation


def delete_automation(automation_id: str) -> bool:
    with _LOCK:
        conn = _connect()
        try:
            cur = conn.execute("DELETE FROM automations WHERE id = ?", (automation_id,))
            conn.execute("DELETE FROM automation_runs WHERE automation_id = ?", (automation_id,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()


def set_automation_enabled(automation_id: str, enabled: bool) -> Optional[Automation]:
    with _LOCK:
        conn = _connect()
        try:
            conn.execute(
                "UPDATE automations SET enabled = ?, updated_at = ? WHERE id = ?",
                (int(enabled), now_iso_z(), automation_id),
            )
            conn.commit()
        finally:
            conn.close()
    return get_automation(automation_id)


def pause_automation(automation_id: str, until_iso: Optional[str]) -> Optional[Automation]:
    """Mute until ``until_iso`` (or clear the mute with None). Distinct from disabling:
    a pause has an end, and the run history keeps saying *why* nothing fired."""
    with _LOCK:
        conn = _connect()
        try:
            conn.execute(
                "UPDATE automations SET paused_until = ?, updated_at = ? WHERE id = ?",
                (until_iso, now_iso_z(), automation_id),
            )
            conn.commit()
        finally:
            conn.close()
    return get_automation(automation_id)


def purge_connection(conn_id: str) -> int:
    """Delete every automation and run for a connection (catalog-delete cascade).
    Returns the total rows removed across both tables."""
    with _LOCK:
        conn = _connect()
        try:
            n = conn.execute("DELETE FROM automations WHERE conn_id = ?", (conn_id,)).rowcount
            n += conn.execute("DELETE FROM automation_runs WHERE conn_id = ?", (conn_id,)).rowcount
            conn.commit()
            return n
        finally:
            conn.close()


# ── Run history ───────────────────────────────────────────────────────────────

def _row_to_run(row: sqlite3.Row) -> AutomationRun:
    d = dict(row)
    d["fallback_used"] = bool(d["fallback_used"])
    d["conditions_fired"] = json.loads(d["conditions_fired"] or "[]")
    d["effects"] = json.loads(d["effects"] or "[]")
    return AutomationRun(**d)


def append_run(run: AutomationRun) -> AutomationRun:
    """Persist one tick. Idempotent — silent no-op on a duplicate id.

    Also advances the parent automation's ``last_run_at``/``last_status`` in the same
    transaction, so the summary on the config row can never disagree with its history.
    """
    p = run.model_dump()
    p["conditions_fired"] = json.dumps(run.conditions_fired)
    p["effects"] = json.dumps([e.model_dump() for e in run.effects])
    p["fallback_used"] = int(run.fallback_used)

    with _LOCK:
        conn = _connect()
        try:
            conn.execute("""
                INSERT OR IGNORE INTO automation_runs (
                    id, automation_id, automation_name, conn_id, started_at, finished_at,
                    duration_ms, outcome, reason, conditions_fired, effects, fallback_used, error
                ) VALUES (
                    :id, :automation_id, :automation_name, :conn_id, :started_at, :finished_at,
                    :duration_ms, :outcome, :reason, :conditions_fired, :effects,
                    :fallback_used, :error
                )
            """, p)
            conn.execute(
                "UPDATE automations SET last_run_at = ?, last_status = ? WHERE id = ?",
                (run.finished_at or run.started_at, run.outcome, run.automation_id),
            )
            conn.commit()
        finally:
            conn.close()

    # Surface the tick on the event spine so a panel sees it live — the same treatment
    # monitor alerts get. The row is the source of truth; a failed emit never blocks it.
    try:
        from aughor.kernel.ledger import Ledger
        Ledger.default().emit(
            "automation.run",
            {"automation_id": run.automation_id, "automation_name": run.automation_name,
             "outcome": run.outcome, "reason": run.reason[:200],
             "effects": [e.status for e in run.effects]},
            conn_id=run.conn_id,
        )
    except Exception:
        logger.debug("automation.run emit failed", exc_info=True)
    return run


def get_runs(automation_id: Optional[str] = None, conn_id: Optional[str] = None,
             limit: int = 100) -> list[AutomationRun]:
    clauses, params = [], []
    if automation_id:
        clauses.append("automation_id = ?"); params.append(automation_id)
    if conn_id:
        clauses.append("conn_id = ?"); params.append(conn_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _LOCK:
        conn = _connect()
        try:
            rows = conn.execute(
                f"SELECT * FROM automation_runs {where} ORDER BY started_at DESC LIMIT ?",
                [*params, limit],
            ).fetchall()
            return [_row_to_run(r) for r in rows]
        finally:
            conn.close()


def last_run(automation_id: str) -> Optional[AutomationRun]:
    """The most recent tick, or None. Used by ``source_change`` conditions to know what
    'since last time' means (A3) and by the UI to explain the current state."""
    runs = get_runs(automation_id=automation_id, limit=1)
    return runs[0] if runs else None
