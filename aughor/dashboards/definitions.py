"""What a query card means, in plain words, read off its SQL and nothing else.

A card a model drafted carries a label the model chose ("Cash profit"). A label on a wrong definition looks exactly as
confident as one on a right one, so what a person checks before keeping the card is this: the sum, the column and the
conditions, as the statement says them. It is never the model's text, so the words cannot say one thing while the query
does another.

A statement these words cannot hold (a join, a subquery, a window) answers None, and the card says to read its query. A guess
in plain words would be worse than no words.
"""
from __future__ import annotations

from typing import Optional

import sqlglot
from sqlglot import exp

from aughor.dashboards.queries import PARAM, engine_name


class _NoWords(ValueError):
    """Something in the statement these words do not hold."""


def _pretty(name: str) -> str:
    return (name or "").replace("_", " ").strip().capitalize()


def _term(node: exp.Expression, values: dict[str, str]) -> str:
    """One side of a condition, or a value inside a calculation."""
    if isinstance(node, exp.Column):
        return _pretty(node.name)
    if isinstance(node, exp.Literal):
        return node.name
    if isinstance(node, exp.Boolean):
        return "yes" if node.this else "no"
    if isinstance(node, exp.Placeholder):
        return values.get(node.name, f"your {_pretty(node.name).lower()}")
    if isinstance(node, exp.Cast):
        return _term(node.this, values)
    if isinstance(node, exp.Neg):
        return f"−{_term(node.this, values)}"
    raise _NoWords(node.sql())


_COMPARED = {exp.GT: "is above", exp.GTE: "is at least", exp.LT: "is below", exp.LTE: "is at most"}


def _condition(node: exp.Expression, values: dict[str, str]) -> str:
    if isinstance(node, exp.Paren):
        return _condition(node.this, values)
    if isinstance(node, exp.And):
        return f"{_condition(node.left, values)} and {_condition(node.right, values)}"
    if isinstance(node, exp.Or):
        return f"{_condition(node.left, values)} or {_condition(node.right, values)}"
    if isinstance(node, exp.EQ):
        return f"{_term(node.left, values)} is {_term(node.right, values)}"
    if isinstance(node, exp.NEQ):
        return f"{_term(node.left, values)} is not {_term(node.right, values)}"
    if isinstance(node, exp.Not):
        inner = node.this
        if isinstance(inner, exp.EQ):
            return f"{_term(inner.left, values)} is not {_term(inner.right, values)}"
        if isinstance(inner, exp.In):
            return f"{_term(inner.this, values)} is none of " + ", ".join(_term(e, values) for e in inner.expressions)
        if isinstance(inner, exp.Is) and isinstance(inner.expression, exp.Null):
            return f"{_term(inner.this, values)} is filled in"
        raise _NoWords(node.sql())
    if isinstance(node, exp.In) and not node.args.get("query"):
        return f"{_term(node.this, values)} is " + " or ".join(_term(e, values) for e in node.expressions)
    if isinstance(node, exp.Is) and isinstance(node.expression, exp.Null):
        return f"{_term(node.this, values)} is empty"
    if isinstance(node, exp.Between):
        return f"{_term(node.this, values)} is from {_term(node.args['low'], values)} to {_term(node.args['high'], values)}"
    for kind, said in _COMPARED.items():
        if isinstance(node, kind):
            return f"{_term(node.left, values)} {said} {_term(node.right, values)}"
    raise _NoWords(node.sql())


def _implied(own: str, where: str) -> bool:
    """Whether a statement's WHERE says nothing its CASE does not: "Status is Complete" already rules out "Status is not
    Cancelled", and saying both makes a reader work out that one follows from the other."""
    column, sep, excluded = where.partition(" is not ")
    if not sep or " and " in where or " or " in where:
        return False
    if own.startswith(f"{column} is none of "):
        return excluded in own[len(f"{column} is none of "):].split(", ")
    if own.startswith(f"{column} is ") and not own.startswith(f"{column} is not "):
        return excluded not in own[len(f"{column} is "):].split(" or ")
    return False


def _measured(inner: exp.Expression, where: str, values: dict[str, str]) -> tuple[str, str]:
    """What an aggregate reads, and the conditions it reads it under: its own CASE, or the statement's WHERE. ``ELSE 0`` adds
    nothing to a sum, so it says nothing either."""
    if isinstance(inner, exp.Case):
        branches = inner.args.get("ifs") or []
        fallback = inner.args.get("default")
        if len(branches) != 1 or (fallback is not None and not (isinstance(fallback, exp.Literal) and fallback.name == "0")):
            raise _NoWords(inner.sql())
        own = _condition(branches[0].this, values)
        return _term(branches[0].args["true"], values), own if not where or _implied(own, where) else f"{own} and {where}"
    return _term(inner, values), where


_AGGREGATES = {exp.Sum: "Sum of", exp.Avg: "Average of", exp.Min: "Least", exp.Max: "Most"}


def _words(node: exp.Expression, where: str, values: dict[str, str]) -> str:
    suffix = f" where {where}" if where else ""
    if isinstance(node, exp.Alias):
        return _words(node.this, where, values)
    if isinstance(node, exp.Paren):
        return f"({_words(node.this, where, values)})"
    if isinstance(node, exp.Count):
        inner = node.this
        if isinstance(inner, exp.Distinct):
            return f"Count of different {_term(inner.expressions[0], values)}{suffix}"
        if inner is None or isinstance(inner, exp.Star):
            return f"Count of rows{suffix}"
        read, under = _measured(inner, where, values)
        literal_one = read == "1"
        return f"Count of {'rows' if literal_one else read}" + (f" where {under}" if under else "")
    for kind, said in _AGGREGATES.items():
        if isinstance(node, kind):
            read, under = _measured(node.this, where, values)
            if kind is exp.Sum and read == "1":         # a sum of ones is a count
                return "Count of rows" + (f" where {under}" if under else "")
            return f"{said} {read}" + (f" where {under}" if under else "")
    if isinstance(node, exp.Coalesce):
        return _words(node.this, where, values)     # "or nothing": a sum over no rows, as zero
    if isinstance(node, exp.Nullif):
        return _words(node.this, where, values)     # a guard against dividing by zero
    if isinstance(node, exp.Div):
        return f"{_words(node.left, where, values)} ÷ {_words(node.right, where, values)}"
    if isinstance(node, exp.Add):
        return f"{_words(node.left, where, values)} + {_words(node.right, where, values)}"
    if isinstance(node, exp.Sub):
        return f"{_words(node.left, where, values)} − {_words(node.right, where, values)}"
    if isinstance(node, exp.Mul):
        # `* 1.0` is how a query asks for a decimal, not a calculation anyone needs to read
        for side, other in ((node.right, node.left), (node.left, node.right)):
            if isinstance(side, exp.Literal) and side.is_number and float(side.name) == 1:
                return _words(other, where, values)
        return f"{_words(node.left, where, values)} × {_words(node.right, where, values)}"
    if isinstance(node, exp.Cast):
        return _words(node.this, where, values)
    if isinstance(node, (exp.DateTrunc, exp.TimestampTrunc)):
        return f"{node.text('unit').capitalize()} of {_pretty(node.this.name)}"
    if isinstance(node, (exp.Literal, exp.Column, exp.Placeholder, exp.Neg)):
        return _term(node, values)
    raise _NoWords(node.sql())


def _having(node: exp.Expression, values: dict[str, str]) -> str:
    """A condition on what was summed: "Only where Count of rows is at least 30"."""
    for kind, said in _COMPARED.items():
        if isinstance(node, kind):
            return f"{_words(node.left, '', values)} {said} {_term(node.right, values)}"
    raise _NoWords(node.sql())


def definition_of(sql: str, *, dialect: str = "duckdb", values: Optional[dict[str, str]] = None,
                  only: Optional[str] = None) -> Optional[str]:
    """The statement in plain words, or None when these words cannot hold it. ``values`` names the dashboard's values it
    reads (``{{name}}`` → "your return rate"), by their name as the statement writes them. ``only`` is the one column a figure
    shows, so its definition is of that and not of a second value said beside it."""
    named = {engine_name(k): v for k, v in (values or {}).items()}
    try:
        tree = sqlglot.parse_one(PARAM.sub(lambda m: f":{engine_name(m.group(1))}", sql or ""), read=dialect)
        if not isinstance(tree, exp.Select) or tree.args.get("joins") or tree.find(exp.Subquery) or tree.find(exp.Window) \
                or tree.find(exp.CTE):
            return None
        where = _condition(tree.args["where"].this, named) if tree.args.get("where") else ""
        selects = tree.selects
        if only:
            selects = [s for s in selects if s.alias_or_name == only] or selects
        if any(isinstance(s, exp.Star) for s in selects):
            return (f"The rows where {where}." if where else "The rows, as they stand.")
        group = tree.args.get("group")
        if not group:
            measures = [s for s in selects if s.find(exp.AggFunc) or isinstance(s.unalias(), (exp.Div, exp.Add, exp.Sub, exp.Mul))]
            if len(measures) != len(selects):
                listed = ", ".join(_pretty(s.alias_or_name) for s in selects)
                return f"{listed}, for each row where {where}." if where else f"{listed}, for each row."
            if len(selects) == 1:
                return _words(selects[0], where, named)
            return ". ".join(f"{_pretty(s.alias_or_name)}: {_words(s, where, named)}" for s in selects) + "."
        keys = [s for s in selects if not s.find(exp.AggFunc)]
        told = ". ".join(f"{_pretty(m.alias_or_name)}: {_words(m, where, named)}" for m in selects if m.find(exp.AggFunc))
        by = ", ".join(_words(k.unalias(), "", named) for k in keys) or "each row"
        limit = tree.args.get("limit")
        top = f" The top {limit.expression.name}." if limit is not None and limit.expression is not None else ""
        having = tree.args.get("having")
        kept = f" Only where {_having(having.this, named)}." if having is not None else ""
        return f"{told}. By {by}.{kept}{top}"
    except (_NoWords, sqlglot.errors.SqlglotError, AttributeError, IndexError, KeyError):
        return None
