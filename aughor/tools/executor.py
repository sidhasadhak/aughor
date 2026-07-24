"""SQL validation and result formatting utilities."""
from __future__ import annotations

import logging

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


# Number formatting lives in ONE place — `aughor.util.format` owns the precision policy for the
# whole platform (prose, table cells, and LLM prompt input alike).
from aughor.util.format import round_cell  # noqa: E402  (after the module's own constants)


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
        # SEC-03: column names + row values are untrusted DB content. Fence the whole
        # data table so it can't be read as instructions, cap each cell, and neutralize
        # any <data> break-out attempt inside a value.
        from aughor.util.prompt_safety import cap_cell, fence_untrusted
        col_str = " | ".join(cap_cell(c) for c in result.columns)
        table_lines = [col_str, "-" * len(col_str)]
        for row in result.rows[:max_rows]:
            # `cap_cell` sanitizes and truncates but does NOT round — so a raw float64 repr
            # reached the model here, and the interpret prompts require it to quote a value
            # that appears in the result. Round FIRST: the 17-digit form never exists for it
            # to copy. (aughor.util.format owns the precision policy.)
            table_lines.append(" | ".join(cap_cell(round_cell(v)) for v in row))
        if result.row_count > max_rows:
            table_lines.append(f"... ({result.row_count - max_rows} more rows)")
        lines.append(fence_untrusted("\n".join(table_lines)))

    # Append statistical findings so the LLM can cite them in evidence scoring
    if result.stats:
        lines.append("")
        lines.append("STATISTICAL ANALYSIS:")
        for s in result.stats:
            sig_marker = "⚠ SIGNIFICANT" if s.is_significant else "—"
            sigma_str = f" [{s.sigma:.1f}σ]" if s.sigma is not None else ""
            lines.append(f"  {sig_marker}{sigma_str} {s.interpretation}")

    return "\n".join(lines)


# ── Wave R5: the SQL half of declared parallel-safety ─────────────────────────
# The generic machinery (a fan-out declares itself; the dangerous operation asks) lives in
# `aughor.kernel.parallel_safety`. These two live HERE because "is this statement a read"
# is SQL-domain knowledge, and the kernel must not import the tools layer — the
# platform→agent boundary test enforces that, and it caught the first attempt.

def sql_is_parallel_safe(sql: str) -> bool:
    """True when ``sql`` is a read the gate would allow.

    Reuses :func:`validate_sql` rather than adding a second opinion — a divergence between
    "the gate allows it" and "we call it parallel-safe" would be worse than having no check
    at all. Unparseable ⇒ False: the gate refuses it anyway, and guessing on the permissive
    side is the wrong direction for a concurrency question.
    """
    try:
        ok, _ = validate_sql(sql)
        return bool(ok)
    except Exception:
        logging.getLogger(__name__).debug("read-only check failed", exc_info=True)
        return False


def check_sql_fanout(sqls, *, where: str) -> list[str]:
    """The statements in ``sqls`` that must NOT be fanned out, returned for the caller to log.

    Advisory on purpose: the per-worker SQL gate is still the authority and refuses a write
    regardless. What this adds is the decision being made and COUNTED *before* the dispatch,
    so "a write reached a fan-out" is visible at ``GET /dev/stats`` rather than only as N
    identical per-worker rejections.
    """
    bad = [s for s in sqls if s and s.strip() and not sql_is_parallel_safe(s)]
    if bad:
        from aughor.stats import bump
        bump("parallel_safety.non_read_fanout", len(bad))
        logging.getLogger(__name__).warning(
            "parallel-safety: %d non-read statement(s) reached %s — the gate will refuse "
            "them per worker", len(bad), where)
    return bad
