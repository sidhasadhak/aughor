"""Raw schema rendering + pure schema-string helpers — the PLATFORM half of what
used to live entirely in ``aughor/tools/schema.py`` (agent).

The platform must be able to render a connection's schema and parse a schema string
*without importing the agent*. Everything here is either raw introspection (reads
``information_schema`` / ``DESCRIBE`` + the platform-owned user annotations and type
overrides) or a pure string function — no glossary, ontology, profiling, or vector
index. The agent's rich enrichment (glossary, metrics, join hints, ontology,
exploration) is layered on top via the schema-annotator registry and
``tools/schema.build_schema_context`` (which delegates its raw half here).
"""
from __future__ import annotations

import re

import duckdb

# Columns whose names indicate they are IDs/keys — skip value sampling for these.
_KEY_COL = re.compile(
    r"(_id|_key|_code|_num|_number|_identifier|_pk|_uuid|_guid)$",
    re.IGNORECASE,
)

# Strips these suffixes (longest first) to get the semantic "root" of a key column.
_ROOT_SUFFIXES = sorted(
    ["_identifier", "_number", "_pseudonym", "_code", "_num", "_key", "_id", "_sk"],
    key=len, reverse=True,
)

# Short table-name alias prefix some schemas put on every column (TPC-H c_custkey).
_TABLE_PREFIX = re.compile(r"^[a-z]{1,3}_")

# Section headers that terminate a TABLE: block when parsing a schema string.
_SECTION_STOP = re.compile(
    r"^(DETECTED JOIN|NO DIRECT JOIN|METRICS CATALOG|Date range|GLOSSARY|JOIN HINTS|RELEVANT|--)"
)


def render_raw_schema(
    conn: duckdb.DuckDBPyConnection,
    schema_name: str | None = None,
    connection_id: str | None = None,
) -> str:
    """The raw, agent-free schema description: tables + row counts + columns (with
    user annotations and type overrides) + low-cardinality value enumerations + a
    no-date-column flag + the kpi_daily date range. This is the body of the former
    ``build_schema_context`` *before* glossary/metrics/join-hint enrichment, so the
    agent's tail re-applied on top of this produces a byte-identical result."""
    if schema_name:
        # For MotherDuck (multi-database DuckDB), restrict to the current database
        # so we don't bleed tables from other attached databases that share the schema.
        current_db = ""
        try:
            current_db = conn.execute("SELECT current_database()").fetchone()[0]
        except Exception:
            pass
        if current_db:
            tables = [
                row[0] for row in conn.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = ? AND table_type = 'BASE TABLE' "
                    "AND table_catalog = ? ORDER BY table_name",
                    [schema_name, current_db],
                ).fetchall()
            ]
        else:
            tables = [
                row[0] for row in conn.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = ? AND table_type = 'BASE TABLE' ORDER BY table_name",
                    [schema_name],
                ).fetchall()
            ]
        # Fallback: the user may have set schema_name to a database name
        # (common with MotherDuck) rather than a DuckDB schema. In that case,
        # information_schema.tables returns nothing — fall back to SHOW TABLES.
        if not tables:
            tables = [row[0] for row in conn.execute("SHOW TABLES").fetchall()]
    else:
        tables = [row[0] for row in conn.execute("SHOW TABLES").fetchall()]
    parts: list[str] = []

    # Use fully-qualified names when schema is known so queries work even if
    # SET search_path silently failed (DuckDB version differences).
    def _fqn(t: str) -> str:
        return f"{schema_name}.{t}" if schema_name else t

    # Load user-authored annotations (table + column descriptions) if available
    from aughor.db.annotations import inject_into_schema_parts, load_annotations
    from aughor.db.type_overrides import get_table_overrides
    _annotations = load_annotations(connection_id) if connection_id else None

    for table in sorted(tables):
        fqn = _fqn(table)
        try:
            count = conn.execute(f"SELECT COUNT(*) FROM {fqn}").fetchone()[0]
        except Exception:
            count = "?"

        parts.append(f"TABLE: {fqn}  ({count:,} rows)")
        if _annotations:
            inject_into_schema_parts(parts, table, None, _annotations)

        cols = conn.execute(f"DESCRIBE {fqn}").fetchall()
        _overrides = get_table_overrides(connection_id or "", table) if connection_id else {}
        for col in cols:
            col_name, col_type = col[0], col[1]
            if col_name in _overrides:
                col_type = _overrides[col_name]
            parts.append(f"  {col_name}  {col_type}")
            if _annotations:
                inject_into_schema_parts(parts, table, col_name, _annotations)

        # Explicitly flag tables with no date/timestamp columns so the LLM never
        # invents a date column name when building time-series queries on this table.
        _date_types = ("DATE", "TIMESTAMP", "TIME", "INTERVAL")
        has_date_col = any(
            any(dt in col[1].upper() for dt in _date_types) for col in cols
        )
        if not has_date_col:
            parts.append(
                f"  -- ⚠ No date/timestamp columns in {table}. "
                "Do NOT fabricate a date column. Join a table that has one if a time range is needed."
            )

        # Enumerate values for ALL low-cardinality categorical columns (frequency-ordered).
        # Using LIMIT 51: if ≤ 50 rows come back we know cardinality is low enough to list.
        for col_name, col_type in [(c[0], c[1]) for c in cols]:
            if not any(t in col_type.upper() for t in ("VARCHAR", "TEXT", "CHAR", "BOOLEAN")):
                continue
            if _KEY_COL.search(col_name.lower()):
                continue
            try:
                rows = conn.execute(
                    f'SELECT "{col_name}", COUNT(*) AS n FROM {fqn} '
                    f'WHERE "{col_name}" IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 51'
                ).fetchall()
                if rows and 1 <= len(rows) <= 50:
                    vals = ", ".join(str(r[0]) for r in rows)
                    parts.append(f"  -- {col_name}  [{vals}]")
            except Exception:
                pass

        parts.append("")

    # Add date range context
    try:
        date_range = conn.execute(
            "SELECT MIN(date)::VARCHAR, MAX(date)::VARCHAR FROM kpi_daily"
        ).fetchone()
        if date_range:
            parts.append(f"Date range in kpi_daily: {date_range[0]} to {date_range[1]}")
    except Exception:
        pass

    return "\n".join(parts)


# ── Pure schema-string helpers (no DB, no agent) ──────────────────────────────

def _parse_schema_tables(schema_str: str) -> dict[str, list[str]]:
    """Parse TABLE: blocks from a schema string → {table: [col_name, ...]}."""
    table_cols: dict[str, list[str]] = {}
    current: str | None = None
    for line in schema_str.splitlines():
        if _SECTION_STOP.match(line):
            current = None
            continue
        m = re.match(r"^TABLE:\s+([\w.]+)", line)
        if m:
            current = m.group(1)
            table_cols[current] = []
        elif current:
            col_m = re.match(r"^\s{2}(.+?)\s{2,}(\S+)", line)
            if col_m and not line.strip().startswith("--"):
                table_cols[current].append(col_m.group(1))
    return table_cols


def parse_schema_tables(schema_str: str) -> dict[str, list[str]]:
    """Public alias for the schema → {table: [columns]} parser (a stable interface
    callers can import without reaching into the module's internals)."""
    return _parse_schema_tables(schema_str)


def _fk_root(col: str) -> str | None:
    """Normalised foreign-key root for a *key-like* column, else None.

    Handles the convention where every column carries a short table prefix and
    the key suffix is fused: ``c_custkey`` and ``o_custkey`` both → ``cust`` so
    the customer↔orders FK is detected. Standard ``customer_id`` style still
    maps to ``customer``. Returns None for non-key columns so the caller can fall
    back to legacy behaviour — purely additive, no new join candidates for
    non-key columns (c_acctbal / s_acctbal stay un-joined)."""
    c = col.lower()
    stripped = _TABLE_PREFIX.sub("", c, count=1)
    root = None
    for suffix in _ROOT_SUFFIXES:  # _id, _key, _number, _code, _sk, …
        if stripped.endswith(suffix):
            root = stripped[: -len(suffix)]
            break
    if root is None and stripped.endswith("key") and len(stripped) > 3:  # fused: custkey
        root = stripped[:-3]
    if root is None or len(root) < 3:
        return None
    # Skip date/time surrogate keys (every fact carries *_date_sk → shared date_dim;
    # plain root-matching would wrongly join facts to each other).
    if root == "date" or root == "time" or root.endswith("date") or root.endswith("time"):
        return None
    return root


def fk_root(col: str) -> str | None:
    """Public alias for the FK-root extractor (stable cross-module interface)."""
    return _fk_root(col)


# Public aliases so other modules never import the private names (keeps the
# "no cross-module private imports" ratchet satisfied).
ROOT_SUFFIXES = _ROOT_SUFFIXES
SECTION_STOP = _SECTION_STOP
