"""SQLite-backed store for human verdicts on investigation findings (Bet 0, 0-V).

Every verdict is org-scoped (`org_id` from the request context) so multi-tenant falls out
for free, matching the rest of the platform. Mirrors the PRAGMA-free additive-schema idiom
of `aughor/org/store.py`. Best-effort, never raises into the request path beyond validation.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from aughor.org.context import current_org_id
from aughor.util.time import now_iso as _now
from aughor.db.migrations import Migration, add_column_if_missing, run_migrations
from aughor.db.sqlite_util import resolve_db_path, tune

_DB_PATH = resolve_db_path("AUGHOR_VERDICTS_DB", Path(__file__).parent.parent.parent / "data" / "verdicts.db")


def _add_closeloop_cols(c: "sqlite3.Connection") -> None:
    # The SQL that produced a judged finding + any human correction — what lets a
    # verdict feed back into the planner instead of dying as a bare label.
    add_column_if_missing(c, "finding_verdicts", "sql_source", "TEXT NOT NULL DEFAULT ''")
    add_column_if_missing(c, "finding_verdicts", "corrected_sql", "TEXT NOT NULL DEFAULT ''")


# Schema evolution (DATA-05). The `finding_verdicts` base table is v1; changes are Migration(v>=2).
_MIGRATIONS = [Migration(2, "close-the-loop columns (sql_source, corrected_sql)", _add_closeloop_cols)]

# accept = the finding is correct/useful · correct = right direction but a detail is wrong
# · reject = wrong or misleading. These are the labels the trust economy calibrates against.
VERDICTS = ("accept", "correct", "reject")


def _conn() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = tune(sqlite3.connect(str(_DB_PATH)))
    c.row_factory = sqlite3.Row
    _ensure_schema(c)
    return c


def _ensure_schema(c: sqlite3.Connection) -> None:
    c.execute("""
        CREATE TABLE IF NOT EXISTS finding_verdicts (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            org_id          TEXT NOT NULL,
            connection_id   TEXT NOT NULL DEFAULT '',
            investigation_id TEXT NOT NULL DEFAULT '',
            verdict         TEXT NOT NULL,
            note            TEXT NOT NULL DEFAULT '',
            headline        TEXT NOT NULL DEFAULT '',
            sql_source      TEXT NOT NULL DEFAULT '',
            corrected_sql   TEXT NOT NULL DEFAULT '',
            created_at      TEXT NOT NULL
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS ix_verdicts_org_conn "
              "ON finding_verdicts (org_id, connection_id)")
    run_migrations(c, _MIGRATIONS, store="verdicts")
    c.commit()


def record_verdict(
    connection_id: str,
    investigation_id: str,
    verdict: str,
    note: str = "",
    headline: str = "",
    sql_source: str = "",
    corrected_sql: str = "",
) -> dict:
    """Persist a human verdict on a finding. Raises ValueError on an invalid verdict label
    (the only failure the caller must handle); everything else is a normal insert.

    ``sql_source`` is the SQL that produced the judged finding and ``corrected_sql`` an
    optional human fix — the structural payload the planner reads back (P1 close-the-loop).
    Both are optional so every existing caller keeps working unchanged."""
    v = (verdict or "").strip().lower()
    if v not in VERDICTS:
        raise ValueError(f"verdict must be one of {VERDICTS}, got {verdict!r}")
    org = current_org_id()
    now = _now()
    c = _conn()
    try:
        cur = c.execute(
            "INSERT INTO finding_verdicts "
            "(org_id, connection_id, investigation_id, verdict, note, headline, "
            "sql_source, corrected_sql, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (org, connection_id or "", investigation_id or "", v, note or "", headline or "",
             sql_source or "", corrected_sql or "", now),
        )
        c.commit()
        result = {
            "id": cur.lastrowid, "org_id": org, "connection_id": connection_id or "",
            "investigation_id": investigation_id or "", "verdict": v,
            "note": note or "", "headline": headline or "",
            "sql_source": sql_source or "", "corrected_sql": corrected_sql or "",
            "created_at": now,
        }
    finally:
        c.close()
    # Verdict → Ambiguity Ledger bridge: a reviewer's reject/correct on a headlined finding
    # crystallizes as the HIGHEST-authority resolution (overrides any probe/user reading on that
    # question). Best-effort, gated with the ledger (closed_loop); never fails the verdict write.
    if v in ("reject", "correct") and (headline or "").strip():
        try:
            from aughor.verify.priors import closed_loop_enabled
            if closed_loop_enabled():
                from aughor.semantic.ambiguity_ledger import crystallize_verdict
                crystallize_verdict(connection_id or "", headline, org_id=org,
                                    corrected_sql=corrected_sql or "", note=note or "")
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "verdict→ledger crystallization is best-effort",
                     counter="verdicts.ledger_bridge")
    return result


def verdict_stats(connection_id: Optional[str] = None) -> dict:
    """Counts by verdict for the current org (optionally filtered to one connection) plus the
    acceptance rate — the headline calibration signal the trust economy reads."""
    org = current_org_id()
    c = _conn()
    try:
        if connection_id:
            rows = c.execute(
                "SELECT verdict, COUNT(*) n FROM finding_verdicts "
                "WHERE org_id=? AND connection_id=? GROUP BY verdict",
                (org, connection_id),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT verdict, COUNT(*) n FROM finding_verdicts WHERE org_id=? GROUP BY verdict",
                (org,),
            ).fetchall()
    finally:
        c.close()
    counts = {v: 0 for v in VERDICTS}
    for r in rows:
        if r["verdict"] in counts:
            counts[r["verdict"]] = r["n"]
    total = sum(counts.values())
    # acceptance credits a full accept and a half-credit "correct" (right direction).
    acceptance = round((counts["accept"] + 0.5 * counts["correct"]) / total, 3) if total else None
    return {"counts": counts, "total": total, "acceptance_rate": acceptance}


def list_verdicts(connection_id: Optional[str] = None, limit: int = 50) -> list[dict]:
    """Most-recent verdicts for the current org (optionally one connection)."""
    org = current_org_id()
    limit = max(1, min(int(limit), 500))
    c = _conn()
    try:
        if connection_id:
            rows = c.execute(
                "SELECT * FROM finding_verdicts WHERE org_id=? AND connection_id=? "
                "ORDER BY id DESC LIMIT ?", (org, connection_id, limit),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM finding_verdicts WHERE org_id=? ORDER BY id DESC LIMIT ?",
                (org, limit),
            ).fetchall()
    finally:
        c.close()
    return [dict(r) for r in rows]


def list_corrections(connection_id: Optional[str] = None, limit: int = 20) -> list[dict]:
    """Recent verdicts that carry a *lesson* — ``reject`` (the finding was wrong) or
    ``correct`` (right direction, a detail was off). These are what the planner reads
    back as priors (P1 close-the-loop): an accepted finding teaches nothing new, but a
    rejected/corrected one names a mistake not to repeat. Org-scoped, most-recent-first."""
    org = current_org_id()
    limit = max(1, min(int(limit), 200))
    c = _conn()
    try:
        if connection_id:
            rows = c.execute(
                "SELECT * FROM finding_verdicts WHERE org_id=? AND connection_id=? "
                "AND verdict IN ('reject','correct') ORDER BY id DESC LIMIT ?",
                (org, connection_id, limit),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM finding_verdicts WHERE org_id=? "
                "AND verdict IN ('reject','correct') ORDER BY id DESC LIMIT ?",
                (org, limit),
            ).fetchall()
    finally:
        c.close()
    return [dict(r) for r in rows]
