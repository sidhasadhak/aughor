"""Row-level-security SQL rewrite (Rec 7): AND per-table row filters into a query, deterministically.

Given ``{table: predicate}`` filters (from ``rbac/row_policy.resolve_row_filters``), rewrite every base-table
reference to that table as a filtered subquery — ``FROM orders o`` → ``FROM (SELECT * FROM orders WHERE
<predicate>) AS o`` — so a role physically cannot read rows outside its filter, regardless of the query's
shape (joins, aggregates, nested SELECTs). The alias is preserved so all downstream ``o.col`` references still
resolve. Mirrors the parse → walk/transform → regenerate idiom of ``sql/fanout.py`` / ``sql/identifiers.py``.

Fail-CLOSED by contract: a policy that cannot be applied safely RAISES — the caller (the connection-layer
enforcer) turns that into a blocked query, never a silent unfiltered run. In particular, if a policied table
name collides with a CTE name (the CTE could shadow the real table and slip data past the filter) we raise.
"""
from __future__ import annotations

import sqlglot
import sqlglot.expressions as exp


def inject_row_filters(sql: str, filters: dict[str, str], dialect: str = "duckdb") -> str:
    """Return ``sql`` with each policied base table wrapped in a filtered subquery. No-op when no policied
    table appears. Raises on parse failure or a policied-table/CTE-name collision (fail-closed)."""
    if not filters:
        return sql
    lc_filters = {k.lower(): v for k, v in filters.items()}
    # error_level=RAISE so an unparseable query fails CLOSED (the caller blocks) rather than slipping through.
    tree = sqlglot.parse_one(sql, read=dialect, error_level=sqlglot.ErrorLevel.RAISE)
    if tree is None:
        raise ValueError("row policy: SQL did not parse")

    cte_names = {(c.alias_or_name or "").lower() for c in tree.find_all(exp.CTE)}
    collision = cte_names & set(lc_filters)
    if collision:
        # A CTE shadowing a policied table could leak the real table's rows — refuse rather than guess.
        raise ValueError(f"row policy: CTE name collides with a policied table ({', '.join(sorted(collision))})")

    changed = False
    for tbl in list(tree.find_all(exp.Table)):
        name = (tbl.name or "").lower()
        if name in cte_names or name not in lc_filters:
            continue
        predicate = lc_filters[name]
        alias_name = tbl.alias or tbl.name
        bare = tbl.copy()                     # copy (not reuse) so the inner ref has its own nodes
        bare.set("alias", None)               # the alias moves to the wrapping subquery, not the inner table
        sub = sqlglot.select("*").from_(bare).where(predicate, dialect=dialect).subquery(alias=alias_name)
        tbl.replace(sub)
        changed = True

    return tree.sql(dialect=dialect) if changed else sql
