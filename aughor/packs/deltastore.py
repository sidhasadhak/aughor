"""Proposed pack deltas (Bet 1 flywheel — the safe writeback).

A steered, VERIFIED run distills learnings (caveats, diagnostics) via flywheel.distill_deltas.
Rather than auto-mutate the pack folder, we PROPOSE them to this org-scoped store; a human
accepts or dismisses (the 'expert changelog' UI). That keeps the flywheel compounding without
letting an unattended loop rewrite an expert. Mirrors aughor/verify/verdicts.py.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from aughor.org.context import current_org_id
from aughor.util.time import now_iso as _now

_DB_PATH = Path(__file__).parent.parent.parent / "data" / "pack_deltas.db"


def _conn() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(_DB_PATH))
    c.row_factory = sqlite3.Row
    _ensure_schema(c)
    return c


def _ensure_schema(c: sqlite3.Connection) -> None:
    c.execute("""
        CREATE TABLE IF NOT EXISTS pack_deltas (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            org_id        TEXT NOT NULL,
            pack_id       TEXT NOT NULL,
            connection_id TEXT NOT NULL DEFAULT '',
            kind          TEXT NOT NULL,
            target        TEXT NOT NULL DEFAULT '',
            content       TEXT NOT NULL,
            source_run    TEXT NOT NULL DEFAULT '',
            confidence    REAL NOT NULL DEFAULT 0.5,
            status        TEXT NOT NULL DEFAULT 'proposed',
            created_at    TEXT NOT NULL
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS ix_deltas_org_pack ON pack_deltas (org_id, pack_id, status)")
    c.commit()


def record_deltas(pack_id: str, connection_id: str, deltas: list, source_run: str = "") -> int:
    """Persist proposed deltas (dedup by (pack,kind,target,content) within the org so the same
    learning from repeated runs isn't stored twice). Returns the count newly written."""
    if not deltas:
        return 0
    org = current_org_id()
    now = _now()
    written = 0
    c = _conn()
    try:
        for d in deltas:
            kind = getattr(d, "kind", "")
            target = getattr(d, "target", "")
            content = getattr(d, "content", "")
            if not content:
                continue
            dup = c.execute(
                "SELECT 1 FROM pack_deltas WHERE org_id=? AND pack_id=? AND kind=? AND target=? "
                "AND content=? AND status!='dismissed'",
                (org, pack_id, kind, target, content),
            ).fetchone()
            if dup:
                continue
            c.execute(
                "INSERT INTO pack_deltas (org_id, pack_id, connection_id, kind, target, content, "
                "source_run, confidence, status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (org, pack_id, connection_id or "", kind, target, content,
                 source_run or getattr(d, "source_run", ""), float(getattr(d, "confidence", 0.5)),
                 "proposed", now),
            )
            written += 1
        c.commit()
    finally:
        c.close()
    return written


def purge_connection(connection_id: str) -> int:
    """Delete every proposed/accepted delta tied to a connection in the current org
    (catalog delete cascade). Returns the number removed."""
    if not connection_id:
        return 0
    org = current_org_id()
    c = _conn()
    try:
        n = c.execute(
            "DELETE FROM pack_deltas WHERE org_id=? AND connection_id=?",
            (org, connection_id),
        ).rowcount
        c.commit()
        return n
    finally:
        c.close()


def list_deltas(pack_id: Optional[str] = None, status: str = "proposed") -> list[dict]:
    """Proposed (or other-status) deltas for the current org, newest first."""
    org = current_org_id()
    c = _conn()
    try:
        if pack_id:
            rows = c.execute("SELECT * FROM pack_deltas WHERE org_id=? AND pack_id=? AND status=? "
                             "ORDER BY id DESC", (org, pack_id, status)).fetchall()
        else:
            rows = c.execute("SELECT * FROM pack_deltas WHERE org_id=? AND status=? ORDER BY id DESC",
                             (org, status)).fetchall()
    finally:
        c.close()
    return [dict(r) for r in rows]


def set_delta_status(delta_id: int, status: str) -> bool:
    """Accept or dismiss a proposed delta. Returns True if a row changed."""
    if status not in ("proposed", "accepted", "dismissed"):
        raise ValueError(f"bad status {status!r}")
    org = current_org_id()
    c = _conn()
    try:
        cur = c.execute("UPDATE pack_deltas SET status=? WHERE id=? AND org_id=?",
                        (status, delta_id, org))
        c.commit()
        return cur.rowcount > 0
    finally:
        c.close()
