"""Query Builder Layer-3 — reverse-compile raw SQL → semantic chips.

The visual builder only had a FORWARD compiler (chips → SQL). This is the inverse: parse a
raw SELECT with SQLGlot and reconstruct the builder's chips — primary table, joins,
dimensions (plain columns + DATE_TRUNC grains), measures (SUM/AVG/COUNT/… or a custom
expression), filters (column op value), plus ORDER BY / LIMIT — so a pasted or
engine-generated query round-trips back into the visual builder for editing.

Deliberately honest about its limits: a shape the simple builder can't represent (a CTE,
a set operation, a subquery in FROM) returns ``{"ok": False, "reason": …}`` rather than a
lossy half-import. Within a flat SELECT it maps what it recognises and surfaces anything it
couldn't (``unmapped_filters``) instead of dropping it silently. Pure + dependency-light
(SQLGlot only); fully testable without a database.
"""

from __future__ import annotations

from typing import Optional

# SELECT-aggregate node type → the builder's AggFn label.
_AGG_LABEL = {
    "Sum": "SUM", "Avg": "AVG", "Min": "MIN", "Max": "MAX",
    "Stddev": "STDDEV", "Variance": "VARIANCE", "Median": "MEDIAN",
}
# comparison node type → the builder's FilterOp.
_CMP_OP = {"EQ": "=", "NEQ": "!=", "GT": ">", "GTE": ">=", "LT": "<", "LTE": "<="}
# DATE_TRUNC unit → the builder's dimension transform.
_TRUNC_TRANSFORM = {"day": "date", "month": "month", "year": "year",
                    "quarter": "quarter", "hour": "hour", "minute": "minute"}


def _table_of(col, dialect: str) -> str:
    return (getattr(col, "table", "") or "")


def _col_dim(col, alias: Optional[str]) -> dict:
    return {"col": col.name, "table": (col.table or ""), "transform": None, "alias": alias or None}


def decompile_sql(sql: str, dialect: str = "duckdb") -> dict:
    """Reverse-compile ``sql`` into the visual builder's chip structure.

    Returns ``{"ok": True, primary_table, joins[], dimensions[], measures[], filters[],
    order_by, limit, having, unmapped_filters[]}`` for a flat SELECT, or
    ``{"ok": False, "reason": …}`` for a shape the builder can't represent."""
    try:
        import sqlglot
        from sqlglot import exp
    except Exception:
        return {"ok": False, "reason": "SQL parser unavailable."}

    try:
        tree = sqlglot.parse_one(sql, read=dialect)
    except Exception as e:
        return {"ok": False, "reason": f"Could not parse SQL: {str(e)[:120]}"}

    if not isinstance(tree, exp.Select):
        return {"ok": False, "reason": "Only a single SELECT can be imported (no set-ops / DDL)."}
    if tree.args.get("with") or tree.find(exp.With):
        return {"ok": False, "reason": "Queries with CTEs (WITH …) can't be imported into the builder."}

    # FROM must be a single base table (a subquery source has no chip representation).
    # The arg key is "from_" in newer SQLGlot; find(From) is version-robust for a flat SELECT.
    from_ = tree.find(exp.From)
    base = from_.this if from_ else None
    if not isinstance(base, exp.Table):
        return {"ok": False, "reason": "FROM must be a base table (subquery sources aren't supported)."}
    primary_table = base.name
    alias_to_table = {(t.alias_or_name or "").lower(): t.name for t in tree.find_all(exp.Table)}

    # ── Joins ────────────────────────────────────────────────────────────────────
    joins = []
    for j in (tree.args.get("joins") or []):
        jt = j.this
        if not isinstance(jt, exp.Table):
            return {"ok": False, "reason": "Only base-table joins can be imported."}
        on = j.args.get("on")
        joins.append({
            "table": jt.name,
            "alias": jt.alias_or_name if jt.alias_or_name != jt.name else None,
            "side": (j.args.get("side") or j.args.get("kind") or "").upper() or "INNER",
            "on": on.sql(dialect=dialect) if on else "",
        })

    # ── SELECT → dimensions + measures ───────────────────────────────────────────
    dimensions: list = []
    measures: list = []
    for e in tree.expressions:
        alias = e.alias if isinstance(e, exp.Alias) else None
        body = e.this if isinstance(e, exp.Alias) else e
        if isinstance(body, exp.Star):
            continue   # SELECT * — nothing to chip
        if isinstance(body, exp.Column):
            dimensions.append(_col_dim(body, alias))
            continue
        # DATE_TRUNC('month', col) → a dimension with a grain transform. DuckDB parses this as
        # TimestampTrunc; the unit is a Var (MONTH) read via .text("unit").
        if isinstance(body, (exp.TimestampTrunc, exp.DateTrunc)):
            unit = (body.text("unit") or "").strip("'").lower()
            inner = body.this
            if isinstance(inner, exp.Column) and unit in _TRUNC_TRANSFORM:
                dimensions.append({"col": inner.name, "table": (inner.table or ""),
                                   "transform": _TRUNC_TRANSFORM.get(unit), "alias": alias or None})
                continue
        # Aggregates → measures.
        agg_label, agg_col, agg_table = _classify_aggregate(body, exp)
        if agg_label is not None:
            measures.append({"agg": agg_label, "col": agg_col, "table": agg_table,
                             "alias": alias or None, "customExpr": ""})
            continue
        # Anything else: a custom measure if it contains an aggregate, else a custom dimension.
        if list(body.find_all(exp.AggFunc)):
            measures.append({"agg": "CUSTOM", "col": "", "table": "",
                             "alias": alias or None, "customExpr": body.sql(dialect=dialect)})
        else:
            dimensions.append({"col": body.sql(dialect=dialect), "table": "",
                               "transform": None, "alias": alias or None})

    # ── WHERE → filters ──────────────────────────────────────────────────────────
    filters: list = []
    unmapped: list = []
    where = tree.args.get("where")
    if where is not None:
        for conj in _split_and(where.this, exp):
            f = _filter_of(conj, exp, dialect)
            (filters if f else unmapped).append(f or conj.sql(dialect=dialect))

    # ── ORDER BY / LIMIT / HAVING ────────────────────────────────────────────────
    order = tree.args.get("order")
    order_by = ", ".join(o.sql(dialect=dialect) for o in order.expressions) if order else ""
    limit_node = tree.args.get("limit")
    try:
        limit = int(limit_node.expression.name) if limit_node else 0
    except (TypeError, ValueError, AttributeError):
        limit = 0
    having = tree.args.get("having")
    having_raw = having.this.sql(dialect=dialect) if having else ""

    # Chips carry the REAL table name (the builder qualifies columns by table, not alias), so
    # resolve every alias back to its table. Unqualified columns ("") stay unqualified.
    def _resolve(t: str) -> str:
        return alias_to_table.get((t or "").lower(), t) if t else t
    for grp in (dimensions, measures, filters):
        for item in grp:
            item["table"] = _resolve(item.get("table", ""))

    return {
        "ok": True,
        "primary_table": primary_table,
        "joins": joins,
        "dimensions": dimensions,
        "measures": measures,
        "filters": filters,
        "unmapped_filters": unmapped,
        "order_by": order_by,
        "limit": limit,
        "having": having_raw,
    }


def _classify_aggregate(body, exp):
    """``(agg_label, col, table)`` if ``body`` is a recognised single-column aggregate, else
    ``(None, "", "")``. Handles COUNT(*), COUNT(DISTINCT col), and the simple stat aggs."""
    if isinstance(body, exp.Count):
        inner = body.this
        if isinstance(inner, exp.Star) or inner is None:
            return "COUNT", "*", ""
        if isinstance(inner, exp.Distinct):
            cols = inner.expressions or ([inner.this] if inner.this else [])
            c = cols[0] if cols else None
            if isinstance(c, exp.Column):
                return "COUNT DISTINCT", c.name, (c.table or "")
            return None, "", ""
        if isinstance(inner, exp.Column):
            return "COUNT", inner.name, (inner.table or "")
        return None, "", ""
    label = _AGG_LABEL.get(type(body).__name__)
    if label:
        inner = body.this
        if isinstance(inner, exp.Column):
            return label, inner.name, (inner.table or "")
    return None, "", ""


def _filter_of(node, exp, dialect: str):
    """Map one WHERE conjunct to a builder FilterItem dict, or None if it isn't a simple
    ``column <op> value`` predicate the builder can represent."""
    # IS NULL / IS NOT NULL
    if isinstance(node, exp.Is) and isinstance(node.this, exp.Column):
        is_null = isinstance(node.expression, exp.Null)
        return {"col": node.this.name, "table": (node.this.table or ""),
                "op": "IS NULL" if is_null else "IS NOT NULL", "val": ""}
    if isinstance(node, exp.Not) and isinstance(node.this, exp.Is) and isinstance(node.this.this, exp.Column):
        c = node.this.this
        return {"col": c.name, "table": (c.table or ""), "op": "IS NOT NULL", "val": ""}
    # column IN (...)
    if isinstance(node, exp.In) and isinstance(node.this, exp.Column):
        vals = ", ".join(v.sql(dialect=dialect) for v in (node.expressions or []))
        return {"col": node.this.name, "table": (node.this.table or ""), "op": "IN", "val": f"({vals})"}
    # column LIKE / ILIKE value
    if isinstance(node, (exp.Like, exp.ILike)) and isinstance(node.this, exp.Column):
        op = "ILIKE" if isinstance(node, exp.ILike) else "LIKE"
        return {"col": node.this.name, "table": (node.this.table or ""),
                "op": op, "val": node.expression.sql(dialect=dialect)}
    # column <cmp> value  (column on either side)
    op = _CMP_OP.get(type(node).__name__)
    if op and isinstance(node, exp.Binary):
        col, val = (node.this, node.expression)
        if isinstance(col, exp.Column) and not isinstance(val, exp.Column):
            return {"col": col.name, "table": (col.table or ""), "op": op, "val": val.sql(dialect=dialect)}
        if isinstance(val, exp.Column) and not isinstance(col, exp.Column):
            # flip the operator so the column stays on the left
            flip = {">": "<", "<": ">", ">=": "<=", "<=": ">="}.get(op, op)
            return {"col": val.name, "table": (val.table or ""), "op": flip, "val": col.sql(dialect=dialect)}
    return None


def _split_and(node, exp) -> list:
    """Flatten a top-level AND (through parens) into conjuncts."""
    if isinstance(node, exp.Paren):
        return _split_and(node.this, exp)
    if isinstance(node, exp.And):
        return _split_and(node.left, exp) + _split_and(node.right, exp)
    return [node]
