"""SQL validation and result formatting utilities."""
from __future__ import annotations

import re

import sqlglot

from aughor.agent.state import QueryResult

MAX_ROWS = 500

_FORBIDDEN = re.compile(
    r"\b(DROP|DELETE|INSERT|UPDATE|CREATE|ALTER|TRUNCATE|EXEC|EXECUTE|COPY|ATTACH|DETACH|PRAGMA)\b",
    re.IGNORECASE,
)


_READ_ONLY_TYPES = (
    sqlglot.exp.Select,   # plain SELECT
    sqlglot.exp.Union,    # SELECT ... UNION [ALL] SELECT ...
    sqlglot.exp.Intersect,
    sqlglot.exp.Except,
    sqlglot.exp.Subquery, # shouldn't appear at top level, but harmless to allow
)


def validate_sql(sql: str) -> tuple[bool, str]:
    """Parse with sqlglot and block any non-SELECT statement.

    UNION / INTERSECT / EXCEPT are all read-only set operations composed of
    SELECT statements and must be allowed — they parse as sqlglot.exp.Union
    (not Select), so a bare isinstance(…, Select) check incorrectly rejects them.
    """
    sql = sql.strip().rstrip(";")
    if _FORBIDDEN.search(sql):
        return False, "Query contains a forbidden keyword (only SELECT is allowed)"
    try:
        parsed = sqlglot.parse_one(sql, error_level=sqlglot.ErrorLevel.RAISE)
    except Exception as e:
        return False, f"SQL parse error: {e}"
    if not isinstance(parsed, _READ_ONLY_TYPES):
        return False, f"Only SELECT statements are allowed, got {type(parsed).__name__}"
    return True, "ok"


def format_result_for_llm(result: QueryResult, max_rows: int = 30) -> str:
    """Render a QueryResult as a compact text table for LLM context."""
    if result.error:
        return f"SQL: {result.sql}\nERROR: {result.error}"

    lines = [f"SQL: {result.sql}", f"Rows returned: {result.row_count}"]

    # Diagnose zero-row results so the interpret LLM knows this is likely a bad query,
    # not an absence of data.  Common causes: wrong date column, failed CAST, bad join.
    if result.row_count == 0:
        sql_lower = (result.sql or "").lower()
        hints: list[str] = []
        if "cast(" in sql_lower and "as date" in sql_lower:
            hints.append(
                "⚠ Query contains CAST(... AS DATE) which may be casting an integer/string "
                "identifier — this usually returns zero rows. Use the real DATE/TIMESTAMP column instead."
            )
        if not hints:
            hints.append(
                "⚠ Zero rows returned. Possible causes: (1) incorrect date column — "
                "check whether a CAST of a non-date column is filtering out all rows; "
                "(2) wrong table — the metric or date may live in a joined table; "
                "(3) date range has no data. Re-examine the SQL before concluding data is absent."
            )
        lines.extend(hints)

    if result.columns:
        col_str = " | ".join(result.columns)
        lines.append(col_str)
        lines.append("-" * len(col_str))
        for row in result.rows[:max_rows]:
            lines.append(" | ".join(str(v) for v in row))
        if result.row_count > max_rows:
            lines.append(f"... ({result.row_count - max_rows} more rows)")

    # Append statistical findings so the LLM can cite them in evidence scoring
    if result.stats:
        lines.append("")
        lines.append("STATISTICAL ANALYSIS:")
        for s in result.stats:
            sig_marker = "⚠ SIGNIFICANT" if s.is_significant else "—"
            sigma_str = f" [{s.sigma:.1f}σ]" if s.sigma is not None else ""
            lines.append(f"  {sig_marker}{sigma_str} {s.interpretation}")

    return "\n".join(lines)
