"""Structured Data Catalog builder for Aughor.

Builds a compact, markdown-formatted catalog from a database connection
for a given set of tables. Caches results by (connection_id, table_hash)
with LRU eviction and TTL expiry.

Design constraints:
- ≤5-row samples per table
- Exact column-name case preservation
- Relevance-filtered (only requested tables)
- **Column config is authoritative** (R11, ``ontology/column_config.py``): a column with
  ``visible: false`` is not rendered at all, and a column with ``sample: false`` has its
  VALUES withheld — the column and its type still appear. Until 2026-08-15 this builder
  read samples straight from the DB and never consulted the config, so the deep path
  bypassed the one switch that exists for this: a deep-analysis run shipped 9 credit-card numbers,
  5 e-mail addresses and 2 phone numbers to a third-party model, all from columns already
  marked ``sample: false``. The ``/ask`` renderer had honoured it since R11
  (``tools/schema.apply_schema_enrichment``); only the catalog did not.
- Sample cells are truncated (``_MAX_CELL_CHARS``). Untruncated cells are how two
  multi-paragraph review tables became 29% of a 28.5k-char airline-outlier prompt.
"""
from __future__ import annotations

import hashlib
import re
import time
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from aughor.db.connection import DatabaseConnection

# In-memory cache: key → (timestamp, catalog_string)
_cache: dict[str, tuple[float, str]] = {}
_MAX_ENTRIES = 50
_TTL_SECONDS = 3600  # 1 hour

#: Longest sample cell rendered into the catalog. A sample exists to show the SHAPE of a
#: value (format, unit, spelling) — that is legible well inside 200 chars, and everything
#: past it is a free-text blob crowding out the tables the question is actually about.
_MAX_CELL_CHARS = 200


def _cache_key(connection_id: str, tables: list[str], config_fingerprint: str = "") -> str:
    table_hash = hashlib.md5(",".join(sorted(tables)).encode()).hexdigest()
    # The config is part of the OUTPUT, so it must be part of the key: without this,
    # turning `sample` off on a column would leave the previously-cached catalog — the
    # one still carrying its values — serving for the next hour.
    return f"{connection_id}:{table_hash}:{config_fingerprint}"


def _column_policy(
    connection_id: str, tables: list[str], schema: Optional[str],
) -> tuple[set[tuple[str, str]], set[tuple[str, str]], str]:
    """Resolve (hidden, values_withheld, fingerprint) for these tables, keyed by
    ``(table_lower, column_lower)``.

    Config is stored per ``{connection}/{schema}``; a schema-qualified table name carries
    its own schema, and anything bare falls back to ``schema`` (the caller's effective
    schema) then ``"default"`` — the same resolution ``apply_schema_enrichment`` uses.
    Matching is on the BARE table name, so ``main.flights`` finds ``flights.yaml``.
    Fail-open: an unreadable store must not empty the catalog, only unguard it — which is
    why the counter below exists rather than a silent ``except: pass``."""
    hidden: set[tuple[str, str]] = set()
    withheld: set[tuple[str, str]] = set()
    if not connection_id:
        return hidden, withheld, ""
    try:
        from aughor.ontology.column_config import load_column_configs
        schemas = {(t.split(".")[-2] if "." in t else (schema or "default")) for t in tables}
        for sch in sorted(s for s in schemas if s):
            for (tbl, col), flags in load_column_configs(connection_id, sch).items():
                key = (tbl.split(".")[-1].lower(), col.lower())
                if not flags.visible:
                    hidden.add(key)
                if not flags.sample or not flags.visible:
                    withheld.add(key)
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "column-config lookup failed; the catalog renders unfiltered samples",
                 counter="catalog.column_config", conn_id=connection_id or None)
        return set(), set(), "unfiltered"
    fingerprint = hashlib.md5(
        ("|".join(sorted(f"h:{t}.{c}" for t, c in hidden))
         + "#" + "|".join(sorted(f"w:{t}.{c}" for t, c in withheld))).encode()
    ).hexdigest()[:12]
    return hidden, withheld, fingerprint


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


def build_data_catalog(
    conn: "DatabaseConnection",
    tables: list[str],
    *,
    schema: Optional[str] = None,
) -> str:
    """Build a markdown Data Catalog for the given tables.

    Returns a compact markdown string with column definitions + 5-row samples, filtered
    by the connection's per-column config (see the module docstring). ``schema`` is the
    caller's effective schema, used to locate that config for unqualified table names.
    Uses exact column case from the database. Caches by (conn_id, tables, config).
    """
    conn_id = getattr(conn, "_connection_id", "") or "unknown"
    hidden, withheld, cfg_fp = _column_policy(conn_id, tables, schema)
    key = _cache_key(conn_id, tables, cfg_fp)

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
            bare = table.split(".")[-1].lower()

            # Build markdown table header
            lines = [f"## {table}", ""]
            lines.append("| Column | Type | Nullable |")
            lines.append("|---|---|---|")

            col_names: list[str] = []
            for col_name, col_type, nullable in col_rows:
                if (bare, col_name.lower()) in hidden:
                    continue      # visible:false — the column does not exist for the model
                # Preserve exact case from DB
                null_str = "YES" if nullable else "NO"
                lines.append(f"| {col_name} | {col_type} | {null_str} |")
                col_names.append(col_name)
            if not col_names:
                continue
            catalog_cols[table] = col_names

            # Sample 5 rows — of the SAMPLEABLE columns only. Withheld columns are never
            # even SELECTed, so their values do not enter this process, its logs, or this
            # cache: the leak is closed at the query, not at the renderer.
            sample_cols = [c for c in col_names if (bare, c.lower()) not in withheld]
            no_sample = [c for c in col_names if (bare, c.lower()) in withheld]
            sample_rows = _fetch_sample(conn, table, sample_cols) if sample_cols else []
            if sample_rows:
                lines.append("")
                lines.append("Sample (5 rows):")
                header = "| " + " | ".join(sample_cols) + " |"
                lines.append(header)
                lines.append("|" + "|".join("---" for _ in sample_cols) + "|")
                for row in sample_rows:
                    cells = []
                    for v in row:
                        s = str(v) if v is not None else "NULL"
                        if len(s) > _MAX_CELL_CHARS:
                            s = s[:_MAX_CELL_CHARS] + "…[truncated]"
                        # Escape pipe characters in cell values
                        s = s.replace("|", "\\|")
                        cells.append(s)
                    lines.append("| " + " | ".join(cells) + " |")
            if no_sample:
                # Say it out loud: an omitted column is a withheld value, NOT an empty
                # one, and a model told nothing would reasonably infer the latter.
                lines.append("")
                lines.append("Sample values withheld by column config (the columns exist "
                             "and hold data): " + ", ".join(no_sample))

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


def table_columns(conn: "DatabaseConnection", table: str) -> list[tuple[str, str, bool]]:
    """``[(name, type, nullable), ...]`` for one table, exact DB case preserved.

    The public face of :func:`_fetch_columns`. Declared because a second plane needs it:
    the deep path resolves a join key by asking what two tables actually share
    (`agent/investigate._association_from_clause`), and reaching for the private name
    tripped the private-cross-import ratchet — which is the ratchet doing its job. An
    internal that two planes need is an interface nobody had declared yet.
    """
    return _fetch_columns(conn, table)


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

    # 3. INFORMATION_SCHEMA.COLUMNS (standard SQL — Postgres and others)
    try:
        parts = [p for p in table.split(".") if p]
        tname = parts[-1].replace("'", "''")
        where = f"table_name = '{tname}'"
        if len(parts) > 1:
            where += f" AND table_schema = '{parts[-2]}'"
        _, rows = _raw_rows(
            conn,
            "SELECT column_name, data_type, is_nullable FROM INFORMATION_SCHEMA.COLUMNS "
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
    # Double every embedded quote: column names reach here from user-supplied file
    # headers, and `_quote_ref` guards only the TABLE name. An unescaped `"` in a
    # header closes the identifier and the rest of the cell executes as SQL.
    quoted_cols = ", ".join('"' + str(c).replace('"', '""') + '"' for c in col_names)
    try:
        # Plain SELECT passes the validator — use the safe execute() path.
        result = conn.execute("_catalog", f"SELECT {quoted_cols} FROM {_quote_ref(table)} LIMIT 5")
        return result.rows
    except Exception:
        return []


def clear_cache() -> None:
    """Clear the in-memory Data Catalog cache. Useful for testing."""
    _cache.clear()

#: A table header in either dialect this function is handed: ``TABLE: name`` from the raw
#: schema renderer, ``## name`` from :func:`build_data_catalog`. It only ever matched the
#: first, so on a CATALOG — the one input that costs 5 sample rows a table — every call
#: was a silent no-op: both the /chat and deep-analysis paths capped, found "0 tables", and shipped
#: all 23. The guard existed, was called, and had been blind since the catalog was built.
_TABLE_HEADER = re.compile(r"^(?:TABLE:\s+|##\s+)\S")


def enforce_context_cap(schema_or_catalog: str, max_tables: int = 10) -> str:
    """Hard cap on schema context size.

    Counts table headers in either dialect (``TABLE:`` / ``##``). If > max_tables, keeps
    only the first N tables and appends a truncation notice. Preserves exact case.

    This is the BACKSTOP: trailing blocks appended after the last table (FK join hints,
    surrogate-key guidance) fall outside the kept region and are cut with it. Callers
    should cap the table LIST before building — see
    :func:`aughor.tools.schema_linker.rank_tables_for_context` — so this never fires.
    """
    lines = schema_or_catalog.splitlines()
    table_starts: list[int] = []
    for i, line in enumerate(lines):
        if _TABLE_HEADER.match(line):
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

