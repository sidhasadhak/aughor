"""Persistence for agent alert rules and the alerts they fire.

Two tables in ``data/agent_alerts.db``:
  agent_alert_rules  — configuration; mutable (upsert by id)
  agent_alert_events — append-only fired alerts; ``acknowledged`` and the delivery
                       stamp are the only fields that change after the write

A separate store from ``monitors.db`` on purpose. A monitor watches a warehouse metric on
a connection; a rule here watches the fleet, has no ``conn_id`` at all, and is scoped by
agent or charter instead. Writing both into one table would mean a nullable half of every
row and two meanings for ``metric_name`` — and the Attention surface would have to guess
which kind it was holding. Same delivery path, same shape of rule, different subject.

The write order is deliberate and mirrors the monitors store: the event row is committed
BEFORE delivery is attempted, and ``mark_delivered`` stamps the outcome afterwards. A
channel that is down then leaves a visible alert rather than nothing at all.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from aughor.db.backend import connect_store
from aughor.db.migrations import run_migrations
from aughor.db.sqlite_util import resolve_db_path
from aughor.obs.agent_alerts import AgentAlertEvent, AgentAlertRule

logger = logging.getLogger(__name__)

_DB_PATH = resolve_db_path("AUGHOR_AGENT_ALERTS_DB", Path("data") / "agent_alerts.db")
_LOCK = threading.Lock()

_DDL = """
CREATE TABLE IF NOT EXISTS agent_alert_rules (
    id               TEXT PRIMARY KEY,
    name             TEXT NOT NULL,
    metric           TEXT NOT NULL,
    comparator       TEXT NOT NULL DEFAULT 'gt',
    threshold        REAL NOT NULL DEFAULT 0,
    window_minutes   INTEGER NOT NULL DEFAULT 15,
    debounce_minutes INTEGER NOT NULL DEFAULT 30,
    check_cron       TEXT NOT NULL DEFAULT '*/5 * * * *',
    agent_id         TEXT NOT NULL DEFAULT '',
    charter_id       TEXT NOT NULL DEFAULT '',
    channel          TEXT NOT NULL DEFAULT '',
    severity         TEXT NOT NULL DEFAULT 'warning',
    enabled          INTEGER NOT NULL DEFAULT 1,
    org_id           TEXT NOT NULL DEFAULT '',
    last_notified_at TEXT,
    created_at       TEXT NOT NULL DEFAULT '',
    updated_at       TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS agent_alert_events (
    id              TEXT PRIMARY KEY,
    rule_id         TEXT NOT NULL,
    rule_name       TEXT NOT NULL DEFAULT '',
    metric          TEXT NOT NULL DEFAULT '',
    severity        TEXT NOT NULL DEFAULT 'warning',
    fired_at        TEXT NOT NULL,
    value           REAL,
    threshold       REAL,
    population      INTEGER NOT NULL DEFAULT 0,
    window_minutes  INTEGER NOT NULL DEFAULT 0,
    reason          TEXT NOT NULL DEFAULT '',
    observed        TEXT NOT NULL DEFAULT '{}',
    delivered       INTEGER NOT NULL DEFAULT 0,
    delivery_detail TEXT NOT NULL DEFAULT '',
    acknowledged    INTEGER NOT NULL DEFAULT 0,
    acknowledged_at TEXT,
    org_id          TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_agent_alert_events_rule ON agent_alert_events (rule_id);
CREATE INDEX IF NOT EXISTS idx_agent_alert_events_time ON agent_alert_events (fired_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_alert_events_ack  ON agent_alert_events (acknowledged);
"""

#: Base DDL is conceptually v1; every later change is an additive Migration (DATA-05).
_MIGRATIONS: list = []


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    conn = connect_store(_DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _init_schema() -> None:
    with _LOCK:
        conn = _connect()
        try:
            conn.executescript(_DDL)
            conn.commit()
            run_migrations(conn, _MIGRATIONS, store="agent_alerts")
        finally:
            conn.close()


_init_schema()


# ── rules ─────────────────────────────────────────────────────────────────────

_RULE_COLS = ("id", "name", "metric", "comparator", "threshold", "window_minutes",
              "debounce_minutes", "check_cron", "agent_id", "charter_id", "channel",
              "severity", "enabled", "org_id", "last_notified_at")


def _row_to_rule(row: sqlite3.Row) -> AgentAlertRule:
    d = dict(row)
    d["enabled"] = bool(d.get("enabled", 1))
    return AgentAlertRule(**{k: d.get(k) for k in _RULE_COLS if k in d})


def list_rules(*, enabled_only: bool = False, org_id: Optional[str] = None
               ) -> list[AgentAlertRule]:
    conn = _connect()
    try:
        q = "SELECT * FROM agent_alert_rules WHERE 1=1"
        args: list = []
        if enabled_only:
            q += " AND enabled = 1"
        if org_id is not None:
            q += " AND org_id = ?"
            args.append(org_id)
        q += " ORDER BY created_at DESC"
        return [_row_to_rule(r) for r in conn.execute(q, args).fetchall()]
    finally:
        conn.close()


def get_rule(rule_id: str) -> Optional[AgentAlertRule]:
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM agent_alert_rules WHERE id = ?",
                           (rule_id,)).fetchone()
        return _row_to_rule(row) if row else None
    finally:
        conn.close()


def upsert_rule(rule: AgentAlertRule, *, org_id: str = "") -> AgentAlertRule:
    """Create or update. Returns the stored rule, with its id filled in on create."""
    if not rule.id:
        rule = rule.model_copy(update={"id": uuid.uuid4().hex[:12]})
    now = _now()
    conn = _connect()
    try:
        with _LOCK:
            existing = conn.execute("SELECT created_at, org_id, last_notified_at "
                                    "FROM agent_alert_rules WHERE id = ?",
                                    (rule.id,)).fetchone()
            created = (existing["created_at"] if existing else now)
            # An edit must not reset the debounce clock: raising a threshold is not a
            # reason to re-page someone about a condition they were already told about.
            last_notified = rule.last_notified_at or (
                existing["last_notified_at"] if existing else None)
            owner = (existing["org_id"] if existing else org_id)
            conn.execute(
                "INSERT OR REPLACE INTO agent_alert_rules "
                "(id, name, metric, comparator, threshold, window_minutes, debounce_minutes, "
                " check_cron, agent_id, charter_id, channel, severity, enabled, org_id, "
                " last_notified_at, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (rule.id, rule.name, rule.metric, rule.comparator, rule.threshold,
                 rule.window_minutes, rule.debounce_minutes, rule.check_cron, rule.agent_id,
                 rule.charter_id, rule.channel, rule.severity, 1 if rule.enabled else 0,
                 owner, last_notified, created, now))
            conn.commit()
    finally:
        conn.close()
    stored = get_rule(rule.id)
    return stored if stored is not None else rule


def delete_rule(rule_id: str) -> bool:
    conn = _connect()
    try:
        with _LOCK:
            cur = conn.execute("DELETE FROM agent_alert_rules WHERE id = ?", (rule_id,))
            conn.commit()
            return cur.rowcount > 0
    finally:
        conn.close()


def set_rule_enabled(rule_id: str, enabled: bool) -> Optional[AgentAlertRule]:
    conn = _connect()
    try:
        with _LOCK:
            conn.execute("UPDATE agent_alert_rules SET enabled = ?, updated_at = ? "
                         "WHERE id = ?", (1 if enabled else 0, _now(), rule_id))
            conn.commit()
    finally:
        conn.close()
    return get_rule(rule_id)


def mark_notified(rule_id: str, at: str) -> None:
    """Stamp the debounce clock. Written only when a rule NOTIFIED, never when it merely
    matched — the quiet period is about how often a person hears from us."""
    conn = _connect()
    try:
        with _LOCK:
            conn.execute("UPDATE agent_alert_rules SET last_notified_at = ?, updated_at = ? "
                         "WHERE id = ?", (at, _now(), rule_id))
            conn.commit()
    finally:
        conn.close()


# ── events ────────────────────────────────────────────────────────────────────

def append_event(event: AgentAlertEvent) -> AgentAlertEvent:
    if not event.id:
        event = event.model_copy(update={"id": uuid.uuid4().hex[:12]})
    if not event.fired_at:
        event = event.model_copy(update={"fired_at": _now()})
    conn = _connect()
    try:
        with _LOCK:
            conn.execute(
                "INSERT OR REPLACE INTO agent_alert_events "
                "(id, rule_id, rule_name, metric, severity, fired_at, value, threshold, "
                " population, window_minutes, reason, observed, delivered, delivery_detail, "
                " acknowledged, acknowledged_at, org_id) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (event.id, event.rule_id, event.rule_name, event.metric, event.severity,
                 event.fired_at, event.value, event.threshold, event.population,
                 event.window_minutes, event.reason, json.dumps(event.observed),
                 1 if event.delivered else 0, event.delivery_detail,
                 1 if event.acknowledged else 0, event.acknowledged_at, event.org_id))
            conn.commit()
    finally:
        conn.close()
    return event


def _row_to_event(row: sqlite3.Row) -> AgentAlertEvent:
    d = dict(row)
    try:
        d["observed"] = json.loads(d.get("observed") or "{}")
    except (TypeError, ValueError):
        # A row whose observed blob is unreadable is still an alert. Losing the whole
        # event because its detail will not parse would hide the thing it reported.
        logger.warning("agent alert %s has an unreadable observed blob", d.get("id"))
        d["observed"] = {}
    d["delivered"] = bool(d.get("delivered", 0))
    d["acknowledged"] = bool(d.get("acknowledged", 0))
    return AgentAlertEvent(**d)


def list_events(*, rule_id: Optional[str] = None, unacknowledged_only: bool = False,
                since: Optional[str] = None, limit: int = 100) -> list[AgentAlertEvent]:
    conn = _connect()
    try:
        q = "SELECT * FROM agent_alert_events WHERE 1=1"
        args: list = []
        if rule_id:
            q += " AND rule_id = ?"
            args.append(rule_id)
        if unacknowledged_only:
            q += " AND acknowledged = 0"
        if since:
            q += " AND fired_at >= ?"
            args.append(since)
        q += " ORDER BY fired_at DESC LIMIT ?"
        args.append(int(limit))
        return [_row_to_event(r) for r in conn.execute(q, args).fetchall()]
    finally:
        conn.close()


def mark_delivered(event_id: str, *, delivered: bool, detail: str = "") -> None:
    conn = _connect()
    try:
        with _LOCK:
            conn.execute("UPDATE agent_alert_events SET delivered = ?, delivery_detail = ? "
                         "WHERE id = ?", (1 if delivered else 0, detail[:500], event_id))
            conn.commit()
    finally:
        conn.close()


def acknowledge_event(event_id: str) -> Optional[AgentAlertEvent]:
    conn = _connect()
    try:
        with _LOCK:
            conn.execute("UPDATE agent_alert_events SET acknowledged = 1, acknowledged_at = ? "
                         "WHERE id = ?", (_now(), event_id))
            conn.commit()
        row = conn.execute("SELECT * FROM agent_alert_events WHERE id = ?",
                           (event_id,)).fetchone()
        return _row_to_event(row) if row else None
    finally:
        conn.close()
