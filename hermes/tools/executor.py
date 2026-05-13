"""Safe SQL execution against DuckDB with query validation and audit logging."""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Optional

import duckdb
import sqlglot

from hermes.agent.state import QueryResult

# Hard limits per query
MAX_ROWS = 500
MAX_EXECUTION_MS = 30_000

_FORBIDDEN = re.compile(
    r"\b(DROP|DELETE|INSERT|UPDATE|CREATE|ALTER|TRUNCATE|EXEC|EXECUTE|COPY|ATTACH|DETACH|PRAGMA)\b",
    re.IGNORECASE,
)


def validate_sql(sql: str) -> tuple[bool, str]:
    """Parse with sqlglot and block any non-SELECT statement."""
    sql = sql.strip().rstrip(";")
    if _FORBIDDEN.search(sql):
        return False, "Query contains a forbidden keyword (only SELECT is allowed)"
    try:
        parsed = sqlglot.parse_one(sql, error_level=sqlglot.ErrorLevel.RAISE)
    except Exception as e:
        return False, f"SQL parse error: {e}"
    if not isinstance(parsed, sqlglot.exp.Select):
        return False, f"Only SELECT statements are allowed, got {type(parsed).__name__}"
    return True, "ok"


def execute_query(
    conn: duckdb.DuckDBPyConnection,
    hypothesis_id: str,
    sql: str,
) -> QueryResult:
    sql = sql.strip().rstrip(";")

    ok, reason = validate_sql(sql)
    if not ok:
        return QueryResult(
            hypothesis_id=hypothesis_id,
            sql=sql,
            columns=[],
            rows=[],
            row_count=0,
            error=reason,
        )

    try:
        start = time.monotonic()
        conn.execute(sql)
        elapsed_ms = (time.monotonic() - start) * 1000

        if elapsed_ms > MAX_EXECUTION_MS:
            return QueryResult(
                hypothesis_id=hypothesis_id,
                sql=sql,
                columns=[],
                rows=[],
                row_count=0,
                error=f"Query exceeded {MAX_EXECUTION_MS}ms time limit",
            )

        all_rows = conn.fetchall()
        columns = [desc[0] for desc in conn.description] if conn.description else []
        row_count = len(all_rows)
        rows = all_rows[:MAX_ROWS]

        return QueryResult(
            hypothesis_id=hypothesis_id,
            sql=sql,
            columns=columns,
            rows=[[str(v) if v is not None else "NULL" for v in row] for row in rows],
            row_count=row_count,
        )
    except Exception as e:
        return QueryResult(
            hypothesis_id=hypothesis_id,
            sql=sql,
            columns=[],
            rows=[],
            row_count=0,
            error=str(e),
        )


def format_result_for_llm(result: QueryResult, max_rows: int = 30) -> str:
    """Render a QueryResult as a compact text table for LLM context."""
    if result.error:
        return f"SQL: {result.sql}\nERROR: {result.error}"

    lines = [f"SQL: {result.sql}", f"Rows returned: {result.row_count}"]
    if result.columns:
        col_str = " | ".join(result.columns)
        lines.append(col_str)
        lines.append("-" * len(col_str))
        for row in result.rows[:max_rows]:
            lines.append(" | ".join(str(v) for v in row))
        if result.row_count > max_rows:
            lines.append(f"... ({result.row_count - max_rows} more rows)")
    return "\n".join(lines)


def open_db(db_path: str | Path) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(db_path), read_only=True)
