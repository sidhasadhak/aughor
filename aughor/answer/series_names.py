"""Names a reader can read, for columns a model named for itself (2026-11-06).

The Daily Briefing posted a chart whose legend read ``r28`` and ``r29``: the analyst's SQL had
aliased revenue on Oct 28 and Oct 29 that way, and every renderer prints a column's name as it
is. The name is the model's shorthand; what the column IS sits in its own expression —
``SUM(IF(DATE(created_at) = '2026-10-29', sale_price, 0))``. This reads it back:

* a cryptic alias (``r29``, ``d``, ``rev``) is named from its expression; a name already made of
  words is left to the renderers' own humaniser;
* measures that share one aggregate and differ only by a condition (two days, two regions) are
  named by what differs — ``Oct 28`` · ``Oct 29`` — and the axis by what they share;
* the shared measure takes a governed metric's label only when the query computes that metric:
  its aggregate over the same column AND every one of its filters in the query's WHERE.
  ``SUM(sale_price)`` without the revenue metric's status filter is "Sale price", not "Revenue".

The result is display only: ``{"labels": {column: name}, "y_title": axis}``. The columns keep
their names, because a renderer classifies a grid by them — a column renamed ``Oct 28`` was read
as a date and the chart lost a series (measured on the 09:00 grid). Every surface reads the same
names: the finding carries them (the Data Canvas), the answer's results carry them (Slack, the
export), and a result from before this module is named on demand from its SQL.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Iterable, Optional

#: A name the model wrote for itself: one to three letters, or letters run into digits.
_CRYPTIC = re.compile(r"^(?:[a-z]{1,3}|[a-z]{1,4}_?\d+)$", re.IGNORECASE)
_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def cryptic(name: str) -> bool:
    """Whether a column's name says nothing to a reader on its own."""
    return bool(_CRYPTIC.match(str(name or "").strip()))


def _words(identifier: str) -> str:
    text = re.sub(r"[_\s]+", " ", str(identifier or "")).strip()
    return text[:1].upper() + text[1:] if text else ""


def _day(value: str, *, with_year: bool) -> Optional[str]:
    m = _DATE.match(value or "")
    if not m:
        return None
    try:
        d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None
    return f"{_MONTHS[d.month - 1]} {d.day}" + (f", {d.year}" if with_year else "")


def _norm(sql: str) -> str:
    """A condition with its table qualifiers, spacing and case taken out, for comparing."""
    s = re.sub(r"\b[A-Za-z_][A-Za-z0-9_]*\.(?=[A-Za-z_])", "", str(sql or ""))
    return re.sub(r"\s+", "", s).lower()


def _unwrap(node: Any) -> Any:
    from sqlglot import exp
    while True:
        if isinstance(node, (exp.Alias, exp.Paren, exp.Cast, exp.TryCast)):
            node = node.this
        elif isinstance(node, (exp.Round, exp.Coalesce)) and node.this is not None:
            node = node.this
        else:
            return node


def _measure(node: Any) -> Optional[tuple[str, str, list[str]]]:
    """``(aggregate, the column it aggregates, the string literals its condition tests)`` for an
    aggregate over one column, optionally inside one IF / CASE WHEN — else None."""
    from sqlglot import exp
    aggs = {exp.Sum: "sum", exp.Avg: "avg", exp.Count: "count", exp.Min: "min", exp.Max: "max"}
    node = _unwrap(node)
    kind = next((name for cls, name in aggs.items() if isinstance(node, cls)), None)
    if kind is None:
        return None
    inner = _unwrap(node.this)
    if isinstance(inner, exp.Distinct):
        inner = _unwrap(inner.expressions[0]) if inner.expressions else None
    cond = None
    if isinstance(inner, exp.If):
        cond, inner = inner.this, _unwrap(inner.args.get("true"))
    elif isinstance(inner, exp.Case) and len(inner.args.get("ifs") or []) == 1:
        when = inner.args["ifs"][0]
        cond, inner = when.this, _unwrap(when.args.get("true"))
    if not isinstance(inner, exp.Column):
        return None
    literals = [str(lit.this) for lit in (cond.find_all(exp.Literal) if cond is not None else [])
                if lit.is_string]
    return kind, inner.name, literals


def _metric_label(kind: str, column: str, where: list[str], metrics: Iterable[Any]) -> Optional[str]:
    """The governed metric this aggregate IS — its aggregate over the same column and every one of
    its filters among the query's own conditions — when exactly one is; else None."""
    found: list[str] = []
    for m in metrics or ():
        if str(getattr(m, "status", "approved") or "approved") not in ("approved", ""):
            continue
        tree = _parse(str(getattr(m, "sql", "") or ""), what="a governed metric's definition")
        selects = getattr(tree, "selects", None) or []
        shape = _measure(selects[0]) if len(selects) == 1 else None
        if not shape or shape[0] != kind or shape[1].lower() != column.lower() or shape[2]:
            continue
        if all(_norm(f) in where for f in (getattr(m, "filters", None) or [])):
            found.append(str(getattr(m, "label", "") or getattr(m, "name", "")))
    return found[0] if len(set(found)) == 1 and found[0] else None


def _measure_name(kind: str, column: str, where: list[str], metrics: Iterable[Any]) -> str:
    governed = _metric_label(kind, column, where, metrics)
    if governed:
        return governed
    base = _words(column)
    return {"sum": base, "avg": f"Average {base.lower()}", "count": f"{base} count",
            "min": f"Lowest {base.lower()}", "max": f"Highest {base.lower()}"}.get(kind, base)


def _parse(sql: str, *, what: str):
    """One statement's tree — read as BigQuery first (the analyst writes `IF(…)`), then generic — or
    None, counted, when neither reads it: its columns keep their own names."""
    import sqlglot
    failed: Optional[Exception] = None
    for dialect in ("bigquery", None):
        try:
            return sqlglot.parse_one(sql, read=dialect)
        except Exception as exc:                # noqa: BLE001 — the next dialect, or the count below
            failed = exc
    if failed is not None and sql.strip():
        from aughor.kernel.errors import tolerate
        tolerate(failed, f"series names: {what} could not be read — its columns keep their own names",
                 counter="series_names.unparsed")
    return None


def _statement_for(columns: list[str], sqls: Iterable[str]):
    """The statement among ``sqls`` whose select list names every one of ``columns``."""
    want = {c.lower() for c in columns}
    for sql in sqls or ():
        tree = _parse(str(sql), what="a result's statement")
        selects = getattr(tree, "selects", None) or []
        if want <= {str(s.alias_or_name).lower() for s in selects}:
            return tree
    return None


def names_for(columns: list[str], sqls: Iterable[str], *, metrics: Iterable[Any] = ()) -> dict:
    """``{"labels": {column: name}, "y_title": axis}`` for the cryptic columns of one result, read
    from the statement that produced it; ``{}`` when nothing needs naming or nothing can be read."""
    columns = [str(c) for c in columns or []]
    if not any(cryptic(c) for c in columns):
        return {}
    tree = _statement_for(columns, sqls)
    if tree is None:
        return {}
    from sqlglot import exp
    by_alias = {str(s.alias_or_name).lower(): s for s in tree.selects}
    where_node = tree.args.get("where")
    where = []
    if where_node is not None:
        parts = list(where_node.this.flatten()) if isinstance(where_node.this, exp.And) else [where_node.this]
        where = [_norm(p.sql()) for p in parts]

    labels: dict[str, str] = {}
    shapes: dict[str, tuple[str, str, list[str]]] = {}
    for col in columns:
        if not cryptic(col):
            continue
        node = by_alias.get(col.lower())
        shape = _measure(node) if node is not None else None
        if shape:
            shapes[col] = shape
            continue
        inner = _unwrap(node) if node is not None else None
        if isinstance(inner, (exp.Date, exp.DateTrunc, exp.TimestampTrunc, exp.DatetimeTrunc)):
            labels[col] = "Date"
        elif isinstance(inner, exp.Column):
            labels[col] = _words(inner.name)

    y_title = ""
    if shapes:
        # Measures that share one aggregate over one column and differ by their condition are
        # named by what differs; what they share is the axis.
        shared = {(k, c.lower()) for k, c, _ in shapes.values()}
        literals = [lits for _, _, lits in shapes.values()]
        if len(shapes) >= 2 and len(shared) == 1 and all(len(x) == 1 for x in literals) \
                and len({x[0] for x in literals}) == len(literals):
            kind, column = next(iter(shapes.values()))[:2]
            years = {x[0][:4] for x in literals if _DATE.match(x[0])}
            for col, (_, _, lits) in shapes.items():
                labels[col] = _day(lits[0], with_year=len(years) > 1) or lits[0]
            y_title = _measure_name(kind, column, where, metrics)
        else:
            for col, (kind, column, lits) in shapes.items():
                name = _measure_name(kind, column, where, metrics)
                cond = ", ".join(_day(x, with_year=False) or x for x in lits)
                labels[col] = f"{name} · {cond}" if cond else name
            if len(shapes) == 1:
                y_title = labels[next(iter(shapes))]
    out: dict = {}
    if labels:
        out["labels"] = labels
    if y_title:
        out["y_title"] = y_title
    return out


def connection_metrics(connection_id: str) -> list:
    """The governed metrics a connection's names may borrow, through the platform's seam
    (`kernel/registries/governed_metrics.py`; the semantic layer registers its reader at bootstrap)."""
    from aughor.kernel.registries.governed_metrics import metrics_for
    return metrics_for(connection_id)
