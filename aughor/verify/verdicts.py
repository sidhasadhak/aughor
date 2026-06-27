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

_DB_PATH = Path(__file__).parent.parent.parent / "data" / "verdicts.db"

# accept = the finding is correct/useful · correct = right direction but a detail is wrong
# · reject = wrong or misleading. These are the labels the trust economy calibrates against.
VERDICTS = ("accept", "correct", "reject")


def _conn() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(_DB_PATH))
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
            created_at      TEXT NOT NULL
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS ix_verdicts_org_conn "
              "ON finding_verdicts (org_id, connection_id)")
    c.commit()


def record_verdict(
    connection_id: str,
    investigation_id: str,
    verdict: str,
    note: str = "",
    headline: str = "",
) -> dict:
    """Persist a human verdict on a finding. Raises ValueError on an invalid verdict label
    (the only failure the caller must handle); everything else is a normal insert."""
    v = (verdict or "").strip().lower()
    if v not in VERDICTS:
        raise ValueError(f"verdict must be one of {VERDICTS}, got {verdict!r}")
    org = current_org_id()
    now = _now()
    c = _conn()
    try:
        cur = c.execute(
            "INSERT INTO finding_verdicts "
            "(org_id, connection_id, investigation_id, verdict, note, headline, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (org, connection_id or "", investigation_id or "", v, note or "", headline or "", now),
        )
        c.commit()
        return {
            "id": cur.lastrowid, "org_id": org, "connection_id": connection_id or "",
            "investigation_id": investigation_id or "", "verdict": v,
            "note": note or "", "headline": headline or "", "created_at": now,
        }
    finally:
        c.close()


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
