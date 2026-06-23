"""Append-only audit log — every query execution is recorded in data/audit.db.

Design:
  - SQLite WAL mode for concurrent reads alongside the main app
  - Records are never deleted or updated (append-only semantics)
  - Each record captures: who (connection), what (SQL), when, verdict, outcome

API:
    AuditLogger.log(...)   → write a record, returns record_id
    AuditLogger.recent()   → last N records
    AuditLogger.stats()    → aggregate counts per connection
"""
from __future__ import annotations

import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

_DB_PATH = Path("data/audit.db")


def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def _ensure_schema(c: sqlite3.Connection) -> None:
    c.executescript("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id            TEXT    PRIMARY KEY,
            ts            TEXT    NOT NULL,
            connection_id TEXT    NOT NULL,
            hypothesis_id TEXT    NOT NULL DEFAULT '',
            sql_digest    TEXT    NOT NULL,
            sql_full      TEXT    NOT NULL,
            verdict       TEXT    NOT NULL DEFAULT 'safe',
            row_count     INTEGER NOT NULL DEFAULT 0,
            duration_ms   REAL    NOT NULL DEFAULT 0,
            pii_redacted  INTEGER NOT NULL DEFAULT 0,
            error         TEXT,
            org_id        TEXT    NOT NULL DEFAULT 'default'
        );
        CREATE INDEX IF NOT EXISTS idx_audit_conn ON audit_log (connection_id);
        CREATE INDEX IF NOT EXISTS idx_audit_ts   ON audit_log (ts);
        PRAGMA journal_mode=WAL;
    """)
    # Migration (2026-06-22): tenant key on existing single-org audit logs.
    # Idempotent — add only if an older DB predates the column.
    cols = {r[1] for r in c.execute("PRAGMA table_info(audit_log)").fetchall()}
    if "org_id" not in cols:
        c.execute("ALTER TABLE audit_log ADD COLUMN org_id TEXT NOT NULL DEFAULT 'default'")
    c.commit()


class AuditLogger:
    """Append-only audit writer. Thread-safe via per-call connection open/close."""

    @classmethod
    def log(
        cls,
        *,
        connection_id: str,
        hypothesis_id: str = "",
        sql: str,
        verdict: str = "safe",
        row_count: int = 0,
        duration_ms: float = 0.0,
        pii_redacted: int = 0,
        error: str | None = None,
        org_id: str | None = None,
    ) -> str:
        """Write one audit record. Returns the new record ID. ``org_id`` defaults to
        the current tenant context so every audited query is tenant-keyed."""
        from aughor.org.context import current_org_id
        record_id = str(uuid.uuid4())
        digest = sql[:120].replace("\n", " ").strip()
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        oid = org_id or current_org_id()
        c = _connect()
        try:
            _ensure_schema(c)
            c.execute(
                """INSERT INTO audit_log
                   (id, ts, connection_id, hypothesis_id, sql_digest, sql_full,
                    verdict, row_count, duration_ms, pii_redacted, error, org_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (record_id, ts, connection_id, hypothesis_id, digest, sql,
                 verdict, row_count, round(duration_ms, 2), pii_redacted, error, oid),
            )
            c.commit()
        finally:
            c.close()
        return record_id

    @classmethod
    def recent(
        cls,
        limit: int = 100,
        connection_id: str | None = None,
        verdict: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return recent records, newest first. Optional filters by connection/verdict."""
        c = _connect()
        try:
            _ensure_schema(c)
            clauses: list[str] = []
            params: list[Any] = []
            if connection_id:
                clauses.append("connection_id = ?")
                params.append(connection_id)
            if verdict:
                clauses.append("verdict = ?")
                params.append(verdict)
            where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
            rows = c.execute(
                f"SELECT * FROM audit_log {where} ORDER BY ts DESC LIMIT ?",
                [*params, limit],
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            c.close()

    @classmethod
    def stats(cls, connection_id: str | None = None) -> dict[str, Any]:
        """Aggregate stats: totals, blocked count, suspicious count, PII redactions."""
        c = _connect()
        try:
            _ensure_schema(c)
            where = "WHERE connection_id = ?" if connection_id else ""
            params = (connection_id,) if connection_id else ()
            row = c.execute(
                f"""SELECT
                       COUNT(*)                                           AS total,
                       SUM(CASE WHEN verdict='blocked'    THEN 1 ELSE 0 END) AS blocked,
                       SUM(CASE WHEN verdict='suspicious' THEN 1 ELSE 0 END) AS suspicious,
                       SUM(CASE WHEN error IS NOT NULL    THEN 1 ELSE 0 END) AS errors,
                       SUM(pii_redacted)                                  AS pii_redacted,
                       AVG(duration_ms)                                   AS avg_duration_ms
                    FROM audit_log {where}""",
                params,
            ).fetchone()
            return dict(row) if row else {}
        finally:
            c.close()
