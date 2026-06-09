"""Relative (re-anchoring) monitor windows.

A monitor created from a Briefing finding inherits the finding's SQL, which carries a
FROZEN absolute date window (e.g. ``WHERE order_date >= '2023-12-31' AND order_date <=
'2024-12-30'``). That literal is correct the day it's made but drifts off the data as new
rows arrive — and a recurring monitor should track the *trailing* window, not a frozen one.

``reanchor_trailing_window`` slides every date literal in the SQL forward by the gap
between the window's end and the data's current activity edge, so the window keeps its
shape (a 12-month span stays 12 months) but always ends at the latest data. It is purely
additive: on any parse/resolve/query failure, or when the data isn't newer than the
window, it returns the SQL unchanged — it can only fix a stale window, never break a
working one.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
_MAX_SHIFT_DAYS = 200 * 365  # absurd-shift guard


def _parse_date(s: str) -> Optional[datetime]:
    s = str(s).strip()
    if not _DATE_RE.match(s):
        return None
    try:
        return datetime.fromisoformat(s[:19] if len(s) > 10 else s[:10])
    except ValueError:
        try:
            return datetime.strptime(s[:10], "%Y-%m-%d")
        except ValueError:
            return None


def _is_date_only(s: str) -> bool:
    return len(str(s).strip()) <= 10


def reanchor_trailing_window(sql: str, db, dialect: str = "duckdb") -> str:
    """Slide the SQL's absolute date window to end at the data's live activity edge.

    Returns ``sql`` unchanged on any failure or when no shift is warranted.
    """
    if not sql:
        return sql
    try:
        import sqlglot
        from sqlglot import exp
    except Exception:
        return sql

    try:
        tree = sqlglot.parse_one(sql, read=dialect)
    except Exception:
        return sql

    # ── Collect date-string literals that sit in a comparison with a column ──────
    # Each entry: (literal_node, parsed_date, column_node_or_None)
    found: list[tuple] = []

    def _record(lit, col):
        if not isinstance(lit, exp.Literal) or not lit.is_string:
            return
        d = _parse_date(lit.this)
        if d is not None:
            found.append((lit, d, col))

    for node in tree.find_all(exp.GT, exp.GTE, exp.LT, exp.LTE, exp.EQ):
        left, right = node.this, node.expression
        if isinstance(left, exp.Column):
            _record(right, left)
        elif isinstance(right, exp.Column):
            _record(left, right)
    for node in tree.find_all(exp.Between):
        col = node.this if isinstance(node.this, exp.Column) else None
        _record(node.args.get("low"), col)
        _record(node.args.get("high"), col)

    if not found:
        return sql

    # ── Window end = the latest literal; resolve its column's source table ──────
    found.sort(key=lambda t: t[1])
    end_lit, end_date, end_col = found[-1]
    if end_col is None:
        return sql

    # alias/name → fully-qualified table, excluding CTE names.
    cte_names = set()
    with_node = tree.args.get("with")
    if with_node:
        for cte in with_node.expressions:
            if cte.alias:
                cte_names.add(cte.alias.lower())

    alias_to_table: dict[str, str] = {}
    real_tables: list[str] = []
    for tbl in tree.find_all(exp.Table):
        name = (tbl.name or "").lower()
        if name in cte_names:
            continue
        fq = tbl.sql(dialect=dialect).split(" AS ")[0].strip()  # drop alias
        real_tables.append(fq)
        key = (tbl.alias or tbl.name or "").lower()
        if key:
            alias_to_table[key] = fq

    col_name = end_col.name
    qualifier = (end_col.table or "").lower()
    table = alias_to_table.get(qualifier)
    if table is None:
        # bare column → only safe when there is exactly one real table
        if len(set(real_tables)) == 1:
            table = real_tables[0]
        else:
            return sql

    # ── Query the live activity edge for that column (via the connection API) ───
    try:
        res = db.execute("__monitor_window__", f"SELECT MAX({col_name}) FROM {table}")
        if getattr(res, "error", None):
            logger.debug("reanchor: MAX query error: %s", res.error)
            return sql
        rows = list(getattr(res, "rows", None) or [])
    except Exception as exc:
        logger.debug("reanchor: MAX query failed: %s", exc)
        return sql
    if not rows:
        return sql
    first = rows[0]
    raw = list(first.values())[0] if isinstance(first, dict) else first[0]
    live_edge = _parse_date(str(raw)) if raw is not None else None
    if live_edge is None:
        return sql

    shift_days = (live_edge - end_date).days
    if shift_days <= 0 or shift_days > _MAX_SHIFT_DAYS:
        # data not newer than the window (already current / window in the future), or
        # an implausible shift — leave the SQL alone.
        return sql

    # ── Slide every collected literal forward by the same delta ─────────────────
    delta = timedelta(days=shift_days)
    for lit, d, _col in found:
        new_d = d + delta
        new_s = new_d.strftime("%Y-%m-%d") if _is_date_only(lit.this) else new_d.strftime("%Y-%m-%d %H:%M:%S")
        lit.set("this", new_s)

    try:
        out = tree.sql(dialect=dialect)
        sqlglot.parse_one(out, read=dialect)  # validate round-trip
        logger.info("reanchor: slid window +%d days to live edge %s", shift_days, live_edge.date())
        return out
    except Exception:
        return sql
