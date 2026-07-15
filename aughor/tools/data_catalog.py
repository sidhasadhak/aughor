"""Structured Data Catalog builder for Aughor.

Builds a compact, markdown-formatted catalog from a database connection
for a given set of tables. Caches results by (connection_id, table_hash)
with LRU eviction and TTL expiry.

Inspired by MindsDB DataCatalogBuilder:
- ≤5-row samples per table
- Exact column-name case preservation
- Relevance-filtered (only requested tables)
"""
from __future__ import annotations

import hashlib
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aughor.db.connection import DatabaseConnection

# In-memory cache: key → (timestamp, catalog_string)
_cache: dict[str, tuple[float, str]] = {}
_MAX_ENTRIES = 50
_TTL_SECONDS = 3600  # 1 hour


def _cache_key(connection_id: str, tables: list[str]) -> str:
    table_hash = hashlib.md5(",".join(sorted(tables)).encode()).hexdigest()
    return f"{connection_id}:{table_hash}"


def _evict_stale() -> None:
    now = time.time()
    expired = [k for k, (ts, _) in _cache.items() if now - ts > _TTL_SECONDS]
    for k in expired:
        del _cache[k]
    # LRU eviction if still over limit
    if len(_cache) > _MAX_ENTRIES:
        sorted_items = sorted(_cache.items(), key=lambda x: x[1][0])
        for k, _ in sorted_items[: len(_cache) - _MAX_ENTRIES]:
            del _cache[k]


def build_data_catalog(conn: "DatabaseConnection", tables: list[str]) -> str:
    """Build a markdown Data Catalog for the given tables.

    Returns a compact markdown string with column definitions + 5-row samples.
    Uses exact column case from the database. Caches by (conn_id, table_list_hash).
    """
    conn_id = getattr(conn, "_connection_id", "") or "unknown"
    key = _cache_key(conn_id, tables)

    _evict_stale()
    if key in _cache:
        return _cache[key][1]

    parts: list[str] = []
    catalog_cols: dict[str, list[str]] = {}
    for table in tables:
        try:
            # Get column info — try PRAGMA first (DuckDB), fallback to SHOW COLUMNS
            col_rows = _fetch_columns(conn, table)
            if not col_rows:
                continue

            # Build markdown table header
            lines = [f"## {table}", ""]
            lines.append("| Column | Type | Nullable |")
            lines.append("|---|---|---|")

            col_names: list[str] = []
            for col_name, col_type, nullable in col_rows:
                # Preserve exact case from DB
                null_str = "YES" if nullable else "NO"
                lines.append(f"| {col_name} | {col_type} | {null_str} |")
                col_names.append(col_name)
            catalog_cols[table] = col_names

            # Sample 5 rows
            sample_rows = _fetch_sample(conn, table, col_names)
            if sample_rows:
                lines.append("")
                lines.append("Sample (5 rows):")
                header = "| " + " | ".join(col_names) + " |"
                lines.append(header)
                lines.append("|" + "|".join("---" for _ in col_names) + "|")
                for row in sample_rows:
                    cells = []
                    for v in row:
                        s = str(v) if v is not None else "NULL"
                        # Escape pipe characters in cell values
                        s = s.replace("|", "\\|")
                        cells.append(s)
                    lines.append("| " + " | ".join(cells) + " |")

            parts.append("\n".join(lines))
        except Exception:
            # Skip tables we can't read — don't let one bad table kill the catalog
            continue

    catalog = "\n\n".join(parts)

    # Append detected foreign-key joins among these tables. Without this the
    # catalog has no relational structure and the model invents wrong join paths
    # on multi-table questions (verified on TPC-H Q5/Q10).
    try:
        from aughor.tools.schema import compute_join_map
        jmap = compute_join_map(catalog_cols)
        if jmap.get("joins"):
            # PREVENTION: value-verify the name-inferred join edges at (catalog) build time —
            # demote a value-disjoint name coincidence to an explicit DO-NOT-JOIN so the model
            # never draws it. Cached per connection (probes run on catalog cache-miss only);
            # fail-open to the name-only list if verification can't run.
            from aughor.sql.join_guard import verified_join_edges, render_verified_joins
            verified, rejected = verified_join_edges(conn, jmap["joins"], cache_key=conn_id or "")
            block = render_verified_joins(verified, rejected)
            if not block:
                block = "\n".join(
                    ["FOREIGN KEY JOINS (use these exact keys to join the tables above):"]
                    + [f"  {j['t1']}.{j['c1']} = {j['t2']}.{j['c2']}" for j in jmap["joins"]])
            catalog += "\n\n" + block
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "FK-join enrichment is best-effort; the catalog omits join hints on failure",
                 counter="catalog.join_map", conn_id=conn_id or None)

    # Surrogate-key guidance: if any table exposes a *_date_sk / *_time_sk column,
    # tell the model these are DIMENSION keys, not literal dates. Without this the
    # model writes `ss_sold_date_sk = 2451843` or treats a time key as seconds
    # (verified on TPC-DS Q52/Q55/Q96).
    try:
        import re as _re
        _dt = _re.compile(r"_(date|time)_(sk|key|id)$", _re.IGNORECASE)
        if any(_dt.search(c) for cols in catalog_cols.values() for c in cols):
            catalog += (
                "\n\nNOTE: columns ending in _date_sk / _time_sk are SURROGATE KEYS into a "
                "date/time dimension (e.g. date_dim, time_dim). To filter or group by calendar "
                "values, JOIN that dimension on the key (fact._date_sk = date_dim.d_date_sk) and "
                "use its columns (year, month, day, hour) — NEVER compare a _sk column to a "
                "literal date, timestamp, or number."
            )
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "surrogate-key guidance is best-effort; omitted on failure",
                 counter="catalog.surrogate_key", conn_id=conn_id or None)

    _cache[key] = (time.time(), catalog)
    return catalog


def _quote_ref(table: str) -> str:
    """Quote a possibly schema-qualified table name part-by-part.

    "ecommerce.orders" → '"ecommerce"."orders"' so multi-schema DuckDB resolves it,
    rather than treating the whole dotted string as one identifier.
    """
    parts = [p for p in table.split(".") if p]
    return ".".join(f'"{p}"' for p in parts) if parts else f'"{table}"'


def _raw_rows(conn: "DatabaseConnection", sql: str) -> tuple[list[str], list]:
    """Run a metadata query, preferring raw_execute (bypasses the SELECT-only
    validator that rejects PRAGMA/DESCRIBE) and falling back to execute()."""
    if getattr(conn, "dialect", "") == "duckdb" and hasattr(conn, "raw_execute"):
        cols, rows, _ = conn.raw_execute(sql)
        return cols, rows
    result = conn.execute("_catalog", sql)
    return list(getattr(result, "columns", []) or []), list(result.rows)


def _fetch_columns(conn: "DatabaseConnection", table: str) -> list[tuple[str, str, bool]]:
    """Return [(col_name, col_type, nullable), ...] preserving exact DB case."""
    ref = _quote_ref(table)

    # 1. DESCRIBE — most reliable for DuckDB/MotherDuck across attached DBs.
    try:
        _, rows = _raw_rows(conn, f"DESCRIBE {ref}")
        if rows:
            # DESCRIBE → [column_name, column_type, null, key, default, extra]
            return [
                (str(r[0]), str(r[1]) if len(r) > 1 else "",
                 (str(r[2]).upper() != "NO") if len(r) > 2 else True)
                for r in rows
            ]
    except Exception:
        pass

    # 2. PRAGMA table_info → [cid, name, type, notnull, dflt_value, pk]
    try:
        _, rows = _raw_rows(conn, f"PRAGMA table_info({ref})")
        if rows:
            return [(str(r[1]), str(r[2]), not bool(r[3])) for r in rows]
    except Exception:
        pass

    # 3. information_schema.columns (standard SQL — Postgres and others)
    try:
        parts = [p for p in table.split(".") if p]
        tname = parts[-1].replace("'", "''")
        where = f"table_name = '{tname}'"
        if len(parts) > 1:
            where += f" AND table_schema = '{parts[-2]}'"
        _, rows = _raw_rows(
            conn,
            "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
            f"WHERE {where} ORDER BY ordinal_position",
        )
        if rows:
            return [
                (str(r[0]), str(r[1]) if r[1] is not None else "",
                 (str(r[2]).upper() != "NO") if len(r) > 2 else True)
                for r in rows
            ]
    except Exception:
        pass

    return []


def _fetch_sample(
    conn: "DatabaseConnection", table: str, col_names: list[str]
) -> list[list]:
    """Fetch up to 5 sample rows, returning raw values."""
    if not col_names:
        return []
    quoted_cols = ", ".join(f'"{c}"' for c in col_names)
    try:
        # Plain SELECT passes the validator — use the safe execute() path.
        result = conn.execute("_catalog", f"SELECT {quoted_cols} FROM {_quote_ref(table)} LIMIT 5")
        return result.rows
    except Exception:
        return []


def clear_cache() -> None:
    """Clear the in-memory Data Catalog cache. Useful for testing."""
    _cache.clear()

def enforce_context_cap(schema_or_catalog: str, max_tables: int = 10) -> str:
    """Hard cap on schema context size — MindsDB best practice.

    Counts TABLE: headers. If > max_tables, keeps only the first N tables
    and appends a truncation notice. Preserves exact case.
    """
    import re
    lines = schema_or_catalog.splitlines()
    table_starts: list[int] = []
    for i, line in enumerate(lines):
        if re.match(r"^TABLE:\s+", line):
            table_starts.append(i)

    if len(table_starts) <= max_tables:
        return schema_or_catalog

    # Keep only first max_tables
    cutoff = table_starts[max_tables]
    kept = lines[:cutoff]
    notice = (
        f"\n\n[CONTEXT CAP: {len(table_starts)} tables available; "
        f"only top {max_tables} shown to prevent attention dilution.]"
    )
    return "\n".join(kept) + notice

