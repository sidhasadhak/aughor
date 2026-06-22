"""
SQL error classifier — maps raw database errors to structured diagnostic hints.

Called in plan_and_execute *before* FIX_SQL_PROMPT so the LLM receives
targeted guidance ("cast to ::numeric before ROUND") rather than the raw
PostgreSQL error string. Increases first-fix success rate significantly.

Returns a non-empty string when a known pattern matches; empty string
otherwise (raw error is surfaced as-is).
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Optional


class SqlErrorClass(str, Enum):
    """The *kind* of SQL failure — the Verifier's typed signal that ROUTES repair
    (à la MotherDuck's try_bind, extended). Distinguishing these lets the fixer do
    the right thing instead of a blind retry: a `binder` error needs the real
    columns, a `parser` error needs the syntax re-checked, a `runtime` error needs
    a guard (NULLIF), a `semantic` error needs a cast."""
    OK = "ok"
    PARSER = "parser"       # won't parse — syntax
    BINDER = "binder"       # name resolution — missing/ambiguous column/table/function, GROUP BY
    SEMANTIC = "semantic"   # binds, but a type / expression mismatch
    RUNTIME = "runtime"     # executed, then failed (division by zero, overflow, timeout)


def classify_error_type(error: Optional[str], sql: str = "", dialect: str = "") -> SqlErrorClass:
    """Classify a raw DB error into the repair taxonomy. Works across DuckDB
    (prefixed: 'Parser Error:', 'Binder Error:', 'Conversion Error:'), Postgres,
    and SQLite. Order matters — runtime and the semantic 'operator does not exist'
    are checked before the generic binder 'does not exist'. Never raises."""
    if not error:
        return SqlErrorClass.OK
    e = error.lower()
    if any(k in e for k in ("division by zero", "out of range", "overflow",
                            "timeout", "timed out", "deadlock", "out of memory")):
        return SqlErrorClass.RUNTIME
    if any(k in e for k in ("parser error", "syntax error", "incomplete input",
                            "unterminated", "unexpected token", "unexpected end")):
        return SqlErrorClass.PARSER
    if any(k in e for k in ("operator does not exist", "no function matches",
                            "conversion error", "invalid input", "cannot cast",
                            "could not convert", "type mismatch", "double precision")):
        return SqlErrorClass.SEMANTIC
    if any(k in e for k in ("binder error", "catalog error", "does not exist",
                            "no such column", "no such table", "ambiguous",
                            "must appear in the group by", "not in group by",
                            "not found", "unknown column", "undefined column")):
        return SqlErrorClass.BINDER
    return SqlErrorClass.SEMANTIC   # unmatched: a logic/type issue to re-examine


_CLASS_GUIDANCE: dict = {
    SqlErrorClass.PARSER:   "The SQL does not parse. Re-check the dialect's syntax — quoting, commas, balanced parentheses, reserved words.",
    SqlErrorClass.BINDER:   "A referenced name (column/table/function) is missing or ambiguous. Use ONLY the exact columns and tables provided — do not invent names; fully-qualify ambiguous columns.",
    SqlErrorClass.SEMANTIC: "A type or expression mismatch. Cast explicitly (e.g. ::NUMERIC, CAST(col AS TIMESTAMP)), match function argument types, and never apply date/number ops to text columns.",
    SqlErrorClass.RUNTIME:  "The query ran, then failed at execution (e.g. division by zero). Guard it — wrap denominators in NULLIF(...), bound ranges, avoid overflow.",
}


def error_class_guidance(cls: SqlErrorClass) -> str:
    """One-line, type-specific repair framing — prepended to the diagnosis so the
    fixer routes by error class instead of retrying blind."""
    return _CLASS_GUIDANCE.get(cls, "")


def classify_sql_error(error: str, sql: str, dialect: str) -> str:
    """
    Return a DIAGNOSIS string for *error*, or "" if no pattern matches.
    The caller prepends "DIAGNOSIS:" before injecting into the prompt.
    """
    e = error.lower()
    for fn in (
        _round_precision,
        _not_in_group_by,
        _interval_to_numeric,
        _division_by_zero,
        _varchar_date_op,
        _column_alias_in_where,
        _ambiguous_column_ref,
        _column_not_exist,
        _type_cast_error,
    ):
        msg = fn(e, sql, dialect)
        if msg:
            return msg
    return ""


# ── Pattern handlers ──────────────────────────────────────────────────────────

def _round_precision(e: str, sql: str, dialect: str) -> str:
    if "round" in e and ("does not exist" in e or "function" in e) and "double precision" in e:
        return (
            "PostgreSQL ROUND() requires NUMERIC type for its two-argument form. "
            "AVG(), SUM()/COUNT(*), and most arithmetic return double precision. "
            "FIX: cast the expression to numeric before rounding: "
            "ROUND(AVG(col)::numeric, 2) or ROUND((SUM(x)/NULLIF(COUNT(*),0))::numeric, 2)."
        )
    return ""


def _not_in_group_by(e: str, sql: str, dialect: str) -> str:
    if "must appear in the group by" in e or "not in group by" in e:
        m = re.search(r'column "([^"]+)" must appear', e)
        col = f'"{m.group(1)}"' if m else "the column"
        return (
            f"Non-aggregated column {col} must appear in GROUP BY or be wrapped in "
            f"an aggregate (MAX, MIN, SUM, COUNT, etc.). "
            f"FIX: add {col} to the GROUP BY clause. If it is functionally dependent "
            f"on the GROUP BY key, use MAX({col}) or ANY_VALUE({col})."
        )
    return ""


def _interval_to_numeric(e: str, sql: str, dialect: str) -> str:
    if "interval" in e and ("numeric" in e or "integer" in e) and (
        "cannot" in e or "does not exist" in e
    ):
        return (
            "PostgreSQL cannot cast an interval directly to numeric or integer. "
            "FIX: use EXTRACT(EPOCH FROM ...) to get seconds as a float, then divide: "
            "EXTRACT(EPOCH FROM (end_ts - start_ts)) / 86400.0 for days. "
            "If columns are stored as VARCHAR, cast first: CAST(col AS TIMESTAMP)."
        )
    return ""


def _division_by_zero(e: str, sql: str, dialect: str) -> str:
    if "division by zero" in e:
        return (
            "Division by zero encountered. "
            "FIX: wrap the denominator with NULLIF so the expression returns NULL "
            "instead of erroring: SUM(x) / NULLIF(SUM(y), 0) or "
            "COUNT(x) / NULLIF(total, 0)."
        )
    return ""


def _varchar_date_op(e: str, sql: str, dialect: str) -> str:
    if ("character varying" in e or "varchar" in e) and (
        "operator does not exist" in e or "cannot" in e
    ) and (
        # Error explicitly mentions a date/time type
        any(k in e for k in ("timestamp", "date", "interval"))
        # OR error is a varchar-varchar arithmetic op (subtraction/comparison involving varchar date cols)
        or ("character varying - character varying" in e)
        or ("character varying + character varying" in e)
    ):
        return (
            "A VARCHAR column is being used in date/time arithmetic. "
            "FIX: cast the column first: CAST(col AS TIMESTAMP) or col::TIMESTAMP. "
            "For empty-string safety (CSV-loaded data): NULLIF(col, '')::TIMESTAMP. "
            "Date diff in days: "
            "EXTRACT(EPOCH FROM (CAST(b AS TIMESTAMP) - CAST(a AS TIMESTAMP))) / 86400.0."
        )
    return ""


def _column_alias_in_where(e: str, sql: str, dialect: str) -> str:
    if "column" in e and "does not exist" in e:
        m = re.search(r'column "([^"]+)" does not exist', e)
        if m:
            alias = m.group(1)
            if re.search(rf"\bAS\s+{re.escape(alias)}\b", sql, re.IGNORECASE):
                return (
                    f'Column "{alias}" is a SELECT alias and cannot be referenced '
                    f"in WHERE or HAVING (aliases are not yet in scope there). "
                    f"FIX: repeat the full expression in WHERE/HAVING, or wrap in a CTE: "
                    f"WITH cte AS (SELECT ..., expr AS {alias} FROM ...) "
                    f"SELECT * FROM cte WHERE {alias} > x."
                )
    return ""


def _ambiguous_column_ref(e: str, sql: str, dialect: str) -> str:
    if "ambiguous" in e and "column" in e:
        m = re.search(r'column reference "([^"]+)" is ambiguous', e)
        col = f'"{m.group(1)}"' if m else "the column"
        bare = col.strip('"')
        return (
            f"Column {col} exists in multiple joined tables — PostgreSQL cannot "
            f"resolve it without qualification. "
            f"FIX: prefix with the table name: table_name.{bare}."
        )
    return ""


def _column_not_exist(e: str, sql: str, dialect: str) -> str:
    if "column" in e and "does not exist" in e:
        m = re.search(r'column "([^"]+)" does not exist', e)
        if m:
            bad_col = m.group(1)
            if "." in bad_col:
                return (
                    f'"{bad_col}" looks like a schema-qualified name used where a '
                    f"column is expected. FIX: remove the schema prefix from the alias, "
                    f"or reference the table directly."
                )
            return (
                f'Column "{bad_col}" does not exist. '
                f"FIX: verify the exact column name in the schema above — check for "
                f"typos, wrong table, or use of a SELECT alias before it is in scope."
            )
    return ""


def _type_cast_error(e: str, sql: str, dialect: str) -> str:
    if "invalid input syntax for type" in e:
        m = re.search(r'invalid input syntax for type (\w+): "([^"]*)"', e)
        if m:
            typ, val = m.group(1), m.group(2)
            return (
                f'Cannot cast value "{val}" to {typ}. '
                f"FIX: guard empty strings with NULLIF before casting: "
                f"NULLIF(col, '')::{typ}. "
                f"Or filter bad rows first: WHERE col ~ '^[0-9]' before casting."
            )
    return ""
