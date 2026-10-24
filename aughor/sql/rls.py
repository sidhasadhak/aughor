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

from dataclasses import dataclass
from typing import Optional

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


# ── Arc ED, ED-1 — an entity's declarations applied to the table that backs it ───────────────────────────────────────

@dataclass(frozen=True)
class EntityRule:
    """One entity's declarations as the SQL door applies them to the table that backs it (`ontology.security_sql`).

    ``predicate`` is the reader's objects as DuckDB SQL over the alias ``__rp`` (`ontology.security.row_condition`), or
    None when their rows are not restricted. ``masked`` pairs each column the reader may not read with why. ``refused``
    is set when the declarations cannot be applied to raw SQL at all (an entity backed by a query, whose base tables
    hold the rows it restricts): any statement reading the table is refused, with why."""
    table: str                       # the backing table's bare name, lower case
    schema: str = ""                 # its schema or dataset, lower case; "" matches any
    entity: str = ""
    predicate: Optional[str] = None
    masked: tuple = ()               # ((column, why), ...)
    refused: str = ""


class PolicyRefused(ValueError):
    """The statement reads what the reader may not; the message says what and why."""


def bare_name(name: str) -> str:
    return str(name or "").strip().strip('`"[]').lower()


def _matches(table: exp.Table, rule: EntityRule) -> bool:
    """Whether a table reference reads the rule's table. An unqualified reference, or a rule whose backing names no
    schema, matches by name alone: reading too many tables as policied refuses or narrows more than it must, while
    reading too few would leak, so the doubt is resolved toward the policy."""
    if bare_name(table.name) != rule.table:
        return False
    schema = bare_name(table.db)
    return not schema or not rule.schema or schema == rule.schema


def apply_entity_rules(sql: str, rules: list, dialect: str = "duckdb") -> tuple[str, list]:
    """``(sql, applied)``: ``sql`` with every table a rule restricts read through the reader's rows, and the rules
    whose rows were narrowed. Raises `PolicyRefused` when the statement reads a column masked for the reader (a
    ``SELECT *`` over the table included), or a table whose declarations cannot be applied, and on a parse failure or
    a policied table shadowed by a CTE (fail-closed, as `inject_row_filters`). Returns ``sql`` unchanged, as written,
    when no rule's table is read."""
    if not rules:
        return sql, []
    tree = sqlglot.parse_one(sql, read=dialect, error_level=sqlglot.ErrorLevel.RAISE)
    if tree is None:
        raise PolicyRefused("the statement could not be read, so the object policies could not be applied to it")
    cte_names = {(c.alias_or_name or "").lower() for c in tree.find_all(exp.CTE)}
    shadowed = cte_names & {r.table for r in rules}
    if shadowed:
        raise PolicyRefused(f"a CTE named {', '.join(sorted(shadowed))} shadows a table an object policy restricts")
    hits = [(t, r) for t in list(tree.find_all(exp.Table)) if bare_name(t.name) not in cte_names
            for r in rules if _matches(t, r)]
    if not hits:
        return sql, []
    for _t, r in hits:
        if r.refused:
            raise PolicyRefused(r.refused)
    for t, r in hits:
        if not r.masked:
            continue
        why = dict(r.masked)
        names = {bare_name(t.alias_or_name), bare_name(t.name)}
        for col in tree.find_all(exp.Column):
            if isinstance(col.this, exp.Star):
                continue
            name = bare_name(col.name)
            if name in why and (not col.table or bare_name(col.table) in names):
                raise PolicyRefused(f"{why[name]} — a statement that reads it is refused")
        home = t.find_ancestor(exp.Select)
        for e in (home.expressions if home is not None else []):
            star = isinstance(e, exp.Star) or (isinstance(e, exp.Column) and isinstance(e.this, exp.Star)
                                                and bare_name(e.table) in names)
            if star:
                first = next(iter(why.values()))
                raise PolicyRefused(f"{first} — `SELECT *` over {t.name} would read it; name the columns instead")
    applied = []
    for t, r in hits:
        if r.predicate is None:
            continue
        condition = sqlglot.parse_one(f"SELECT 1 FROM _t AS __rp WHERE {r.predicate}", read="duckdb").args["where"].this
        inner = t.copy()
        inner.set("alias", exp.TableAlias(this=exp.to_identifier("__rp")))
        t.replace(exp.select("*").from_(inner).where(condition).subquery(alias=t.alias_or_name))
        applied.append(r)
    return (tree.sql(dialect=dialect) if applied else sql), applied
