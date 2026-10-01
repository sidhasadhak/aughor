"""A duration measured between two timestamps that run backwards on a real share of rows.

Measured 2026-10-01 on theLook (BigQuery): in orders with more than one item, 19,360 of 33,272
`order_items` rows are recorded as shipped BEFORE they were created. A duration taken between
those two columns is negative on those rows, and an average over them read about half a day
where every order took 1.48 days to ship: the Agent published a fulfilment time of 3.12 days
whose true value is 3.98. The statement was correct SQL; nothing in it was wrong but the rows.

So this guard asks the rows. For each duration a statement measures between two columns —
`DATE_DIFF`, `TIMESTAMP_DIFF`, `DATETIME_DIFF`, `DATEDIFF` in any dialect sqlglot reads — it
counts, over the same FROM, JOIN and WHERE, how often the end precedes the start. A pair that
runs backwards on at least :data:`INVERTED_SHARE` of the rows it measures is a finding, carried
as a caveat with its share. It never rewrites and never blocks: the reader and the model decide
what to measure from instead, and the caveat says what is wrong with this one.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import sqlglot
from sqlglot import exp

from aughor.sql.guard_run import GuardRun, why

#: The share of measured rows at which a backwards pair is named. Below it a few stray rows;
#: at it, an average over the pair has visibly moved.
INVERTED_SHARE = 0.01
#: At most this many pairs are probed per statement — one probe per SELECT that measures them.
_MAX_PAIRS = 6

_DIFFS = (exp.DateDiff, exp.TimestampDiff, exp.DatetimeDiff)
#: What may wrap a column inside a duration without changing which moment it is.
_WRAPPERS = (exp.Cast, exp.TryCast, exp.Paren, exp.Date, exp.TsOrDsToDate)
_DIFF_WORD = re.compile(r"\b(date|timestamp|datetime)_?diff\b", re.I)


@dataclass
class Inverted:
    """One duration whose end precedes its start on a share of the rows it measures."""
    end: str
    start: str
    inverted: int
    measured: int
    #: The table the two columns are read from, and other tables that carry both columns —
    #: the record these rows belong to, usually (`orders` for `order_items`).
    table: str = ""
    parents: tuple = field(default_factory=tuple)

    @property
    def share(self) -> float:
        return self.inverted / self.measured if self.measured else 0.0

    def detail(self) -> str:
        return (f"{self.end} is earlier than {self.start} on {self.share:.1%} of the rows measured "
                f"({self.inverted:,} of {self.measured:,})")

    def caveat(self) -> str:
        """What to do, parent first: the 2026-10-01 re-run dropped 30% of `order_items` rows
        when `orders` carried the same two timestamps, and dropping them keeps only the rows
        whose timestamps happen to agree."""
        end, start = self.end.split(".")[-1], self.start.split(".")[-1]
        rows = f"each {self.table} row" if self.table else "each row"
        if self.parents:
            names = " and ".join(self.parents)
            what = (f"Measure from the record {rows} belongs to first — {names} also "
                    f"{'carries' if len(self.parents) == 1 else 'carry'} {end} and {start}")
        else:
            what = f"Measure from the timestamps of the record {rows} belongs to, if it carries its own"
        return (f"time-order guard: {self.detail()} — a duration between them is negative there, "
                f"and an average over them is pulled down. {what}; leaving the backwards rows out "
                "keeps only the ones whose timestamps happen to agree.")


def _column(e: Optional[exp.Expression]) -> Optional[exp.Column]:
    while isinstance(e, _WRAPPERS):
        e = e.this
    return e if isinstance(e, exp.Column) else None


def duration_pairs(tree: exp.Expression) -> list[tuple[exp.Select, list[tuple[exp.Column, exp.Column]]]]:
    """Each SELECT that measures a duration between two columns, with its (end, start) pairs.
    sqlglot reads every dialect's spelling into one node whose ``this`` is the end."""
    scopes: dict[int, tuple[exp.Select, list]] = {}
    seen: set[tuple[int, str, str]] = set()
    for node in tree.find_all(*_DIFFS):
        end, start = _column(node.this), _column(node.expression)
        scope = node.find_ancestor(exp.Select)
        if end is None or start is None or scope is None:
            continue
        key = (id(scope), end.sql(), start.sql())
        if key in seen:
            continue
        seen.add(key)
        scopes.setdefault(id(scope), (scope, []))[1].append((end, start))
    out, n = [], 0
    for scope, pairs in scopes.values():
        pairs = pairs[: max(0, _MAX_PAIRS - n)]
        n += len(pairs)
        if pairs:
            out.append((scope, pairs))
    return out


def _table_of(col: exp.Column, scope: exp.Select) -> str:
    """The table a column is read from in ``scope``: its qualifier resolved through the scope's
    own FROM and JOINs, or the scope's only table when it is unqualified. "" when unknown."""
    tables = [t for t in scope.find_all(exp.Table) if t.find_ancestor(exp.Select) is scope]
    by_alias = {(t.alias_or_name or "").lower(): (t.name or "").lower() for t in tables}
    if col.table:
        return by_alias.get(col.table.lower(), "")
    return (tables[0].name or "").lower() if len(tables) == 1 else ""


def _parents(table: str, end: str, start: str, column_types: dict) -> tuple:
    """Other tables that carry both columns (``column_types`` keys are "table.column")."""
    carrying: dict[str, set] = {}
    for key in column_types or {}:
        t, _, c = str(key).rpartition(".")
        if t and c in (end, start):
            carrying.setdefault(t.split(".")[-1], set()).add(c)
    return tuple(sorted(t for t, cols in carrying.items() if cols == {end, start} and t != table)[:2])


def probe_sql(tree: exp.Expression, scope: exp.Select, pairs: list, dialect: str) -> str:
    """Two counts per pair over the scope's own rows: how many run backwards, how many are
    measured at all. Grouping, ordering and limits go — the question is about every row the
    duration is taken over — and the statement's CTEs come along, since the scope may read them."""
    probe = scope.copy()
    for key in ("group", "order", "limit", "offset", "having", "qualify", "distinct"):
        probe.set(key, None)
    cols = []
    for i, (end, start) in enumerate(pairs):
        e, s = end.sql(dialect=dialect), start.sql(dialect=dialect)
        cols.append(sqlglot.parse_one(
            f"SUM(CASE WHEN {e} < {s} THEN 1 ELSE 0 END) AS inverted_{i}", read=dialect))
        cols.append(sqlglot.parse_one(
            f"SUM(CASE WHEN {e} IS NOT NULL AND {s} IS NOT NULL THEN 1 ELSE 0 END) AS measured_{i}",
            read=dialect))
    probe.set("expressions", cols)
    for key in ("with_", "with"):
        ctes = tree.args.get(key)
        if ctes is not None and scope is not tree:
            probe.set(key, ctes.copy())
            break
    return probe.sql(dialect=dialect)


def time_order_check(conn: Any, sql: str, dialect: str = "duckdb",
                     column_types: Optional[Callable[[], dict]] = None) -> Optional[GuardRun]:
    """The guard's run over ``sql``, or None when the statement measures no duration between
    two columns (nothing to check, and nothing said). ``column_types`` — read only when a
    duration runs backwards — lets the caveat name the table that carries the same two
    timestamps. Never raises."""
    try:
        tree = sqlglot.parse_one(sql, read=dialect)
    except Exception:
        tree = None
    run = GuardRun("time-order")
    if tree is None:
        if not _DIFF_WORD.search(sql or ""):
            return None
        run.unchecked.append(f"the statement could not be read in {dialect}'s dialect to find its durations")
        return run
    scopes = duration_pairs(tree)
    if not scopes:
        return None
    for scope, pairs in scopes:
        names = ", ".join(f"{e.sql()} − {s.sql()}" for e, s in pairs)
        try:
            result = conn.execute("__time_order_probe__", probe_sql(tree, scope, pairs, dialect),
                                  internal=True)
        except Exception as exc:  # noqa: BLE001 — a probe that raised is a part not checked
            run.unchecked.append(f"{names}: {why(exc)}")
            continue
        if getattr(result, "error", None) or not getattr(result, "rows", None):
            run.unchecked.append(f"{names}: {why(getattr(result, 'error', '') or 'the probe returned no row')}")
            continue
        row = list(result.rows[0])
        for i, (end, start) in enumerate(pairs):
            try:
                inverted, measured = int(float(row[2 * i] or 0)), int(float(row[2 * i + 1] or 0))
            except (TypeError, ValueError, IndexError):
                run.unchecked.append(f"{end.sql()} − {start.sql()}: the probe's counts did not read as numbers")
                continue
            if measured and inverted and inverted / measured >= INVERTED_SHARE:
                run.findings.append(Inverted(end.sql(), start.sql(), inverted, measured,
                                             table=_table_of(end, scope)))
    if run.findings and column_types is not None:
        try:
            types = column_types() or {}
        except Exception as exc:  # noqa: BLE001 — the caveat stands without the parent's name
            from aughor.kernel.errors import tolerate
            tolerate(exc, "time-order guard: column types unavailable; the caveat names no parent",
                     counter="sql.time_order_parents")
            types = {}
        for f in run.findings:
            f.parents = _parents(f.table, f.end.split(".")[-1].lower(), f.start.split(".")[-1].lower(), types)
    return run
