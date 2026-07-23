"""Wave K3 — the edits-as-overlay ledger.

A human annotation or correction on the data ("this outlier is a known launch-day spike";
"order 8821's status is a test order") is written here and MERGED AT READ TIME onto query
results — it never mutates the source. It generalizes the ambiguity ledger from *resolutions*
to *data annotations*, sharing its store idiom exactly (SQLite via `resolve_db_path` so the
suite never touches live `data/`; org+connection scoped; forward-only migrations) and its
override-wins authority: a machine-sourced edit never clobbers a human one on the same target.

Because the store is independent of the connection's data cache, an overlay SURVIVES a refresh/
rebuild by construction — the merge re-applies on every read. Grain is the cell, the column, or
the whole table; the read-time merge matches by the columns actually present in a result, so it
is precise for cell/column edits and best-effort (a caveat) for table-grain.
"""
from __future__ import annotations

import hashlib
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from aughor.db.migrations import run_migrations
from aughor.db.sqlite_util import resolve_db_path, tune

_LOCK = threading.Lock()
_DB_PATH = resolve_db_path(
    "AUGHOR_OVERLAY_LEDGER_DB",
    Path(__file__).parent.parent.parent / "data" / "overlay_ledger.db",
)

# Edit authority — override-wins, mirroring the ambiguity ledger: a human-verified correction
# beats a plain user note, which beats a machine-suggested annotation. A re-write of the same
# target only lands when it arrives with >= authority, so machinery never clobbers a human edit.
_SOURCE_RANK = {"machine": 1, "user": 2, "verified": 3}

_MIGRATIONS: list = []  # forward-only; append Migration(2, ...) when the schema evolves


class OverlayEdit(BaseModel):
    """One human edit over the data, merged at read time (never written to source)."""
    connection_id: str
    org_id: str = ""
    table: str                              # table the edit is about (lowercased on save)
    column: str = ""                        # annotated column ('' ⇒ whole-table edit)
    row_key: str = ""                       # value identifying the row ('' ⇒ whole-column edit)
    key_column: str = ""                    # column whose value equals row_key (defaults to `column`)
    kind: str = "annotation"                # annotation | correction
    body: str = ""                          # the human text (annotation) or corrected value (correction)
    source: str = "user"                    # machine | user | verified
    id: str = ""                            # deterministic natural-key hash (auto)
    created_at: str = ""
    last_used_at: Optional[str] = None
    use_count: int = 0

    def target(self) -> str:
        """Canonical address — the dedup grain. ``table`` | ``table.column`` | ``table.column#kc=rk``."""
        t = self.table
        if self.column:
            t += f".{self.column}"
        if self.row_key:
            t += f"#{self.key_column or self.column}={self.row_key}"
        return t

    def natural_key(self) -> str:
        raw = f"{self.org_id}|{self.connection_id}|{self.target()}"
        return hashlib.sha1(raw.encode()).hexdigest()[:20]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _conn() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = tune(sqlite3.connect(str(_DB_PATH)))
    c.row_factory = sqlite3.Row
    _ensure_schema(c)
    return c


def _ensure_schema(c: sqlite3.Connection) -> None:
    c.execute("""
        CREATE TABLE IF NOT EXISTS overlay_edits (
            id             TEXT PRIMARY KEY,
            org_id         TEXT NOT NULL DEFAULT '',
            connection_id  TEXT NOT NULL,
            "table"        TEXT NOT NULL,
            column         TEXT NOT NULL DEFAULT '',
            row_key        TEXT NOT NULL DEFAULT '',
            key_column     TEXT NOT NULL DEFAULT '',
            kind           TEXT NOT NULL DEFAULT 'annotation',
            body           TEXT NOT NULL DEFAULT '',
            source         TEXT NOT NULL DEFAULT 'user',
            created_at     TEXT NOT NULL,
            last_used_at   TEXT,
            use_count      INTEGER NOT NULL DEFAULT 0
        )
    """)
    c.execute('CREATE INDEX IF NOT EXISTS ix_overlay_conn ON overlay_edits (org_id, connection_id)')
    c.execute('CREATE INDEX IF NOT EXISTS ix_overlay_table ON overlay_edits (connection_id, "table")')
    run_migrations(c, _MIGRATIONS, store="overlay_ledger")
    c.commit()


def _row_to_edit(row: sqlite3.Row) -> OverlayEdit:
    return OverlayEdit(**dict(row))


# ── write path (authority-gated) ───────────────────────────────────────────────

def save_edit(edit: OverlayEdit) -> OverlayEdit:
    """Persist an overlay edit (idempotent by natural key). A re-edit of the same target updates
    the same row and **only overwrites when it arrives with >= authority** (verified > user >
    machine), so a machine annotation never clobbers a human one. created_at/use_count survive."""
    edit.table = (edit.table or "").strip().lower()
    if not edit.org_id:
        # Stamp the current tenant so an edit is found by a read in the same org — the reader
        # scopes by current_org_id(), so an unstamped ('') edit would be orphaned (a real bug the
        # end-to-end path caught: the unit merge worked only because it mocked the org to '').
        from aughor.org.context import current_org_id
        edit.org_id = current_org_id()
    edit.id = edit.id or edit.natural_key()   # natural_key hashes org_id — stamp it FIRST
    edit.created_at = edit.created_at or _now()
    with _LOCK:
        c = _conn()
        try:
            existing = c.execute(
                "SELECT source, created_at, use_count FROM overlay_edits WHERE id=?",
                (edit.id,)).fetchone()
            if existing is not None:
                if _SOURCE_RANK.get(edit.source, 0) < _SOURCE_RANK.get(existing["source"], 0):
                    return _row_to_edit(c.execute(
                        "SELECT * FROM overlay_edits WHERE id=?", (edit.id,)).fetchone())
                edit.created_at = existing["created_at"]
                edit.use_count = existing["use_count"]
            c.execute("""
                INSERT OR REPLACE INTO overlay_edits
                    (id, org_id, connection_id, "table", column, row_key, key_column,
                     kind, body, source, created_at, last_used_at, use_count)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (edit.id, edit.org_id, edit.connection_id, edit.table, edit.column,
                  edit.row_key, edit.key_column, edit.kind, edit.body, edit.source,
                  edit.created_at, edit.last_used_at, edit.use_count))
            c.commit()
            return edit
        finally:
            c.close()


def edits_for_connection(connection_id: str, org_id: str = "") -> list[OverlayEdit]:
    if not connection_id:
        return []
    with _LOCK:
        c = _conn()
        try:
            q = "SELECT * FROM overlay_edits WHERE connection_id = ?"
            args: tuple = (connection_id,)
            if org_id:
                q += " AND org_id = ?"
                args += (org_id,)
            q += " ORDER BY created_at DESC"
            return [_row_to_edit(r) for r in c.execute(q, args).fetchall()]
        finally:
            c.close()


def purge_connections(connection_ids: list[str], org_id: Optional[str] = None) -> int:
    """Catalog-delete cascade — drop every overlay edit for the given connections. Returns the
    rows removed (observable, per the purge-hook contract)."""
    if not connection_ids:
        return 0
    placeholders = ",".join("?" for _ in connection_ids)
    with _LOCK:
        c = _conn()
        try:
            sql = f"DELETE FROM overlay_edits WHERE connection_id IN ({placeholders})"
            args = list(connection_ids)
            if org_id is not None:
                sql += " AND org_id = ?"
                args.append(org_id)
            n = c.execute(sql, args).rowcount
            c.commit()
            return n
        finally:
            c.close()


# ── read-time merge ─────────────────────────────────────────────────────────────

def apply_overlay(result, connection_id: str, org_id: str = "") -> "object":
    """Merge this connection's overlay edits onto a ``QueryResult`` IN PLACE (and return it).

    Matching is by the columns actually present in the result — precise for cell and column
    grain, best-effort (a caveat, matched against the SQL text) for whole-table edits. Never
    raises: an overlay hiccup must never take down a real result."""
    try:
        if not connection_id or not getattr(result, "columns", None):
            return result
        if not org_id:
            from aughor.org.context import current_org_id
            org_id = current_org_id()
        edits = edits_for_connection(connection_id, org_id)
        if not edits:
            return result

        # case-insensitive column-name → index
        col_idx = {str(c).lower(): i for i, c in enumerate(result.columns)}
        # last segment of a possibly-qualified column ("orders.status" → "status")
        for name, i in list(col_idx.items()):
            col_idx.setdefault(name.split(".")[-1], i)
        sql_lower = (getattr(result, "sql", "") or "").lower()
        anns: list[dict] = []

        for e in edits:
            entry = {"target": e.target(), "kind": e.kind, "body": e.body,
                     "source": e.source, "column": e.column or None}
            if e.column and e.row_key:
                # cell grain — need both the annotated column and the key column present
                kc = (e.key_column or e.column).lower()
                ci, ki = col_idx.get(e.column.lower()), col_idx.get(kc)
                if ci is None or ki is None:
                    continue
                for ridx, row in enumerate(result.rows):
                    if ki < len(row) and str(row[ki]) == e.row_key:
                        anns.append({**entry, "row_index": ridx})
            elif e.column:
                # column grain — annotate the whole column when it is in the result
                if e.column.lower() in col_idx:
                    anns.append({**entry, "row_index": None})
            else:
                # table grain — a coarse caveat when the SQL references the table
                if e.table and e.table in sql_lower:
                    result.caveats = list(dict.fromkeys([*result.caveats, f"[{e.table}] {e.body}"]))

        if anns:
            existing = list(getattr(result, "annotations", []) or [])
            result.annotations = existing + anns
        return result
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "overlay merge is advisory; result proceeds", counter="kinetic.overlay_merge")
        return result
