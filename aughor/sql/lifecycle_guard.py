"""Lifecycle filter enforcement — a prompt is not a guard.

The utilization lens's claim ("paid units over available capacity") is only correct
over units that actually consumed capacity: a cancelled ticket never sat in the seat,
a cancelled flight never offered it. The probed lifecycle rule ("tickets.segment_status:
KEEP 'flown'") was injected into the planner prompt twice — plan_user, then plan_system —
and the live planner IGNORED it both times while obeying its neighbours (the same run
honoured the grouping rule sitting beside it). The claim silently moved between
77.7/79.4 and 74.5/77.2 depending on which reading the model felt like.

So the filter is now ENFORCED after planning, deterministically: every SELECT that
reads a ruled table gets `col IN (keep…)` appended to its own WHERE, at its own grain —
unless that scope already filters the column (a planner that obeyed is left alone).
sqlglot AST pass; fail-open to the ORIGINAL SQL on any parse/build error, because a
broken repair is worse than an unpinned reading. The column's existence is already
proven — the probe read DISTINCT values off exactly `table.column` moments earlier.
"""
from __future__ import annotations

from typing import Optional

import sqlglot
from sqlglot import exp


def enforce_lifecycle_filters(
    sql: str, rules: list, dialect: str = "duckdb",
) -> tuple[str, list]:
    """Return ``(sql, applied)`` — the SQL with every ruled table filtered to its KEEP
    values, and a list of ``"table.column"`` strings actually injected. ``rules`` is
    ``[{"table": ..., "column": ..., "keep": [...]}]`` (see loss_signals.lifecycle_rules).
    The input SQL is returned unchanged when there is nothing to do or on any failure.
    """
    if not sql or not rules:
        return sql, []
    by_table = {}
    for r in rules:
        tbl, col, keep = r.get("table"), r.get("column"), r.get("keep") or []
        if tbl and col and keep:
            by_table[str(tbl).lower()] = (str(col), [str(v) for v in keep])
    if not by_table:
        return sql, []
    try:
        tree = sqlglot.parse_one(sql, read=dialect)
        applied: list = []
        seen: set = set()                      # (select-node id, table alias) — apply once
        for tbl_node in list(tree.find_all(exp.Table)):
            rule = by_table.get(tbl_node.name.lower())
            if not rule:
                continue
            select = tbl_node.find_ancestor(exp.Select)
            if select is None:
                continue
            col_name, keep = rule
            ref = tbl_node.alias or tbl_node.name
            key = (id(select), ref.lower())
            if key in seen:
                continue
            seen.add(key)
            if _scope_already_filters(select, col_name, ref):
                continue                        # the planner obeyed — leave its filter alone
            cond = exp.In(
                this=exp.Column(this=exp.to_identifier(col_name),
                                table=exp.to_identifier(ref)),
                expressions=[exp.Literal.string(v) for v in keep],
            )
            select.where(cond, copy=False)
            applied.append(f"{tbl_node.name}.{col_name}")
        if not applied:
            return sql, []
        return tree.sql(dialect=dialect), applied
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "lifecycle guard could not repair; the original SQL runs",
                 counter="sql.lifecycle_guard_failed")
        return sql, []


def _scope_already_filters(select: exp.Select, col_name: str, table_ref: str) -> bool:
    """Does this SELECT's own WHERE / JOIN conditions already mention the lifecycle
    column (bare, or qualified with this table's reference)? Scans only the scope's
    condition expressions — never nested subqueries, whose filters don't cover this
    scope's read of the table."""
    conds: list = []
    where = select.args.get("where")
    if where is not None:
        conds.append(where)
    for join in select.args.get("joins") or []:
        on = join.args.get("on")
        if on is not None:
            conds.append(on)
    want = col_name.lower()
    ref = (table_ref or "").lower()
    for cond in conds:
        for col in cond.find_all(exp.Column):
            if col.name.lower() == want and (not col.table or col.table.lower() == ref):
                return True
    return False


def lifecycle_transform(rules: list, dialect: str = "duckdb",
                        on_apply=None) -> Optional[callable]:
    """A per-query SQL transform for ``run_analysis_phase(sql_transform=)``, or None
    when there are no rules. ``on_apply(applied)`` is called when a repair landed —
    the observability hook (a guard that fires silently is unauditable)."""
    if not rules:
        return None

    def _t(sql: str) -> str:
        out, applied = enforce_lifecycle_filters(sql, rules, dialect=dialect)
        if applied and on_apply is not None:
            try:
                on_apply(applied)
            except Exception as exc:
                from aughor.kernel.errors import tolerate
                tolerate(exc, "lifecycle guard observability hook is best-effort",
                         counter="sql.lifecycle_guard_hook")
        return out

    return _t
