"""Per-connection notability priors learned from overview "explore this fact" drills.

The overview tour is deterministic — the same schema always yields the same ranked
facts. But WHICH facts a user finds worth drilling into is signal the tour should learn
from: if someone keeps exploring concentration facts on the ``orders`` table, those
deserve a nudge up the next time they open the overview on that connection.

This is the capture + read-back of that loop (the boost math lives in ``build.py``):
  * :func:`record_drill` — a user drilled a card; bump two counters, one for its LENS
    and one for its TABLE (the granularity the tour re-ranks on).
  * :func:`load_priors` — the accumulated counts, read at build time and folded into a
    BOUNDED notability boost so a well-liked lens/table is promoted in close calls but
    never overrides a genuinely notable deterministic fact.

Per-connection and best-effort: a store hiccup degrades to "no prior" (the plain
deterministic tour), never an error on the capture or the overview path.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from aughor.db.sqlite_util import resolve_db_path, tune

_DB_PATH = resolve_db_path(
    "AUGHOR_OVERVIEW_DRILLS_DB",
    Path(__file__).parent.parent.parent / "data" / "overview_drills.db",
)


def _conn() -> sqlite3.Connection:
    c = tune(sqlite3.connect(_DB_PATH))
    c.row_factory = sqlite3.Row
    _ensure_schema(c)
    return c


def _ensure_schema(c: sqlite3.Connection) -> None:
    # Two counter KINDS per connection ('lens', 'table') so the tour can weight the two
    # independently; a composite PK makes each bump an idempotent UPSERT.
    c.execute(
        "CREATE TABLE IF NOT EXISTS overview_drills ("
        " connection_id TEXT NOT NULL,"
        " kind TEXT NOT NULL,"
        " key TEXT NOT NULL,"
        " count INTEGER NOT NULL DEFAULT 0,"
        " PRIMARY KEY (connection_id, kind, key))"
    )


def record_drill(connection_id: str, lens: str = "", table: str = "") -> None:
    """A user drilled an overview card — bump the (lens) and (table) counters for this
    connection. Best-effort: never raises on the capture path."""
    pairs = [(k, v) for k, v in (("lens", lens), ("table", table)) if v]
    if not connection_id or not pairs:
        return
    try:
        c = _conn()
        for kind, key in pairs:
            c.execute(
                "INSERT INTO overview_drills (connection_id, kind, key, count) VALUES (?, ?, ?, 1) "
                "ON CONFLICT(connection_id, kind, key) DO UPDATE SET count = count + 1",
                (connection_id, kind, key))
        c.commit()
        c.close()
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "overview drill capture is best-effort; a miss just skips one prior bump",
                 counter="overview.drill_capture", conn_id=connection_id)


def load_priors(connection_id: str) -> dict:
    """The per-connection drill counts as ``{"lens": {name: n}, "table": {name: n}}``.
    Empty buckets when nothing has been drilled (or on any read error) → no prior nudge."""
    out: dict = {"lens": {}, "table": {}}
    if not connection_id:
        return out
    try:
        c = _conn()
        for row in c.execute(
                "SELECT kind, key, count FROM overview_drills WHERE connection_id = ?",
                (connection_id,)).fetchall():
            bucket = out.get(row["kind"])
            if bucket is not None:
                bucket[row["key"]] = int(row["count"])
        c.close()
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "overview prior read is best-effort; degrading to the plain deterministic tour",
                 counter="overview.prior_read", conn_id=connection_id)
    return out
