"""A period's last day, read whole.

A window over days is inclusive of its last day, and ``ts <= '2025-12-31'`` on a TIMESTAMP keeps
only that day's first instant. The prompts say so (each window written half-open, ``< 'the day
after'``), and the statements the platform writes itself say so (``CAST(col AS DATE) <= DATE …``),
but a model REPAIRING a statement rewrites its window as it likes. Measured on theLook's live
deep analysis (2026-10-09, runs ``5da59d8e`` and ``67da5dc3``): the breakdown was written
``CAST(created_at AS DATE) <= DATE '2025-12-31'``, failed to bind on a column of another table,
and the repair joined that table and wrote ``created_at <= '2025-12-31'`` — revenue from completed
orders in 2025 published as 608,504.54 where the whole year reads 610,184.21.

So the bound is read whole on the statement, the way `metric_filter_guard` puts a declared
filter there: ``col <= 'D'`` becomes ``col < 'D + 1 day'``, ``'D' >= col`` likewise, and
``col BETWEEN x AND 'D'`` becomes ``col >= x AND col < 'D + 1 day'`` — only when the schema says
``col`` is a TIMESTAMP or a DATETIME. On a DATE the two read the same, and a string column is not
the guard's to reinterpret, so neither is touched; nor is ``CAST(col AS DATE)``, a literal with a
time in it, or a column whose type the schema does not give (a CTE's, a derived table's). ``D``
keeps its own spelling (``'D'``, ``DATE 'D'``, ``CAST('D' AS DATE)``).

sqlglot AST pass; the statement comes back unchanged when there is nothing to do or on any
failure.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Optional

import sqlglot
from sqlglot import exp

_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIMESTAMP = re.compile(r"(?i)^\s*(timestamp|datetime)")
#: A cheap look before any parse or schema read: an upper bound that keeps a bare day — ``<= 'D'``, ``'D' >=``,
#: or a BETWEEN whose ``AND`` names one (in any of the three spellings).
_LIT = r"(?:DATE\s*|CAST\s*\(\s*)?'\d{4}-\d{2}-\d{2}'"
_CANDIDATE = re.compile(rf"(?i)<=\s*{_LIT}|'\d{{4}}-\d{{2}}-\d{{2}}'(?:\s+AS\s+DATE\s*\))?\s*>=")
_BETWEEN = re.compile(rf"(?i)\bbetween\b.*?\band\s*{_LIT}", re.S)


def may_close_on_a_day(sql: str) -> bool:
    """Could ``sql`` hold an inclusive bound on a bare day — worth reading the schema for?"""
    return bool(sql) and bool(_CANDIDATE.search(sql) or _BETWEEN.search(sql))


def _day(node: exp.Expression) -> Optional[str]:
    """The ISO day a bare date literal names — ``'D'``, ``DATE 'D'``, ``CAST('D' AS DATE)`` — else None."""
    if isinstance(node, exp.Literal) and node.is_string and _DAY.match(node.this):
        return node.this
    if (isinstance(node, (exp.Cast, exp.TryCast)) and node.to is not None and node.to.is_type("date")
            and isinstance(node.this, exp.Literal) and node.this.is_string and _DAY.match(node.this.this)):
        return node.this.this
    return None


def _after(node: exp.Expression, day: str) -> exp.Expression:
    """``node`` naming the day after ``day``, in ``node``'s own spelling."""
    nxt = exp.Literal.string((date.fromisoformat(day) + timedelta(days=1)).isoformat())
    if isinstance(node, exp.Literal):
        return nxt
    out = node.copy()
    out.this.replace(nxt)
    return out


def _types(schema: dict) -> dict[str, dict[str, str]]:
    """{bare table: {column: type}}, lower-cased; a bare name two tables share with different types is dropped."""
    out: dict[str, dict[str, str]] = {}
    clash: set[tuple[str, str]] = set()
    for table, cols in (schema or {}).items():
        bare = str(table).strip("`\"").rsplit(".", 1)[-1].lower()
        mine = out.setdefault(bare, {})
        for col, typ in (cols or {}).items():
            key, typ = str(col).lower(), str(typ or "")
            if key in mine and mine[key] != typ:
                clash.add((bare, key))
            mine[key] = typ
    for bare, key in clash:
        out[bare].pop(key, None)
    return out


def _timestamp(col: exp.Column, types: dict[str, dict[str, str]]) -> Optional[str]:
    """The TIMESTAMP/DATETIME type ``col`` has where it is read, or None — unknown counts as not."""
    select = col.find_ancestor(exp.Select)
    if select is None:
        return None
    tables = [t for t in select.find_all(exp.Table) if t.find_ancestor(exp.Select) is select]
    name = col.name.lower()
    if col.table:
        ref = col.table.lower()
        tables = [t for t in tables if (t.alias or t.name).lower() == ref]
    found = [types.get(t.name.lower(), {}).get(name) for t in tables]
    found = [t for t in found if t is not None]
    if len(found) != 1 or not _TIMESTAMP.match(found[0]):
        return None
    return found[0]


def read_last_days_whole(sql: str, schema: dict, dialect: str = "duckdb") -> tuple[str, list[dict]]:
    """``(sql, read)`` — the statement with each inclusive bound on a bare day over a TIMESTAMP or DATETIME
    column read through the whole day, and one ``{"column", "day", "type"}`` per bound changed.
    ``schema`` is ``{table: {column: type}}`` (`db.schema_render.parse_schema_column_types`)."""
    if not may_close_on_a_day(sql):
        return sql, []
    try:
        types = _types(schema)
        tree = sqlglot.parse_one(sql, read=dialect)
        read: list[dict] = []
        for node in list(tree.find_all(exp.LTE, exp.GTE, exp.Between)):
            if isinstance(node, exp.Between):
                col, day = node.this, _day(node.args.get("high"))
            elif isinstance(node, exp.LTE):
                col, day = node.this, _day(node.expression)
            else:                                            # 'D' >= col
                col, day = node.expression, _day(node.this)
            if not isinstance(col, exp.Column) or day is None:
                continue
            typ = _timestamp(col, types)
            if typ is None:
                continue
            if isinstance(node, exp.Between):
                low, high = node.args["low"], node.args["high"]
                node.replace(exp.Paren(this=exp.and_(exp.GTE(this=col.copy(), expression=low.copy()),
                                                     exp.LT(this=col.copy(), expression=_after(high, day)))))
            elif isinstance(node, exp.LTE):
                node.replace(exp.LT(this=col.copy(), expression=_after(node.expression, day)))
            else:
                node.replace(exp.GT(this=_after(node.this, day), expression=col.copy()))
            read.append({"column": col.sql(dialect=dialect), "day": day, "type": typ})
        if not read:
            return sql, []
        return tree.sql(dialect=dialect), read
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the last-day window guard could not read the statement; it runs as written",
                 counter="sql.day_window_guard_failed")
        return sql, []
