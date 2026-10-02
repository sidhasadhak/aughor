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

A statement that FILTERS the backwards rows out (`WHERE shipped_at >= created_at`) is asked
the same question with that filter lifted. Measured 2026-10-01: told to measure from `orders`,
the Agent re-ran its fulfilment query with exactly that filter; the guard, counting over the
filtered rows, found none and said nothing; the re-run replaced the flagged result and the
answer went out at HIGH confidence — ship times 1 to 4.4 hours short per centre, and the
second-slowest centre misnamed. Leaving the rows out is a finding too, with how many it left.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from types import SimpleNamespace
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

#: Probe counts by (connection, probe SQL). The probe drops a statement's projections, grouping,
#: order and limit, so the durations one run measures over the same rows — by month, by centre,
#: overall, a repair of the same statement — probe the same SQL, and its counts do not change
#: within minutes. One probe per distinct set of rows, not one per statement.
_PROBE_CACHE: dict[tuple[str, str, str, str], tuple[float, list]] = {}
_PROBE_TTL_S = 600.0
_PROBE_CACHE_MAX = 256


def _probe(conn: Any, sql: str) -> Any:
    """The probe's result, from a recent identical probe on this connection when there is one. Keyed
    by the schema and dataset too: one connection reads several, and the same SQL reads other rows."""
    conn_id = str(getattr(conn, "_connection_id", "") or "")
    key = (conn_id, str(getattr(conn, "_schema_name", "") or ""), str(getattr(conn, "_dataset", "") or ""), sql)
    hit = _PROBE_CACHE.get(key) if conn_id else None
    if hit is not None and time.monotonic() - hit[0] < _PROBE_TTL_S:
        return SimpleNamespace(rows=hit[1], error=None)
    result = conn.execute("__time_order_probe__", sql, internal=True)
    if conn_id and not getattr(result, "error", None) and getattr(result, "rows", None):
        if len(_PROBE_CACHE) >= _PROBE_CACHE_MAX:
            _PROBE_CACHE.pop(next(iter(_PROBE_CACHE)))
        _PROBE_CACHE[key] = (time.monotonic(), [list(r) for r in result.rows])
    return result


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
    #: The statement's own filter leaves these rows out (`WHERE end >= start`): the counts are
    #: of the rows it would measure without that filter.
    left_out: bool = False
    #: The column ``table`` and its one parent both carry, named for the parent (`order_id`
    #: for `orders`) — how to bring the parent in. "" when there is no such column.
    join_on: str = ""

    @property
    def share(self) -> float:
        return self.inverted / self.measured if self.measured else 0.0

    def detail(self) -> str:
        said = (f"{self.end} is earlier than {self.start} on {self.share:.1%} of the rows measured "
                f"({self.inverted:,} of {self.measured:,})")
        return f"{said}; the statement's filter leaves them out" if self.left_out else said

    def caveat(self) -> str:
        """What to do, parent first: the 2026-10-01 re-run dropped 30% of `order_items` rows
        when `orders` carried the same two timestamps, and dropping them keeps only the rows
        whose timestamps happen to agree."""
        end, start = self.end.split(".")[-1], self.start.split(".")[-1]
        rows = f"each {self.table} row" if self.table else "each row"
        if self.parents:
            names = " and ".join(self.parents)
            what = (f"Measure from the record {rows} belongs to first — {names} also "
                    f"{'carries' if len(self.parents) == 1 else 'carry'} {end} and {start}"
                    + (f" (join it on {self.join_on})" if self.join_on else ""))
        else:
            what = f"Measure from the timestamps of the record {rows} belongs to, if it carries its own"
        if self.left_out:
            return (f"time-order guard: the statement leaves out the rows where {self.end} is earlier "
                    f"than {self.start} — {self.share:.1%} of the rows it would measure "
                    f"({self.inverted:,} of {self.measured:,}) — so its result covers only the rows "
                    f"whose timestamps happen to agree. {what}.")
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


def _bare(e: Optional[exp.Expression]) -> Optional[exp.Expression]:
    while isinstance(e, exp.Paren):
        e = e.this
    return e


def _same_column(a: Optional[exp.Column], b: exp.Column) -> bool:
    """The same column, read through a qualifier only one side wrote (`shipped_at`, `oi.shipped_at`)."""
    if a is None or a.name.lower() != b.name.lower():
        return False
    return not a.table or not b.table or a.table.lower() == b.table.lower()


def _is_zero(e: Optional[exp.Expression]) -> bool:
    e = _bare(e)
    return isinstance(e, exp.Literal) and not e.is_string and e.this in ("0", "0.0")


def _keeps_ordered(pred: exp.Expression, end: exp.Column, start: exp.Column) -> bool:
    """Does ``pred`` keep only the rows where ``end`` is not before ``start`` — the filter that
    leaves the backwards rows out? `end >= start`, `start <= end` (strict too), `NOT end < start`,
    or the duration itself `>= 0` / `> 0`, through any cast."""
    p = _bare(pred)

    def cmp(node, kinds, left, right) -> bool:
        node = _bare(node)
        return (isinstance(node, kinds) and _same_column(_column(node.this), left)
                and _same_column(_column(node.expression), right))

    def diff(node) -> bool:
        node = _bare(node)
        return (isinstance(node, _DIFFS) and _same_column(_column(node.this), end)
                and _same_column(_column(node.expression), start))

    if isinstance(p, exp.Not):
        return cmp(p.this, exp.LT, end, start) or cmp(p.this, exp.GT, start, end)
    if cmp(p, (exp.GTE, exp.GT), end, start) or cmp(p, (exp.LTE, exp.LT), start, end):
        return True
    if isinstance(p, (exp.GTE, exp.GT)):
        return diff(p.this) and _is_zero(p.expression)
    if isinstance(p, (exp.LTE, exp.LT)):
        return _is_zero(p.this) and diff(p.expression)
    return False


def _conjuncts(e: Optional[exp.Expression]) -> list[exp.Expression]:
    e = _bare(e)
    if e is None:
        return []
    if isinstance(e, exp.And):
        return _conjuncts(e.this) + _conjuncts(e.expression)
    return [e]


def left_out_pairs(scope: exp.Select, pairs: list) -> set[int]:
    """The pairs whose backwards rows ``scope``'s own WHERE leaves out."""
    where = scope.args.get("where")
    preds = _conjuncts(where.this) if where is not None else []
    return {i for i, (end, start) in enumerate(pairs) if any(_keeps_ordered(p, end, start) for p in preds)}


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


def _join_on(table: str, parent: str, column_types: dict) -> str:
    """The column ``table`` and ``parent`` both carry that is named for the parent —
    `order_id` for `orders` — or "". Told only "orders also carries shipped_at", the analyst
    of 2026-10-01 did not bring orders in; the key is how to."""
    cols: dict[str, set] = {}
    for key in column_types or {}:
        t, _, c = str(key).rpartition(".")
        if t:
            cols.setdefault(t.split(".")[-1].lower(), set()).add(c.lower())
    key = f"{parent.lower().removesuffix('s')}_id"
    return key if key in cols.get(table.lower(), set()) and key in cols.get(parent.lower(), set()) else ""


def probe_sql(tree: exp.Expression, scope: exp.Select, pairs: list, dialect: str) -> str:
    """Two counts per pair over the scope's own rows: how many run backwards, how many are
    measured at all. Grouping, ordering and limits go — the question is about every row the
    duration is taken over — and the statement's CTEs come along, since the scope may read them.

    A filter that leaves a pair's backwards rows out is lifted, so that pair is counted over the
    rows the statement would measure without it; a pair nothing filtered is still counted over
    the statement's own rows — the lifted filters become its condition."""
    probe = scope.copy()
    for key in ("group", "order", "limit", "offset", "having", "qualify", "distinct"):
        probe.set(key, None)
    lifted: list[exp.Expression] = []
    where = probe.args.get("where")
    if where is not None:
        kept = []
        for pred in _conjuncts(where.this):
            (lifted if any(_keeps_ordered(pred, e, s) for e, s in pairs) else kept).append(pred)
        if lifted:
            probe.set("where", exp.Where(this=exp.and_(*kept)) if kept else None)
    filtered = left_out_pairs(scope, pairs)
    cols = []
    for i, (end, start) in enumerate(pairs):
        e, s = end.sql(dialect=dialect), start.sql(dialect=dialect)
        own = "" if i in filtered or not lifted else \
            " AND ".join(f"({p.sql(dialect=dialect)})" for p in lifted) + " AND "
        cols.append(sqlglot.parse_one(
            f"SUM(CASE WHEN {own}{e} < {s} THEN 1 ELSE 0 END) AS inverted_{i}", read=dialect))
        cols.append(sqlglot.parse_one(
            f"SUM(CASE WHEN {own}{e} IS NOT NULL AND {s} IS NOT NULL THEN 1 ELSE 0 END) AS measured_{i}",
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
        filtered = left_out_pairs(scope, pairs)
        try:
            result = _probe(conn, probe_sql(tree, scope, pairs, dialect))
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
                                             table=_table_of(end, scope), left_out=i in filtered))
            elif i in filtered and measured and not inverted:
                # The filter keeps rows that were all in order anyway. Q4's answer (2026-10-01) said it
                # measured "orders with valid timestamps" over a filter that excluded none.
                run.notes.append(f"time-order guard: the statement's filter keeping {end.sql()} at or after "
                                 f"{start.sql()} leaves out no rows — none of the {measured:,} it measures run "
                                 "backwards — so the result is over every row; say no rows were excluded.")
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
            if len(f.parents) == 1 and f.table:
                f.join_on = _join_on(f.table, f.parents[0], types)
    return run
