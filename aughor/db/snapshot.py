"""Data-version tokens for snapshot-pinned receipts (the DuckLake +1, spike).

A finding is computed against the data *as it was* at one instant. Today the Finding
Dossier pins the SQL + a frozen copy of the result cells, but not the DATA VERSION it
ran against — so when re-validate re-runs the SQL later and the number differs, it can't
tell "the finding was mis-derived" from "the data simply moved underneath it".

This module stamps a ``data_version`` token at emit so that gap closes:

  • native  — when the connection's storage is version-aware (DuckLake snapshot id, or a
    warehouse's time-travel token), that id IS the version. Exact, and pairs with an
    ``AT (VERSION => n)`` reproduction. ``_native_snapshot`` is the forward-compat seam;
    it returns None until a DuckLake/warehouse lane is wired.
  • fingerprint — the portable fallback that works on a plain DuckDB file TODAY: a cheap
    per-table signature over just the finding's tables. It moves when rows are appended,
    deleted, or the table is reloaded — the dominant real-world "data moved" cases. (A
    strict content hash would also catch equal-size in-place edits; the native snapshot
    id catches everything. The fingerprint trades that for being free + dialect-portable.)

Either way the receipt carries a token, and re-validate compares pinned-vs-current to
report ``data_moved`` honestly. OPT-IN (``AUGHOR_SNAPSHOT_RECEIPTS=1``, default off): the
per-table COUNT touches the DB, so an operator turns it on deliberately.
"""
from __future__ import annotations

import hashlib
import os
from typing import Any, Iterable, Optional


def snapshot_receipts_enabled() -> bool:
    """True when findings should be pinned to a data-version token at emit. Off by default
    (the version probe touches the DB); set ``AUGHOR_SNAPSHOT_RECEIPTS=1`` to turn it on."""
    return os.getenv("AUGHOR_SNAPSHOT_RECEIPTS", "").strip().lower() in ("1", "true", "yes", "on")


def _meta_row(conn: Any, sql: str) -> Optional[tuple]:
    """Run a tiny metadata query off the audit path; return the first row or None. Fail-open."""
    try:
        _cols, rows, _types = conn.raw_execute(sql)     # bypasses validation/security (metadata)
        return tuple(rows[0]) if rows else None
    except Exception:
        try:
            res = conn.execute("__snapshot__", sql)      # internal id → skips audit
            return tuple(res.rows[0]) if getattr(res, "rows", None) else None
        except Exception:
            return None


def _quote(table: str) -> str:
    """Quote a (possibly schema-qualified) table name for safe interpolation."""
    return ".".join(f'"{p.strip().strip(chr(34))}"' for p in str(table).split(".") if p.strip())


def _table_signature(conn: Any, table: str) -> Optional[str]:
    """Cheap per-table signature — row count today (moves on append/delete/reload). Returns
    ``"<table>=<count>"`` or None when the table can't be probed (fail-open, never raises)."""
    row = _meta_row(conn, f"SELECT COUNT(*) FROM {_quote(table)}")
    return f"{table}={row[0]}" if row else None


def _native_snapshot(conn: Any) -> Optional[str]:
    """Forward-compat seam: the storage layer's exact version id when version-aware
    (DuckLake snapshot id; a warehouse time-travel token). Returns None on a plain DuckDB
    file — today's lanes aren't version-aware, so callers fall back to the fingerprint."""
    return None


def data_version(conn: Any, tables: Iterable[str]) -> Optional[str]:
    """A token identifying the data ``tables`` held when called — the native snapshot id if
    the storage is version-aware, else a portable fingerprint over the finding's tables.
    ``None`` when nothing is probeable (fail-open). Deterministic for a fixed dataset."""
    native = _native_snapshot(conn)
    if native:
        return f"snap:{native}"
    sigs = [s for t in sorted({str(x) for x in (tables or [])}) if (s := _table_signature(conn, t))]
    if not sigs:
        return None
    return "fp:" + hashlib.sha256("|".join(sigs).encode()).hexdigest()[:16]


def as_of_supported(conn: Any) -> bool:
    """True when ``conn`` can reproduce a query AT a past version (DuckLake time-travel /
    warehouse). False on a plain DuckDB file — re-validate then disambiguates via the
    fingerprint comparison instead of an exact AT-VERSION reproduction. Forward-compat hook."""
    return _native_snapshot(conn) is not None
