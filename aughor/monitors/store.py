"""SQLite-backed persistence for Monitors and MonitorAlerts.

Two tables in data/monitors.db:
  monitors       — configuration rows; mutable (upsert by id)
  monitor_alerts — append-only fired alerts; acknowledged flag is the only mutable field
"""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Optional

from aughor.monitors.models import Monitor, MonitorAlert

_DB_PATH = Path("data") / "monitors.db"
_LOCK = threading.Lock()


# ── Schema ────────────────────────────────────────────────────────────────────

_DDL = """
CREATE TABLE IF NOT EXISTS monitors (
    id                  TEXT PRIMARY KEY,
    conn_id             TEXT NOT NULL,
    name                TEXT NOT NULL,
    metric_name         TEXT,
    custom_sql          TEXT,
    check_cron          TEXT NOT NULL DEFAULT '0 * * * *',
    alert_on            TEXT NOT NULL DEFAULT 'threshold_cross',
    warning_threshold   REAL,
    critical_threshold  REAL,
    threshold_direction TEXT NOT NULL DEFAULT 'below',
    sigma_threshold     REAL NOT NULL DEFAULT 2.5,
    history_days        INTEGER NOT NULL DEFAULT 30,
    dimension_column    TEXT,
    drift_p_threshold   REAL NOT NULL DEFAULT 0.05,
    freshness_table     TEXT,
    freshness_column    TEXT NOT NULL DEFAULT 'updated_at',
    freshness_sla_hours REAL NOT NULL DEFAULT 24.0,
    notification_channel TEXT NOT NULL DEFAULT 'in_app',
    enabled             INTEGER NOT NULL DEFAULT 1,
    created_at          TEXT NOT NULL DEFAULT '',
    updated_at          TEXT NOT NULL DEFAULT '',
    extra               TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS monitor_alerts (
    id               TEXT PRIMARY KEY,
    monitor_id       TEXT NOT NULL,
    monitor_name     TEXT NOT NULL DEFAULT '',
    conn_id          TEXT NOT NULL DEFAULT '',
    metric_name      TEXT,
    triggered_at     TEXT NOT NULL,
    alert_on         TEXT NOT NULL DEFAULT '',
    severity         TEXT NOT NULL DEFAULT 'warning',
    current_value    REAL,
    previous_value   REAL,
    threshold        REAL,
    message          TEXT NOT NULL DEFAULT '',
    acknowledged     INTEGER NOT NULL DEFAULT 0,
    acknowledged_at  TEXT
);

CREATE INDEX IF NOT EXISTS idx_alerts_monitor ON monitor_alerts (monitor_id);
CREATE INDEX IF NOT EXISTS idx_alerts_conn    ON monitor_alerts (conn_id);
CREATE INDEX IF NOT EXISTS idx_alerts_time    ON monitor_alerts (triggered_at DESC);
"""


def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _init_schema() -> None:
    with _LOCK:
        conn = _connect()
        try:
            conn.executescript(_DDL)
            conn.commit()
        finally:
            conn.close()


_init_schema()


# ── Monitor CRUD ──────────────────────────────────────────────────────────────

def _row_to_monitor(row: sqlite3.Row) -> Monitor:
    d = dict(row)
    d["enabled"] = bool(d["enabled"])
    # Fields added after the original schema live in the `extra` JSON blob (avoids a
    # column migration). Merge them back into the Monitor kwargs.
    extra_raw = d.pop("extra", None)
    if extra_raw:
        try:
            d.update(json.loads(extra_raw))
        except Exception:
            pass
    return Monitor(**{k: v for k, v in d.items() if v is not None or k in {
        "metric_name", "custom_sql", "warning_threshold", "critical_threshold",
        "dimension_column", "freshness_table",
    }})


def list_monitors(conn_id: Optional[str] = None) -> list[Monitor]:
    with _LOCK:
        conn = _connect()
        try:
            if conn_id:
                rows = conn.execute(
                    "SELECT * FROM monitors WHERE conn_id = ? ORDER BY name", (conn_id,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM monitors ORDER BY name").fetchall()
            return [_row_to_monitor(r) for r in rows]
        finally:
            conn.close()


def get_monitor(monitor_id: str) -> Optional[Monitor]:
    with _LOCK:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT * FROM monitors WHERE id = ?", (monitor_id,)
            ).fetchone()
            return _row_to_monitor(row) if row else None
        finally:
            conn.close()


def upsert_monitor(monitor: Monitor) -> Monitor:
    """Create or update a monitor (full replace by id)."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    if not monitor.created_at:
        monitor = monitor.model_copy(update={"created_at": now})
    monitor = monitor.model_copy(update={"updated_at": now})

    params = monitor.model_dump()
    # Persist post-schema fields in the `extra` JSON blob (no column migration).
    params["extra"] = json.dumps({"reanchor_window": monitor.reanchor_window})

    with _LOCK:
        conn = _connect()
        try:
            conn.execute("""
                INSERT INTO monitors (
                    id, conn_id, name, metric_name, custom_sql, check_cron,
                    alert_on, warning_threshold, critical_threshold, threshold_direction,
                    sigma_threshold, history_days, dimension_column, drift_p_threshold,
                    freshness_table, freshness_column, freshness_sla_hours,
                    notification_channel, enabled, created_at, updated_at, extra
                ) VALUES (
                    :id, :conn_id, :name, :metric_name, :custom_sql, :check_cron,
                    :alert_on, :warning_threshold, :critical_threshold, :threshold_direction,
                    :sigma_threshold, :history_days, :dimension_column, :drift_p_threshold,
                    :freshness_table, :freshness_column, :freshness_sla_hours,
                    :notification_channel, :enabled, :created_at, :updated_at, :extra
                )
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    metric_name=excluded.metric_name,
                    custom_sql=excluded.custom_sql,
                    check_cron=excluded.check_cron,
                    alert_on=excluded.alert_on,
                    warning_threshold=excluded.warning_threshold,
                    critical_threshold=excluded.critical_threshold,
                    threshold_direction=excluded.threshold_direction,
                    sigma_threshold=excluded.sigma_threshold,
                    history_days=excluded.history_days,
                    dimension_column=excluded.dimension_column,
                    drift_p_threshold=excluded.drift_p_threshold,
                    freshness_table=excluded.freshness_table,
                    freshness_column=excluded.freshness_column,
                    freshness_sla_hours=excluded.freshness_sla_hours,
                    notification_channel=excluded.notification_channel,
                    enabled=excluded.enabled,
                    updated_at=excluded.updated_at,
                    extra=excluded.extra
            """, params)
            conn.commit()
        finally:
            conn.close()
    return monitor


def delete_monitor(monitor_id: str) -> bool:
    with _LOCK:
        conn = _connect()
        try:
            cur = conn.execute("DELETE FROM monitors WHERE id = ?", (monitor_id,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()


def set_monitor_enabled(monitor_id: str, enabled: bool) -> Optional[Monitor]:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    with _LOCK:
        conn = _connect()
        try:
            conn.execute(
                "UPDATE monitors SET enabled = ?, updated_at = ? WHERE id = ?",
                (int(enabled), now, monitor_id),
            )
            conn.commit()
        finally:
            conn.close()
    return get_monitor(monitor_id)


# ── Alert append + queries ────────────────────────────────────────────────────

def _row_to_alert(row: sqlite3.Row) -> MonitorAlert:
    d = dict(row)
    d["acknowledged"] = bool(d["acknowledged"])
    return MonitorAlert(**{k: v for k, v in d.items() if v is not None or k in {
        "metric_name", "current_value", "previous_value", "threshold", "acknowledged_at",
    }})


def append_alert(alert: MonitorAlert) -> MonitorAlert:
    """Persist a new alert. Idempotent — silent no-op on duplicate id."""
    with _LOCK:
        conn = _connect()
        try:
            conn.execute("""
                INSERT OR IGNORE INTO monitor_alerts (
                    id, monitor_id, monitor_name, conn_id, metric_name,
                    triggered_at, alert_on, severity, current_value, previous_value,
                    threshold, message, acknowledged, acknowledged_at
                ) VALUES (
                    :id, :monitor_id, :monitor_name, :conn_id, :metric_name,
                    :triggered_at, :alert_on, :severity, :current_value, :previous_value,
                    :threshold, :message, :acknowledged, :acknowledged_at
                )
            """, alert.model_dump())
            conn.commit()
        finally:
            conn.close()
    return alert


def get_alerts(
    monitor_id: Optional[str] = None,
    conn_id: Optional[str] = None,
    limit: int = 100,
    unacknowledged_only: bool = False,
) -> list[MonitorAlert]:
    clauses = []
    params: list = []
    if monitor_id:
        clauses.append("monitor_id = ?"); params.append(monitor_id)
    if conn_id:
        clauses.append("conn_id = ?"); params.append(conn_id)
    if unacknowledged_only:
        clauses.append("acknowledged = 0")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    with _LOCK:
        conn = _connect()
        try:
            rows = conn.execute(
                f"SELECT * FROM monitor_alerts {where} ORDER BY triggered_at DESC LIMIT ?",
                [*params, limit],
            ).fetchall()
            return [_row_to_alert(r) for r in rows]
        finally:
            conn.close()


def acknowledge_alert(alert_id: str) -> Optional[MonitorAlert]:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    with _LOCK:
        conn = _connect()
        try:
            conn.execute(
                "UPDATE monitor_alerts SET acknowledged = 1, acknowledged_at = ? WHERE id = ?",
                (now, alert_id),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM monitor_alerts WHERE id = ?", (alert_id,)
            ).fetchone()
            return _row_to_alert(row) if row else None
        finally:
            conn.close()
