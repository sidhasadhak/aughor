"""
Database connection abstraction.

Each backend implements execute() and get_schema() so the agent
works identically regardless of what's underneath.
SQLGlot handles dialect translation transparently.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

import duckdb
import sqlglot

from hermes.agent.state import QueryResult

# ── Proactive PostgreSQL dialect transforms ───────────────────────────────────
# Applied to every Postgres query *before* execution to prevent the most
# common class of type errors without needing a retry round-trip.

# Locates each ROUND( token so the paren-aware rewriter can take over.
_ROUND_OPEN = re.compile(r"\bROUND\s*\(", re.IGNORECASE)

# (col1 - col2)::numeric  where operands look like timestamp columns
# → EXTRACT(EPOCH FROM (col1 - col2)) / 86400.0
_INTERVAL_NUMERIC = re.compile(
    r"\(([^()]+?)\s*-\s*([^()]+?)\)\s*::\s*(?:numeric|integer|float)",
    re.IGNORECASE,
)
_TS_HINT = re.compile(
    r"date|time|_at\b|timestamp|created|updated|delivered|approved|purchase|shipping",
    re.IGNORECASE,
)


def _find_top_level_comma(s: str) -> int | None:
    """Return the index of the last comma at paren-depth 0, or None."""
    depth = 0
    last = None
    for i, ch in enumerate(s):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            last = i
    return last


def _pg_fix_round(sql: str) -> str:
    """
    Rewrite every two-argument ROUND(expr, N) → ROUND((expr)::numeric, N).

    PostgreSQL's ROUND(double precision, integer) does not exist — only the
    numeric overload accepts a precision argument.  Arithmetic expressions
    (100.0 * x / y, SUM(a)/COUNT(*), etc.) silently return double precision,
    so we unconditionally cast the first argument to numeric.  The cast is a
    no-op when the expression is already numeric, so this is always safe.
    """
    parts: list[str] = []
    pos = 0
    for m in _ROUND_OPEN.finditer(sql):
        parts.append(sql[pos:m.end()])   # everything up to and including "ROUND("
        # Walk forward tracking paren depth to find the matching ")"
        depth = 1
        j = m.end()
        while j < len(sql) and depth > 0:
            if sql[j] == "(":
                depth += 1
            elif sql[j] == ")":
                depth -= 1
            j += 1
        # sql[m.end() : j-1] is the raw content inside ROUND(...)
        inner = sql[m.end(): j - 1]
        pos = j  # character after the closing ")"

        comma = _find_top_level_comma(inner)
        if comma is not None:
            precision = inner[comma + 1:].strip()
            if re.match(r"^\d+$", precision):          # second arg is a plain integer
                first_arg = inner[:comma].strip()
                # Don't double-cast if already ::numeric
                if not re.search(r"::numeric\s*$", first_arg, re.IGNORECASE):
                    first_arg = f"({first_arg})::numeric"
                parts.append(f"{first_arg}, {precision})")
                continue
        # Not a two-arg ROUND, or precision isn't a plain literal — leave untouched
        parts.append(inner + ")")

    parts.append(sql[pos:])
    return "".join(parts)


def _pg_fix_nullif_timestamps(sql: str, varchar_ts_cols: list[tuple[str, str]]) -> str:
    """col::TIMESTAMP → NULLIF(col, '')::TIMESTAMP for known VARCHAR timestamp columns."""
    for _table, col in varchar_ts_cols:
        pat = re.compile(
            rf"\b{re.escape(col)}\s*::\s*TIMESTAMP\b", re.IGNORECASE
        )
        sql = pat.sub(f"NULLIF({col}, '')::TIMESTAMP", sql)
    return sql


def _pg_fix_interval_arithmetic(sql: str) -> str:
    """(ts_col - ts_col)::numeric → EXTRACT(EPOCH FROM (...)) / 86400.0."""
    def _replace(m: re.Match) -> str:
        a, b = m.group(1).strip(), m.group(2).strip()
        if _TS_HINT.search(a) or _TS_HINT.search(b):
            return f"EXTRACT(EPOCH FROM ({a} - {b})) / 86400.0"
        return m.group(0)  # not timestamp-looking — leave as-is
    return _INTERVAL_NUMERIC.sub(_replace, sql)


# ── Safety ────────────────────────────────────────────────────────────────────

_FORBIDDEN = re.compile(
    r"\b(DROP|DELETE|INSERT|UPDATE|CREATE|ALTER|TRUNCATE|EXEC|EXECUTE|COPY|ATTACH|DETACH)\b",
    re.IGNORECASE,
)

MAX_ROWS = 500


def _validate(sql: str) -> tuple[bool, str]:
    sql = sql.strip().rstrip(";")
    if _FORBIDDEN.search(sql):
        return False, "Only SELECT statements are permitted"
    try:
        parsed = sqlglot.parse_one(sql, error_level=sqlglot.ErrorLevel.RAISE)
    except Exception as e:
        return False, f"SQL parse error: {e}"
    if not isinstance(parsed, sqlglot.exp.Select):
        return False, f"Only SELECT is allowed, got {type(parsed).__name__}"
    return True, "ok"


# ── Base class ────────────────────────────────────────────────────────────────

class DatabaseConnection(ABC):
    dialect: str = "duckdb"

    @abstractmethod
    def execute(self, hypothesis_id: str, sql: str) -> QueryResult: ...

    @abstractmethod
    def get_schema(self) -> str: ...

    @abstractmethod
    def test(self) -> tuple[bool, str]:
        """Return (ok, message)."""
        ...

    @abstractmethod
    def close(self) -> None: ...

    def translate(self, sql: str) -> str:
        """Rewrite SQL from any dialect to this backend's dialect."""
        if self.dialect == "duckdb":
            return sql
        try:
            return sqlglot.transpile(sql, read="duckdb", write=self.dialect)[0]
        except Exception:
            return sql  # best-effort — fall back to original


# ── DuckDB ────────────────────────────────────────────────────────────────────

class DuckDBConnection(DatabaseConnection):
    dialect = "duckdb"

    def __init__(self, path: str | Path):
        self._path = Path(path)
        self._conn = duckdb.connect(str(self._path), read_only=True)

    def execute(self, hypothesis_id: str, sql: str) -> QueryResult:
        sql = sql.strip().rstrip(";")
        ok, reason = _validate(sql)
        if not ok:
            return QueryResult(hypothesis_id=hypothesis_id, sql=sql, columns=[], rows=[], row_count=0, error=reason)
        try:
            self._conn.execute(sql)
            rows = self._conn.fetchall()
            columns = [d[0] for d in self._conn.description] if self._conn.description else []
            return QueryResult(
                hypothesis_id=hypothesis_id,
                sql=sql,
                columns=columns,
                rows=[[str(v) if v is not None else "NULL" for v in row] for row in rows[:MAX_ROWS]],
                row_count=len(rows),
            )
        except Exception as e:
            return QueryResult(hypothesis_id=hypothesis_id, sql=sql, columns=[], rows=[], row_count=0, error=str(e))

    def get_schema(self) -> str:
        from hermes.tools.schema import build_schema_context
        return build_schema_context(self._conn)

    def test(self) -> tuple[bool, str]:
        if not self._path.exists():
            return False, f"File not found: {self._path}"
        try:
            self._conn.execute("SELECT 1")
            return True, "Connected"
        except Exception as e:
            return False, str(e)

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass


# ── Postgres ──────────────────────────────────────────────────────────────────

class PostgresConnection(DatabaseConnection):
    dialect = "postgres"

    def __init__(self, dsn: str):
        self._dsn = dsn
        self._conn = None
        # Populated by get_schema() — used by proactive dialect transforms
        self._varchar_ts_cols: list[tuple[str, str]] = []
        self._connect()

    def _connect(self):
        import psycopg2
        self._conn = psycopg2.connect(self._dsn)
        self._conn.autocommit = True

    def _apply_dialect_fixes(self, sql: str) -> str:
        """
        Three sequential proactive transforms for PostgreSQL.
        Catches predictable type errors before they reach the database,
        avoiding a FIX_SQL retry round-trip.
        """
        sql = _pg_fix_round(sql)
        sql = _pg_fix_nullif_timestamps(sql, self._varchar_ts_cols)
        sql = _pg_fix_interval_arithmetic(sql)
        return sql

    def execute(self, hypothesis_id: str, sql: str) -> QueryResult:
        sql = sql.strip().rstrip(";")
        ok, reason = _validate(sql)
        if not ok:
            return QueryResult(hypothesis_id=hypothesis_id, sql=sql, columns=[], rows=[], row_count=0, error=reason)

        # Translate DuckDB-flavoured SQL → Postgres, then apply proactive fixes
        sql = self.translate(sql)
        sql = self._apply_dialect_fixes(sql)

        try:
            with self._conn.cursor() as cur:
                cur.execute(sql)
                rows = cur.fetchmany(MAX_ROWS)
                columns = [desc[0] for desc in cur.description] if cur.description else []
                # row_count from cursor (may be -1 for some queries)
                total = cur.rowcount if cur.rowcount >= 0 else len(rows)
                return QueryResult(
                    hypothesis_id=hypothesis_id,
                    sql=sql,
                    columns=columns,
                    rows=[[str(v) if v is not None else "NULL" for v in row] for row in rows],
                    row_count=total,
                )
        except Exception as e:
            # Reconnect on broken pipe
            try:
                self._connect()
            except Exception:
                pass
            return QueryResult(hypothesis_id=hypothesis_id, sql=sql, columns=[], rows=[], row_count=0, error=str(e))

    def get_schema(self) -> str:
        """Introspect information_schema and return a Hermes-formatted schema string with SQL hints."""
        try:
            with self._conn.cursor() as cur:
                cur.execute("""
                    SELECT table_name, column_name, data_type
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                    ORDER BY table_name, ordinal_position
                """)
                rows = cur.fetchall()
        except Exception as e:
            return f"Schema unavailable: {e}"

        if not rows:
            return "No tables found in public schema."

        parts: list[str] = []
        current_table = None
        for table, col, dtype in rows:
            if table != current_table:
                if current_table:
                    parts.append("")
                try:
                    with self._conn.cursor() as cur2:
                        cur2.execute(f"SELECT COUNT(*) FROM {table}")
                        count = cur2.fetchone()[0]
                except Exception:
                    count = "?"
                parts.append(f"TABLE: {table}  ({count:,} rows)")
                current_table = table
            parts.append(f"  {col}  {dtype}")

        schema_str = "\n".join(parts)
        hints = self._detect_sql_hints(rows)  # also populates self._varchar_ts_cols
        if hints:
            schema_str += "\n\n" + hints

        from hermes.semantic.autoseed import seed_missing_tables
        from hermes.semantic.glossary import apply_glossary
        from hermes.tools.schema import infer_joins
        seed_missing_tables(schema_str)
        enriched = apply_glossary(schema_str)
        join_hints = infer_joins(enriched)
        if join_hints:
            enriched += "\n\n" + join_hints
        return enriched

    def _detect_sql_hints(self, columns: list) -> str:
        """
        Scan for common data quality issues and return a SQL hints block.
        This runs once at schema-load time so the LLM sees it in every prompt.
        """
        hints: list[str] = []

        # Find VARCHAR columns whose names suggest they hold timestamps/dates
        timestamp_pattern = (
            "timestamp", "date", "_at", "_on", "time", "created", "updated",
            "delivered", "approved", "purchase", "shipping",
        )
        varchar_ts_cols: list[tuple[str, str]] = [
            (t, c) for t, c, dtype in columns
            if dtype == "character varying"
            and any(c.lower().endswith(p) or p in c.lower() for p in timestamp_pattern)
        ]
        # Store for use by _apply_dialect_fixes on every subsequent execute() call
        self._varchar_ts_cols = varchar_ts_cols

        if varchar_ts_cols:
            sample = ", ".join(f"{t}.{c}" for t, c in varchar_ts_cols[:5])
            hints.append(
                "⚠ TIMESTAMP COLUMNS STORED AS VARCHAR — cast before any date arithmetic:\n"
                f"  Affected: {sample}\n"
                "  Correct cast:  CAST(col AS TIMESTAMP)\n"
                "  Date diff (days):  EXTRACT(EPOCH FROM (\n"
                "      CAST(end_col AS TIMESTAMP) - CAST(start_col AS TIMESTAMP)\n"
                "  )) / 86400\n"
                "  Never subtract VARCHAR columns directly — it will fail."
            )

        # Check for empty strings in VARCHAR timestamp columns (up to 5, fast COUNT queries)
        empty_str_notes: list[str] = []
        for table, col in varchar_ts_cols[:5]:
            try:
                with self._conn.cursor() as cur:
                    cur.execute(
                        f"SELECT COUNT(*) FROM {table} WHERE {col} = ''", # noqa: S608
                    )
                    n = cur.fetchone()[0]
                if n > 0:
                    empty_str_notes.append(
                        f"  {table}.{col}: {n:,} empty strings — filter with WHERE {col} != ''"
                    )
            except Exception:
                pass

        if empty_str_notes:
            hints.append(
                "⚠ EMPTY STRINGS (not NULL) in timestamp columns — always filter:\n"
                + "\n".join(empty_str_notes)
            )

        if not hints:
            return ""
        return "SQL HINTS FOR THIS DATABASE:\n" + "\n\n".join(hints)

    def test(self) -> tuple[bool, str]:
        try:
            with self._conn.cursor() as cur:
                cur.execute("SELECT version()")
                version = cur.fetchone()[0]
            return True, version.split(",")[0]
        except Exception as e:
            return False, str(e)

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass


# ── Factory ───────────────────────────────────────────────────────────────────

def open_connection(conn_type: str, dsn: str) -> DatabaseConnection:
    if conn_type == "duckdb":
        return DuckDBConnection(dsn)
    elif conn_type == "postgres":
        return PostgresConnection(dsn)
    else:
        raise ValueError(f"Unsupported connection type: {conn_type!r}. Supported: duckdb, postgres")
