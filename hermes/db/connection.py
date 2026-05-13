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
        self._connect()

    def _connect(self):
        import psycopg2
        self._conn = psycopg2.connect(self._dsn)
        self._conn.autocommit = True

    def execute(self, hypothesis_id: str, sql: str) -> QueryResult:
        sql = sql.strip().rstrip(";")
        ok, reason = _validate(sql)
        if not ok:
            return QueryResult(hypothesis_id=hypothesis_id, sql=sql, columns=[], rows=[], row_count=0, error=reason)

        # Translate DuckDB-flavoured SQL → Postgres
        sql = self.translate(sql)

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
        hints = self._detect_sql_hints(rows)
        if hints:
            schema_str += "\n\n" + hints
        return schema_str

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
