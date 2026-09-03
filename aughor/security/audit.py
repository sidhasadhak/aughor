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

from aughor.db.migrations import Migration, add_column_if_missing, run_migrations
from aughor.db.sqlite_util import resolve_db_path
from aughor.db.backend import connect_store
from aughor.db.store_pool import ensure_once

_DB_PATH = resolve_db_path("AUGHOR_AUDIT_DB", Path("data/audit.db"))

# Schema evolution (DATA-05). The `audit_log` base table is v1; changes are Migration(v>=2).
_MIGRATIONS = [
    Migration(2, "tenant key: org_id on audit_log",
              lambda c: add_column_if_missing(c, "audit_log", "org_id", "TEXT NOT NULL DEFAULT 'default'")),
    # Wave E1: correlate an audited statement to the run that issued it. This table
    # sees EVERY execution — including the quick path, which bypasses the
    # span-emitting executor — so it is the one place where "which run ran this
    # SQL" is answerable for all paths at once. Defaulted from the ambient trace,
    # so no call site changes.
    Migration(3, "correlation key: trace_id on audit_log",
              lambda c: add_column_if_missing(c, "audit_log", "trace_id", "TEXT NOT NULL DEFAULT ''")),
]


def _connect() -> sqlite3.Connection:
    c = connect_store(_DB_PATH, check_same_thread=False)
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

        -- MI-1: the guard verdict, kept. Guards were computed on every execution and
        -- discarded at birth -- `run_trust_checks` returned E1 issues and the rewrite
        -- receipts fanned out to an SSE sink, so the best free supervision signal on the
        -- platform lived only as long as a browser tab. It rides THIS database because
        -- `audit_log` is the one table that sees every execution (quick path included),
        -- which makes "run -> executed SQL -> guard fire" a single-store join instead of
        -- a cross-database reconstruction.
        --
        -- FIRES ONLY, deliberately: the denominator is `audit_log` itself. Every execution
        -- writes an audit row, so "clean" is an audit row with no guard_verdicts sibling —
        -- a rate whose denominator is already durable, without doubling the write volume
        -- of the busiest table in the system.
        CREATE TABLE IF NOT EXISTS guard_verdicts (
            id         TEXT NOT NULL PRIMARY KEY,
            ts         TEXT NOT NULL,
            trace_id   TEXT NOT NULL,
            org_id     TEXT NOT NULL DEFAULT 'default',
            sql_digest TEXT NOT NULL DEFAULT '',
            pattern    TEXT NOT NULL,
            subject    TEXT NOT NULL DEFAULT '',
            phase      TEXT NOT NULL DEFAULT '',
            detail     TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_guard_trace   ON guard_verdicts (trace_id);
        CREATE INDEX IF NOT EXISTS idx_guard_ts      ON guard_verdicts (ts);
        CREATE INDEX IF NOT EXISTS idx_guard_pattern ON guard_verdicts (pattern);
        PRAGMA journal_mode=WAL;
    """)
    run_migrations(c, _MIGRATIONS, store="audit")
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
        trace_id: str | None = None,
    ) -> str:
        """Write one audit record. Returns the new record ID. ``org_id`` defaults to
        the current tenant context so every audited query is tenant-keyed, and
        ``trace_id`` to the ambient run so the statement joins to the session log
        without any caller threading it through."""
        from aughor.org.context import current_org_id
        record_id = str(uuid.uuid4())
        digest = sql[:120].replace("\n", " ").strip()
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        oid = org_id or current_org_id()
        if trace_id is None:
            try:
                from aughor.telemetry import current_trace_id
                trace_id = current_trace_id()
            except Exception:
                trace_id = ""
        c = _connect()
        try:
            ensure_once(c, _ensure_schema)
            c.execute(
                """INSERT INTO audit_log
                   (id, ts, connection_id, hypothesis_id, sql_digest, sql_full,
                    verdict, row_count, duration_ms, pii_redacted, error, org_id, trace_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (record_id, ts, connection_id, hypothesis_id, digest, sql,
                 verdict, row_count, round(duration_ms, 2), pii_redacted, error, oid,
                 trace_id or ""),
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
        label: str | None = None,
        org_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return recent records, newest first. Optional filters by connection/verdict/label
        (``label`` matches the ``hypothesis_id`` column — the surface that issued the SQL,
        e.g. ``query_builder`` / ``query_workbench`` — which is what makes the SQL editor's
        history rail a filtered read of this log, SE-0).

        ``org_id`` is the TENANT filter (DATA-06). Every row is written with the tenant
        that ran it, so the predicate is the row's own ``org_id`` rather than a set of
        currently-registered connection ids: an audit row must stay scoped even after its
        connection is deleted (8,558 such rows exist in one local log), and a read whose
        scope depends on the registry's present state would re-expose them. ``None`` means
        no tenant filter — localhost/identity-off, where a single tenant owns everything.
        """
        c = _connect()
        try:
            ensure_once(c, _ensure_schema)
            clauses: list[str] = []
            params: list[Any] = []
            if org_id is not None:
                clauses.append("org_id = ?")
                params.append(org_id)
            if connection_id:
                clauses.append("connection_id = ?")
                params.append(connection_id)
            if verdict:
                clauses.append("verdict = ?")
                params.append(verdict)
            if label:
                clauses.append("hypothesis_id = ?")
                params.append(label)
            where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
            rows = c.execute(
                f"SELECT * FROM audit_log {where} ORDER BY ts DESC LIMIT ?",
                [*params, limit],
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            c.close()

    @classmethod
    def stats(cls, connection_id: str | None = None,
              org_id: str | None = None) -> dict[str, Any]:
        """Aggregate stats: totals, blocked count, suspicious count, PII redactions.

        ``org_id`` scopes to one tenant (DATA-06) — an aggregate over every org's
        traffic is a leak of a quieter kind: it says how much SQL another tenant runs
        and how often it is blocked. ``None`` = no tenant filter (localhost)."""
        c = _connect()
        try:
            ensure_once(c, _ensure_schema)
            clauses: list[str] = []
            params_l: list[Any] = []
            if org_id is not None:
                clauses.append("org_id = ?")
                params_l.append(org_id)
            if connection_id:
                clauses.append("connection_id = ?")
                params_l.append(connection_id)
            where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
            params = tuple(params_l)
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


class GuardVerdicts:
    """MI-1 — the durable half of the guard plane. Append-only, one row per FIRE.

    Two producers feed this sink, and they are deliberately separate because the guard
    families have genuinely different shapes: `run_trust_checks` records its E1 semantic
    caveats (pattern + the column they are about), and the kernel's `emit_guard_receipt`
    seam records interventions that rewrote SQL (guard name + what changed). Both are
    registration-free — neither depends on the agent plugin being wired, so a bare
    platform, an automation tick and the quick path all record.
    """

    @classmethod
    def record(
        cls,
        *,
        pattern: str,
        subject: str = "",
        phase: str = "",
        sql: str = "",
        detail: str = "",
        trace_id: str | None = None,
        org_id: str | None = None,
    ) -> None:
        """Persist one guard fire. Best-effort and TRACE-GATED; never raises.

        A verdict with no trace is dropped rather than written orphaned — the same law
        the session log already applies, for the same reason: this row exists to be
        JOINED (run -> executed SQL -> guard fire -> human verdict), and a row that can
        reach none of those is noise that makes the table look healthier than it is.
        That gating is also what keeps the check free for tests, scripts and the eval
        plane's `guard.e1_semantics`, which call the same pure functions outside a run.

        Guarding must never cost a query its answer: every failure here is tolerated,
        exactly like the audit write it sits beside.
        """
        try:
            if trace_id is None:
                from aughor.telemetry import current_trace_id
                trace_id = current_trace_id()
            if not trace_id:
                return
            from aughor.org.context import current_org_id
            c = _connect()
            try:
                ensure_once(c, _ensure_schema)
                c.execute(
                    """INSERT INTO guard_verdicts
                       (id, ts, trace_id, org_id, sql_digest, pattern, subject, phase, detail)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (str(uuid.uuid4()),
                     time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                     trace_id,
                     org_id or current_org_id(),
                     (sql or "")[:120].replace("\n", " ").strip(),
                     pattern, subject, phase, (detail or "")[:500]),
                )
                c.commit()
            finally:
                c.close()
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "guard-verdict persistence is additive; the guard still fired",
                     counter="guard.verdict_record")

    @classmethod
    def recent(cls, limit: int = 100, trace_id: str | None = None,
               pattern: str | None = None,
               org_id: str | None = None) -> list[dict[str, Any]]:
        """Recent guard fires, newest first. ``org_id`` is the tenant filter (DATA-06),
        with the same contract as :meth:`AuditLogger.recent`: ``None`` means no filter."""
        c = _connect()
        try:
            ensure_once(c, _ensure_schema)
            clauses: list[str] = []
            params: list[Any] = []
            if org_id is not None:
                clauses.append("org_id = ?")
                params.append(org_id)
            if trace_id:
                clauses.append("trace_id = ?")
                params.append(trace_id)
            if pattern:
                clauses.append("pattern = ?")
                params.append(pattern)
            where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
            rows = c.execute(
                f"SELECT * FROM guard_verdicts {where} ORDER BY ts DESC LIMIT ?",
                [*params, limit],
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            c.close()
