"""Declared metric filters — a definition is its formula AND the rows it is over.

theLook's revenue is declared `SUM(sale_price)` over `status <> 'Cancelled'`. Measured
2026-09-29 on five Agent-mode runs: the formula reached every statement and the filter
reached none. July 2026 was published as 426,292.28 where the declared definition
measures 365,320.51 (1,099 of the 7,200 lines were cancelled), and ten category figures
ran 14.8–19.3% over — enough to put the wrong category in tenth place. No statement was
malformed: the intake pin copied the expression alone, one of the two metric prompt
blocks printed no filter, and the enforcement check compares formula text, so "used the
governed formula" was true of a statement over the wrong rows.

So the filter is ENFORCED on the statement, the way `lifecycle_guard` enforces a probed
lifecycle rule: every SELECT that reads a declared table AND computes the declared
formula there gets the declared filter on its own WHERE.

Two refusals keep it from answering a different question than the one asked:

- a scope that has dealt with a column the filter names is left alone: it groups, shows
  or orders by it, or a condition on it keeps only the values it lists or names a value the
  filter names (`_dealt_with`). "Revenue by status" and "how much was cancelled" have dealt
  with `status` on purpose, and a filter added there would delete the row the question is
  about. Naming the column is not enough: `status IS NOT NULL` keeps every cancelled line;
- the rules are the caller's, and the caller passes only metrics the QUESTION targets
  (`semantic.enforcement.declared_filter_rules`). `COUNT(id)` is a declared formula too,
  and a statement that counts a table is not thereby asking for units sold.

The filter is a WHERE on the scope, not a condition inside the aggregate: it narrows
every figure that scope computes to the declared rows, which keeps a ratio's numerator
and denominator over one population. The receipt names the table and the filter, so that
narrowing is said.

A statement often hands the table's rows on before it aggregates them — the period
comparison the baseline plans selects `sale_price, order_id` into a CTE and sums THAT.
One such step is followed: when the scope computing the formula reads a CTE or a derived
table that itself reads the declared table at the table's own grain (no GROUP BY, no
aggregate, no DISTINCT) and hands the formula's columns on under their own names, the
filter goes on that inner scope. Anything further removed is left alone and reads as a
drift on the receipt, which is what it is.

sqlglot AST pass; the input SQL is returned unchanged when there is nothing to do or on
any failure, because a broken repair is worse than an unfiltered reading.
"""
from __future__ import annotations

import re
from typing import Optional

import sqlglot
from sqlglot import exp

_WS = re.compile(r"\s+")


def _bare(node: exp.Expression, dialect: str) -> str:
    """The expression with table qualifiers and quoting dropped, case and whitespace
    folded — `SUM(oi.sale_price)` and `sum( "sale_price" )` are one formula."""
    clone = node.copy()
    for col in clone.find_all(exp.Column):
        for part in ("table", "db", "catalog"):
            col.set(part, None)
    for ident in clone.find_all(exp.Identifier):
        ident.set("quoted", False)
    return _WS.sub("", clone.sql(dialect=dialect).lower())


def _unwrap(node: exp.Expression) -> exp.Expression:
    while isinstance(node, (exp.Alias, exp.Paren)):
        node = node.this
    return node


def _formula(text: str, dialect: str) -> Optional[exp.Expression]:
    """A declared formula as one expression, or None when it is not one (a whole SELECT,
    or text that does not parse) — such a metric has no shape to look for."""
    body = (text or "").strip().rstrip(";")
    if not body:
        return None
    try:
        node = _unwrap(sqlglot.parse_one(f"SELECT {body}", read=dialect).expressions[0])
    except Exception:
        return None
    if isinstance(node, (exp.Subquery, exp.Select, exp.Column, exp.Literal)):
        return None
    return node


def _conjuncts(node: exp.Expression) -> list:
    node = node.this if isinstance(node, exp.Paren) else node
    if isinstance(node, exp.And):
        return _conjuncts(node.this) + _conjuncts(node.expression)
    return [node]


def measure_of(text: str, dialect: str = "duckdb") -> Optional[dict]:
    """A declared metric as ``{"formula", "tables", "filters"}``, or None.

    A metric is stored in one of two shapes and the first version of this guard read only
    one. It was built against `data/metrics.json`, where revenue is the expression
    ``SUM(sale_price)`` — the LEGACY file. The catalogue the platform serves is
    `data/metrics.instance.json`, where revenue is the statement
    ``SELECT (SUM(sale_price)) AS revenue FROM order_items WHERE status <> 'Cancelled'``.
    Live, the guard was handed that statement as a "formula", found no shape in it, and
    rewrote nothing: three re-runs on 2026-09-29 passed `guarded:declared-filter` and
    published 426,292.28 again.

    So both shapes are read. An expression gives its formula and nothing else. A statement
    gives its one measure, the one table it reads and the conditions of its WHERE — and
    only when it is exactly that: one projection, one table, no join, grouping, CTE or
    limit. Anything richer is a query, not a measure over a table's rows, and there is no
    single filter to lift out of it."""
    body = (text or "").strip().rstrip(";").strip()
    if not body:
        return None
    try:
        tree = sqlglot.parse_one(body, read=dialect)
    except Exception:
        tree = None
    if not isinstance(tree, exp.Select):
        node = _formula(body, dialect)
        return ({"formula": node.sql(dialect=dialect), "tables": [], "filters": []}
                if node is not None else None)
    # sqlglot spells two of these keys with a trailing underscore in some versions and
    # without in others (`from_` / `with_`); reading one spelling silently finds nothing.
    source = tree.args.get("from_") or tree.args.get("from")
    table = source.this if source is not None else None
    if (len(tree.expressions) != 1 or not isinstance(table, exp.Table)
            or any(tree.args.get(k) for k in ("joins", "group", "having", "distinct", "limit",
                                              "qualify", "with_", "with"))
            or list(tree.find_all(exp.Subquery))):
        return None
    node = _unwrap(tree.expressions[0])
    if isinstance(node, (exp.Column, exp.Literal)) or not list(node.find_all(exp.AggFunc)):
        return None
    where = tree.args.get("where")
    return {"formula": node.sql(dialect=dialect), "tables": [table.name],
            "filters": [c.sql(dialect=dialect) for c in _conjuncts(where.this)] if where else []}


def same_condition(a: str, b: str, dialect: str = "duckdb") -> bool:
    """Two filters that say the same thing, however each was typed."""
    x, y = _condition(a, dialect), _condition(b, dialect)
    return x is not None and y is not None and _bare(x, dialect) == _bare(y, dialect)


def same_formula(a: str, b: str, dialect: str = "duckdb") -> bool:
    x, y = _formula(a, dialect), _formula(b, dialect)
    return x is not None and y is not None and _bare(x, dialect) == _bare(y, dialect)


def _condition(text: str, dialect: str) -> Optional[exp.Expression]:
    body = (text or "").strip().rstrip(";")
    if not body:
        return None
    try:
        where = sqlglot.parse_one(f"SELECT 1 WHERE {body}", read=dialect).args.get("where")
    except Exception:
        return None
    return where.this if where is not None else None


def _own(select: exp.Select, kind) -> list:
    """The nodes of ``kind`` that belong to this SELECT itself — never a nested
    subquery's or a CTE's, whose rows are another scope's business."""
    return [n for n in select.find_all(kind) if n.find_ancestor(exp.Select) is select]


def _computes(select: exp.Select, formula: exp.Expression, ref: str, only_ref: bool,
              dialect: str) -> bool:
    """Does this scope compute the declared formula over the table known here as ``ref``?
    A qualified column must name that table; an unqualified one is taken to, unless the
    scope reads the table under several names and so cannot say which."""
    want = _bare(formula, dialect)
    for node in _own(select, type(formula)):
        if _bare(node, dialect) != want:
            continue
        named = {c.table.lower() for c in node.find_all(exp.Column) if c.table}
        if named == {ref.lower()} or (not named and only_ref):
            return True
    return False


def _dealt_with(select: exp.Select, column: str, ref: str, values: set) -> bool:
    """Has this scope chosen its own rows of ``column`` — so that the declared filter on it would
    answer a different question? ``values`` are the ones the filter names, as written.

    It has when it shows the column — groups, projects or orders by it, every value in sight
    ("revenue by status") — and when a condition on the column keeps only the values it lists
    (``status = 'Complete'``, ``IN (…)``) or names a value the filter names (``status =
    'Cancelled'`` measures the cancelled rows; ``status <> 'Cancelled'`` IS the filter). A
    condition that does neither keeps the rows the filter is there to remove: the analyst wrote
    ``status IS NOT NULL`` after the guard had filtered its statement three times, and July's
    revenue was published with every cancelled line in it — 418,928.40 where the declared figure
    is 359,224.30 (theLook, 2026-10-02). Naming the column was all this used to ask. A filter that
    names no value (``sold_at IS NOT NULL``) is about the column itself, and any condition on the
    column has dealt with it."""
    want, ref = column.lower(), ref.lower()
    for col in _own(select, exp.Column):
        if col.name.lower() != want or (col.table and col.table.lower() != ref):
            continue
        if not values:
            return True
        cond = col.find_ancestor(exp.Predicate, exp.Select)
        if not isinstance(cond, exp.Predicate):
            return True                                  # shown, grouped or ordered by
        if {str(lit.this) for lit in cond.find_all(exp.Literal)} & values:
            return True                                  # names what the filter is about
        outer = cond.parent
        while isinstance(outer, exp.Paren):
            outer = outer.parent
        if isinstance(outer, exp.Not):
            continue                                     # an exclusion that names none of it
        if isinstance(cond, exp.EQ) and any(isinstance(side, exp.Literal)
                                            for side in (cond.this, cond.expression)):
            return True                                  # keeps only the value it names
        if (isinstance(cond, exp.In) and cond.expressions
                and all(isinstance(e, exp.Literal) for e in cond.expressions)):
            return True                                  # keeps only the values it lists
    return False


def _hands_on(inner: exp.Select, formula: exp.Expression, tables: set) -> Optional[exp.Table]:
    """The declared table ``inner`` reads at its own grain while handing the formula's
    columns on under their own names — or None. A scope that groups, aggregates or
    de-duplicates has changed what a row is, and a filter on it is a different claim."""
    if (inner.args.get("group") or inner.args.get("distinct")
            or _own(inner, exp.AggFunc)):
        return None
    reads = [t for t in _own(inner, exp.Table) if t.name.lower() in tables]
    need = {c.name.lower() for c in formula.find_all(exp.Column)}
    if len(reads) != 1 or not need:
        return None
    ref = (reads[0].alias or reads[0].name).lower()
    handed: set = set()
    for item in inner.expressions:
        node = item.this if isinstance(item, exp.Alias) else item
        if isinstance(node, exp.Star) or (isinstance(node, exp.Column)
                                          and isinstance(node.this, exp.Star)):
            return reads[0]
        if isinstance(node, exp.Column) and (not node.table or node.table.lower() == ref):
            out = (item.alias if isinstance(item, exp.Alias) else node.name).lower()
            if out == node.name.lower():
                handed.add(out)
    return reads[0] if need <= handed else None


def _sources(select: exp.Select, formula: exp.Expression, tables: set, ctes: dict) -> list:
    """``(ref, scope, table)`` for each way this SELECT reads a declared table: ``ref``
    is the name the rows go by HERE, ``scope`` the SELECT the filter belongs on (this
    one, or the inner one that hands the rows on) and ``table`` the declared table
    there."""
    out: list = []
    for node in _own(select, exp.Table):
        name = node.name.lower()
        if name in ctes and not node.db:                  # a CTE shadows a table of its name
            inner = ctes[name]
            table = _hands_on(inner, formula, tables) if inner is not select else None
            if table is not None:
                out.append((node.alias or node.name, inner, table))
        elif name in tables:
            out.append((node.alias or node.name, select, node))
    for sub in _own(select, exp.Subquery):
        inner = sub.this
        if (sub.alias and isinstance(inner, exp.Select)
                and isinstance(sub.parent, (exp.From, exp.Join))):
            table = _hands_on(inner, formula, tables)
            if table is not None:
                out.append((sub.alias, inner, table))
    return out


def enforce_metric_filters(sql: str, rules: list, dialect: str = "duckdb") -> tuple[str, list]:
    """Return ``(sql, applied)`` — the statement with each declared filter on the scopes
    that compute its metric, and one ``{"metric", "table", "filter"}`` per filter added.

    ``rules`` is ``[{"metric": name, "formula": sql, "tables": [...], "filters": [...]}]``.
    """
    if not sql or not rules:
        return sql, []
    try:
        tree = sqlglot.parse_one(sql, read=dialect)
        ctes = {c.alias.lower(): c.this for c in tree.find_all(exp.CTE)
                if c.alias and isinstance(c.this, exp.Select)}
        applied: list = []
        done: set = set()                      # (scope, table ref, filter text) — once each
        for rule in rules:
            formula = _formula(rule.get("formula") or "", dialect)
            tables = {str(t).split(".")[-1].lower() for t in (rule.get("tables") or []) if t}
            filters = [str(f) for f in (rule.get("filters") or []) if str(f).strip()]
            if formula is None or not tables or not filters:
                continue
            for select in list(tree.find_all(exp.Select)):
                sources = _sources(select, formula, tables, ctes)
                for ref, scope, table in sources:
                    if not _computes(select, formula, ref, len(sources) == 1, dialect):
                        continue
                    here = table.alias or table.name    # the table's name where the filter goes
                    for text in filters:
                        cond = _condition(text, dialect)
                        key = (id(scope), here.lower(), _WS.sub("", text.lower()))
                        if cond is None or key in done:
                            continue
                        done.add(key)
                        columns = {c.name for c in cond.find_all(exp.Column)}
                        values = {str(lit.this) for lit in cond.find_all(exp.Literal)}
                        if not columns or any(_dealt_with(select, c, ref, values)
                                              or _dealt_with(scope, c, here, values)
                                              for c in columns):
                            continue            # a scope has dealt with it — leave it alone
                        for col in cond.find_all(exp.Column):
                            if not col.table:
                                col.set("table", exp.to_identifier(here))
                        scope.where(cond, copy=False)
                        applied.append({"metric": str(rule.get("metric") or ""),
                                        "table": table.name, "filter": text})
        if not applied:
            return sql, []
        return tree.sql(dialect=dialect), applied
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "declared-filter guard could not repair; the original SQL runs",
                 counter="sql.metric_filter_guard_failed")
        return sql, []
