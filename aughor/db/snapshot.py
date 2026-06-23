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
    (the version probe touches the DB). A runtime override (Settings → System) wins;
    otherwise ``AUGHOR_SNAPSHOT_RECEIPTS=1`` decides."""
    try:
        from aughor.kernel.flags import flag_enabled
        return flag_enabled("snapshot_receipts")
    except Exception:
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


def _ducklake_catalog(conn: Any) -> Optional[str]:
    """The name of an attached DuckLake catalog on this connection, or None. DuckLake keeps its
    tables in a versioned catalog that shows up as ``type = 'ducklake'`` in duckdb_databases()."""
    row = _meta_row(conn, "SELECT database_name FROM duckdb_databases() WHERE type = 'ducklake' LIMIT 1")
    return str(row[0]) if row else None


def _native_snapshot(conn: Any) -> Optional[str]:
    """The EXACT data version when the connection's storage is version-aware: the current
    DuckLake snapshot id as ``dl:<catalog>:<id>``. None on a plain DuckDB file — callers fall
    back to the fingerprint. This is the seam a warehouse time-travel token would also fill."""
    cat = _ducklake_catalog(conn)
    if not cat:
        return None
    row = _meta_row(conn, f"SELECT max(snapshot_id) FROM ducklake_snapshots('{cat}')")
    return f"dl:{cat}:{row[0]}" if row and row[0] is not None else None


def native_version_id(token: Optional[str]) -> Optional[int]:
    """The numeric snapshot id inside a native ``dl:<catalog>:<id>`` token, else None."""
    if token and token.startswith("dl:"):
        try:
            return int(token.rsplit(":", 1)[1])
        except (ValueError, IndexError):
            return None
    return None


def data_version(conn: Any, tables: Iterable[str]) -> Optional[str]:
    """A token identifying the data ``tables`` held when called — the EXACT native snapshot id
    (``dl:…``) if the storage is version-aware, else a portable fingerprint (``fp:…``) over the
    finding's tables. ``None`` when nothing is probeable (fail-open). Deterministic per dataset."""
    native = _native_snapshot(conn)
    if native:
        return native
    sigs = [s for t in sorted({str(x) for x in (tables or [])}) if (s := _table_signature(conn, t))]
    if not sigs:
        return None
    return "fp:" + hashlib.sha256("|".join(sigs).encode()).hexdigest()[:16]


def as_of_supported(conn: Any) -> bool:
    """True when ``conn`` can reproduce a query AT a past version (DuckLake time-travel). False
    on a plain DuckDB file — re-validate then disambiguates via the fingerprint comparison
    instead of an exact AT-VERSION reproduction."""
    return _ducklake_catalog(conn) is not None


def execute_as_of(conn: Any, sql: str, version: int) -> Any:
    """Reproduce a query AS IT WOULD HAVE RUN at a past DuckLake snapshot, by pinning every
    table to ``AT (VERSION => version)`` (sqlglot rewrite). Returns the QueryResult, or None on
    failure. Requires :func:`as_of_supported`; pins ALL tables, so mixed-catalog queries (a
    DuckLake table joined to a non-versioned one) aren't supported — caller falls back."""
    try:
        import sqlglot
        from sqlglot import exp
        tree = sqlglot.parse_one(sql, read="duckdb")
        # DuckDB time-travel parses into Table.args["when"] (a HistoricalData AT/VERSION node).
        when = sqlglot.parse_one(
            f"SELECT 1 FROM _t AT (VERSION => {int(version)})", read="duckdb"
        ).find(exp.Table).args["when"]
        pinned = 0
        for tbl in tree.find_all(exp.Table):
            tbl.set("when", when.copy())
            pinned += 1
        if not pinned:
            return None
        return conn.execute("__asof__", tree.sql(dialect="duckdb"))
    except Exception:
        return None
