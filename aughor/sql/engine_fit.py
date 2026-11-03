"""What sqlglot's generators leave unrunnable or wrong on SQL Server, Oracle and MySQL's family, fixed on the tree before it renders.

Platform SQL is written in DuckDB's dialect (`db/dialects.py`), and these are the forms it uses that those engines refuse once
translated, each measured on a real server (`tests/integration/test_connectors_on_real_servers.py`). A form not here goes to the
engine as sqlglot renders it, and the engine's refusal says what it could not run.

Three would otherwise answer wrongly rather than fail. On TiDB sqlglot's month bucket counts from the year 0000, which is NULL there,
so every row lands in one bucket. Oracle's `TRUNC(x, 'DAY')` is the start of the WEEK. And sqlglot moves a statement's cap inside the
subquery it makes for QUALIFY, so the cap would run before the filter.
"""
from __future__ import annotations

import sqlglot
from sqlglot import exp, transforms

#: Oracle's TRUNC format per grain. `DAY` means the week's first day there, and `WEEK` is not a format at all.
_ORACLE_TRUNC = {"YEAR": "YYYY", "QUARTER": "Q", "MONTH": "MM", "WEEK": "IW", "DAY": "DD", "HOUR": "HH", "MINUTE": "MI"}
_TSQL_GRAINS = ("YEAR", "QUARTER", "MONTH", "DAY", "HOUR", "MINUTE")
_MYSQL_FORMATS = {"YEAR": "%Y-01-01", "MONTH": "%Y-%m-01", "HOUR": "%Y-%m-%d %H:00:00", "MINUTE": "%Y-%m-%d %H:%i:00"}


def _fn(name: str, *args: exp.Expression) -> exp.Anonymous:
    """A call rendered as written: sqlglot's own DATEDIFF would re-spell its arguments."""
    return exp.Anonymous(this=name, expressions=list(args))


def _tsql_trunc(value: exp.Expression, grain: str) -> exp.Expression:
    """DATEADD over DATEDIFF from day zero, a Monday in 1900: every version has it (DATETRUNC is 2022's), and a week starts on
    Monday as DuckDB's does, whatever the server's DATEFIRST says."""
    zero = exp.Literal.number(0)
    if grain == "WEEK":
        days = exp.Div(this=_fn("DATEDIFF", exp.var("DAY"), zero, value), expression=exp.Literal.number(7), typed=True)  # whole weeks
        return _fn("DATEADD", exp.var("DAY"), exp.Mul(this=days, expression=exp.Literal.number(7)), zero)
    return _fn("DATEADD", exp.var(grain), _fn("DATEDIFF", exp.var(grain), zero, value), zero)


def _mysql_trunc(value: exp.Expression, grain: str) -> exp.Expression | None:
    """From the value's own parts: nothing here leans on a date the server's mode may refuse."""
    if grain == "DAY":
        return _fn("DATE", value)
    if grain == "WEEK":
        return _fn("DATE_SUB", _fn("DATE", value), exp.Interval(this=_fn("WEEKDAY", value), unit=exp.var("DAY")))
    if grain == "QUARTER":
        months = exp.Sub(this=exp.Mul(this=_fn("QUARTER", value), expression=exp.Literal.number(3)), expression=exp.Literal.number(2))
        return exp.cast(_fn("CONCAT", _fn("YEAR", value), exp.Literal.string("-"), months, exp.Literal.string("-01")), "DATE")
    if grain in _MYSQL_FORMATS:
        return exp.cast(_fn("DATE_FORMAT", value, exp.Literal.string(_MYSQL_FORMATS[grain])), "DATETIME" if ":" in _MYSQL_FORMATS[grain] else "DATE")
    return None


def _date_trunc(node: exp.Expression, dialect: str) -> exp.Expression:
    if not isinstance(node, (exp.TimestampTrunc, exp.DateTrunc)):
        return node
    grain = node.text("unit").upper()
    if dialect == "oracle" and grain in _ORACLE_TRUNC:
        return _fn("TRUNC", node.this, exp.Literal.string(_ORACLE_TRUNC[grain]))
    if dialect == "tsql" and (grain in _TSQL_GRAINS or grain == "WEEK"):
        return _tsql_trunc(node.this, grain)
    if dialect == "mysql":
        return _mysql_trunc(node.this, grain) or node
    return node


def _filter(node: exp.Expression) -> exp.Expression:
    """`SUM(x) FILTER (WHERE c)` as `SUM(CASE WHEN c THEN x END)`. None of these engines has FILTER."""
    if not isinstance(node, exp.Filter) or not isinstance(node.this, exp.AggFunc):
        return node
    agg, condition = node.this, node.expression.this

    def when(value: exp.Expression) -> exp.Case:
        return exp.Case(ifs=[exp.If(this=condition.copy(), true=value)])

    inner = agg.this
    if isinstance(inner, exp.Distinct):
        inner.set("expressions", [when(inner.expressions[0])])
    else:
        agg.set("this", when(exp.Literal.number(1) if inner is None or isinstance(inner, exp.Star) else inner))
    return agg


def _ilike(node: exp.Expression) -> exp.Expression:
    if not isinstance(node, exp.ILike):
        return node
    return exp.Like(this=exp.Lower(this=node.this), expression=exp.Lower(this=node.expression))


def _group_by_written_out(tree: exp.Expression) -> None:
    """`GROUP BY 1` and `GROUP BY alias`, as the expression they name: neither engine groups by either."""
    for select in tree.find_all(exp.Select):
        group = select.args.get("group")
        if not group:
            continue
        aliases = {s.alias: s.this for s in select.selects if isinstance(s, exp.Alias)}
        written = []
        for item in group.expressions:
            if isinstance(item, exp.Literal) and item.is_int and 0 < int(item.this) <= len(select.selects):
                written.append(select.selects[int(item.this) - 1].unalias().copy())
            elif isinstance(item, exp.Column) and not item.table and item.name in aliases:
                written.append(aliases[item.name].copy())
            else:
                written.append(item)
        group.set("expressions", written)


def _qualify_as_subquery(select: exp.Select) -> exp.Expression:
    """sqlglot's own rewrite, with the statement's order and cap moved back out where they mean what was written."""
    order, limit = select.args.pop("order", None), select.args.pop("limit", None)
    outer = transforms.eliminate_qualify(select)
    if order is not None:
        outer.set("order", order)
    if limit is not None:
        outer.set("limit", limit)
    return outer


def _quote_leading_underscores(tree: exp.Expression) -> None:
    """Oracle refuses an unquoted name that starts with one, and the platform's probes (and sqlglot's `_t`) use them."""
    for identifier in tree.find_all(exp.Identifier):
        if identifier.name.startswith("_"):
            identifier.set("quoted", True)


def _varchar_with_length(node: exp.Expression) -> exp.Expression:
    """Oracle's VARCHAR2 must say how long."""
    if isinstance(node, exp.DataType) and node.this in (exp.DataType.Type.VARCHAR, exp.DataType.Type.TEXT) and not node.expressions:
        return exp.DataType.build("VARCHAR2(4000)", dialect="oracle")
    return node


#: Who needs which step. ClickHouse has QUALIFY and Postgres has FILTER; ClickHouse's FILTER refuses COUNT(*).
_QUALIFY_REWRITTEN = frozenset({"tsql", "oracle", "mysql", "postgres"})
_FILTER_REWRITTEN = frozenset({"tsql", "oracle", "mysql", "clickhouse"})
#: The dialects `translate_for` is for. Every other engine takes sqlglot's rendering as it is.
FITTED_DIALECTS = _QUALIFY_REWRITTEN | _FILTER_REWRITTEN


def translate_for(sql: str, dialect: str) -> str:
    """``sql``, written in DuckDB's dialect, as one of `FITTED_DIALECTS` can run it."""
    tree = sqlglot.parse_one(sql, read="duckdb")
    if dialect in _QUALIFY_REWRITTEN:
        tree = tree.transform(lambda node: _qualify_as_subquery(node) if isinstance(node, exp.Select) and node.args.get("qualify") else node)
    tree = tree.transform(lambda node: _date_trunc(node, dialect))
    if dialect in _FILTER_REWRITTEN:
        tree = tree.transform(_filter)
    if dialect == "tsql":
        tree = tree.transform(_ilike)
    if dialect in ("tsql", "oracle"):
        _group_by_written_out(tree)
    if dialect == "oracle":
        _quote_leading_underscores(tree)
        tree = tree.transform(_varchar_with_length)
    return tree.sql(dialect=dialect)
