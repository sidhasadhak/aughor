"""A metric's SQL is a STATEMENT, and its grain is one column of one table (2026-09-26).

The user, on the metric editor's *"Aggregate expression — no SELECT keyword"*: *"not having
SELECT statement is hard because not every metric is SUM or AVG or COUNT of something.. it
can be pre-assessed SELECT statements with multiple CTEs that user may enter. But our job is
to propose those nonetheless (with select statement). Remove this condition and let every
metric have mandatorily a SELECT statement."* And on the date field: *"a combination of a
list and an open input. List should be our proposal of what date/timestamp should the metric
be grained at in a format schema.table.column_name."*

Two words, one concept each:

* A **statement** is a whole ``SELECT`` (CTEs allowed) that returns one row holding the
  metric's value. Every metric a person or the platform writes from now on is one; the doors
  refuse a bare aggregate. A row written before this (an **expression** such as
  ``SUM(sale_price)`` with its ``tables`` and ``filters``) still reads: :func:`as_statement`
  wraps it exactly as `value_query` always has, so nothing already approved changes value.
* The **grain** is the date a row counts on, written ``schema.table.column`` (or
  ``table.column``); a bare column means "on the metric's first table". It names the TABLE
  as well as the column because a statement is cut to a range by substituting that table
  with itself filtered to the window — the one rewrite that works on any statement, CTEs
  included, without the platform having to understand the statement's arithmetic.

Everything here is pure: sqlglot in, sqlglot out, no store, no model.
"""
from __future__ import annotations

from typing import Any, Optional

#: How a statement begins. ``WITH`` is a statement too — the multi-CTE case the user named.
_STATEMENT_STARTS = ("select", "with")


def is_statement(sql: Optional[str]) -> bool:
    """True when ``sql`` is a whole query rather than an aggregate expression."""
    return str(sql or "").strip().lower().startswith(_STATEMENT_STARTS)


def as_statement(sql: Optional[str], tables: Optional[list] = None, filters: Optional[list] = None,
                 name: str = "value") -> str:
    """The runnable statement for a definition: a statement as written, an expression
    wrapped over the metric's first table with its declared filters — the filters ARE the
    definition (revenue that includes cancelled orders is a different metric)."""
    text = str(sql or "").strip()
    if not text:
        return ""
    if is_statement(text):
        return text
    # Leading underscores survive: the value path has always aliased its column `_v`.
    alias = "".join(c if c.isalnum() or c == "_" else "_" for c in (name or "value").lower()) or "value"
    out = f"SELECT ({text}) AS {alias}"
    tables = [t for t in (tables or []) if str(t).strip()]
    if tables:
        out += f" FROM {tables[0]}"
        clauses = [str(f).strip() for f in (filters or []) if str(f).strip()]
        if clauses:
            out += " WHERE " + " AND ".join(clauses)
    return out


def bare(name: str) -> str:
    return str(name or "").split(".")[-1].strip('`"[]').lower()


def split_grain(time_column: Optional[str]) -> tuple[Optional[str], str]:
    """``"schema.table.column"`` → ``("schema.table", "column")``; a bare column → ``(None,
    column)``. Quoting is left as written."""
    text = str(time_column or "").strip()
    if "." not in text:
        return None, text
    table, column = text.rsplit(".", 1)
    return table.strip() or None, column.strip()


def statement_tables(sql: str, dialect: str = "duckdb") -> list[str]:
    """The tables a statement reads, as written (schema kept), CTE names excluded, in order
    of first appearance. Empty when the statement does not parse."""
    try:
        import sqlglot
        from sqlglot import exp
        tree = sqlglot.parse_one(str(sql or ""), read=dialect)
    except Exception:  # noqa: BLE001 — a statement the parser refuses names no table
        return []
    if tree is None:
        return []
    ctes = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    out: list[str] = []
    for t in tree.find_all(exp.Table):
        if not t.name or t.name.lower() in ctes:
            continue
        written = ".".join(p for p in (t.args.get("catalog") and t.catalog, t.db, t.name) if p)
        if written and written.lower() not in {o.lower() for o in out}:
            out.append(written)
    return out


def scoped_statement(sql: str, grain_table: str, predicate, *, dialect: str = "duckdb",
                     rewrite=None) -> tuple[Optional[str], str, int]:
    """``sql`` with every reference to ``grain_table`` replaced by that table filtered to
    ``predicate`` (a sqlglot expression over the table's own columns), so the statement's own
    arithmetic runs unchanged over the rows of one window. ``rewrite``, when given, is applied
    to the whole tree first (a cohort's outcome bound). Returns ``(sql, "", n)`` with ``n`` the
    references substituted, or ``(None, why, 0)``; ``n == 0`` is said, never silently run as the
    whole history."""
    try:
        import sqlglot
        from sqlglot import exp
        tree = sqlglot.parse_one(str(sql or ""), read=dialect)
    except Exception:  # noqa: BLE001
        return None, "its statement does not parse", 0
    if tree is None:
        return None, "its statement is empty", 0
    if rewrite is not None:
        tree, why = rewrite(tree)
        if tree is None:
            return None, why, 0
    ctes = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    want = bare(grain_table)
    n = 0
    for t in list(tree.find_all(exp.Table)):
        if not t.name or t.name.lower() in ctes or bare(t.name) != want:
            continue
        source = t.copy()
        source.set("alias", None)                     # the alias belongs to the subquery
        inner = exp.select(exp.Star()).from_(source).where(predicate.copy())
        alias = t.alias or t.name
        t.replace(exp.Subquery(this=inner, alias=exp.TableAlias(this=exp.to_identifier(alias))))
        n += 1
    if n == 0:
        return None, f"its statement does not read {grain_table}, the table its date is on", 0
    return tree.sql(dialect=dialect), "", n


def date_candidates(sql: str, tables: Optional[list], profile_entry: dict,
                    *, dialect: str = "duckdb") -> list[dict]:
    """The dates a metric could be grained at, as proposals: every date- or time-typed column
    of every table the statement reads (or the definition names), written
    ``schema.table.column`` as the table is written, the profiler's main date of each table
    first. ``[]`` when the connection was never profiled — the caller says so."""
    from aughor.semantic.metric_time import _is_time, _primary_date, _table_columns

    seen: list[str] = []
    for t in statement_tables(sql, dialect) + [str(x).strip() for x in (tables or []) if str(x).strip()]:
        if bare(t) not in {bare(s) for s in seen}:
            seen.append(t)
    if not seen:
        # The statement names no table (theLook's draft `return_rate`, 2026-09-26: an
        # expression with `tables: []`): propose every profiled table's main date, largest
        # table first — the grain a person picks then NAMES the table the metric is cut by.
        profiled = ((profile_entry or {}).get("tables") or {})
        ranked = sorted((n for n, tp in profiled.items() if isinstance(tp, dict) and tp.get("primary_timestamp")),
                        key=lambda n: (-int((profiled[n].get("row_count") or 0) if str(profiled[n].get("row_count") or "0").lstrip("-").isdigit() else 0), n))
        return [{"grain": f"{n}.{profiled[n]['primary_timestamp']}", "table": n,
                 "column": str(profiled[n]["primary_timestamp"]), "type": "timestamp", "primary": True,
                 "fallback": True} for n in ranked]
    out: list[dict] = []
    for table in seen:
        columns = _table_columns(profile_entry or {}, bare(table))
        primary = _primary_date(profile_entry or {}, bare(table))
        rows = [(c, d) for c, d in columns.items() if _is_time(d)]
        if primary and primary not in {c for c, _ in rows}:
            rows.append((primary, columns.get(primary, "timestamp")))
        rows.sort(key=lambda cd: (cd[0] != primary, cd[0]))
        for column, dtype in rows:
            out.append({"grain": f"{table}.{column}", "table": table, "column": column,
                        "type": dtype, "primary": column == primary})
    return out


def final_select(tree: Any):
    """The SELECT whose row is the metric's value: the statement itself, or — for a query
    whose outermost node is not a SELECT — None. A ``WITH`` parses as the final SELECT
    carrying its CTEs, so the common multi-CTE case lands here."""
    from sqlglot import exp
    return tree if isinstance(tree, exp.Select) else None
