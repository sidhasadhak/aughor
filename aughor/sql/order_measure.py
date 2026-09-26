"""A ranked result must return what it is ranked BY.

``SELECT category FROM category_profit ORDER BY total_profit DESC`` answers "which
categories earn the most" with names alone. The reader sees a ranked list with no figure
behind it, a chart has no measure to draw (so a table is the only visualization it can
offer), and the model interpreting the rows cannot state a number it was never shown.

Measured 2026-09-26 over the stored findings: 10 of 750 ordered by a key their final
SELECT did not return, 8 of them pinned key-question findings, whose build-time SQL is
re-run (or re-read) on every exploration, so the same measureless evidence came back
each time.

``project_order_keys`` appends each outer ORDER BY key the SELECT list does not already
return. The rows and their order are unchanged (only a column is added), so the query
supports the same claim as before, with its measure visible.
"""
from __future__ import annotations


def project_order_keys(sql: str, dialect: str = "duckdb") -> str | None:
    """``sql`` with its unreturned outer ORDER BY keys appended to the SELECT list, or
    ``None`` when every key is already returned or the rewrite cannot be shown to be
    safe: a set operation, ``SELECT DISTINCT`` (adding a column changes what is distinct),
    a star projection (its output names are unknown), or SQL that does not parse.
    Never raises. Callers should still dry-run the result before adopting it."""
    if not sql or not sql.strip():
        return None
    try:
        import sqlglot
        from sqlglot import exp

        tree = sqlglot.parse_one(sql, read=dialect)
    except Exception:
        return None
    if not isinstance(tree, exp.Select) or tree.args.get("distinct"):
        return None
    order = tree.args.get("order")
    if order is None or not order.expressions or not tree.expressions:
        return None
    for p in tree.expressions:
        if isinstance(p, exp.Star) or (isinstance(p, exp.Column) and isinstance(p.this, exp.Star)):
            return None

    def _text(e) -> str:
        return e.sql(dialect=dialect).lower()

    returned_names = {(p.alias_or_name or "").lower() for p in tree.expressions}
    returned_exprs = {_text(p.this if isinstance(p, exp.Alias) else p) for p in tree.expressions}
    added = []
    for ordered in order.expressions:
        key = ordered.this
        if isinstance(key, exp.Literal):          # ORDER BY 2: positional, already returned
            continue
        if _text(key) in returned_exprs:          # the same expression is already selected
            continue
        if isinstance(key, exp.Column):
            if key.name.lower() in returned_names:   # a selected alias, or a same-named column
                continue
            added.append(key.copy())
            returned_names.add(key.name.lower())
        else:                                     # ORDER BY SUM(x): an expression needs a name
            alias = "sort_value"
            n = 1
            while alias in returned_names:
                n += 1
                alias = f"sort_value_{n}"
            added.append(exp.alias_(key.copy(), alias))
            returned_names.add(alias)
        returned_exprs.add(_text(key))
    if not added:
        return None
    try:
        out = tree.copy()
        out.set("expressions", [*out.expressions, *added])
        return out.sql(dialect=dialect, pretty=True)
    except Exception:
        return None
