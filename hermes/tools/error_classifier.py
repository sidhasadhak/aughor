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
