"""What a query card means, in plain words, read off its SQL and nothing else.

A card a model drafted carries a label the model chose ("Cash profit"). A label on a wrong definition looks exactly as
confident as one on a right one, so what a person checks before keeping the card is this: the sum, the column and the
conditions, as the statement says them. It is never the model's text, so the words cannot say one thing while the query
does another.

A statement these words cannot hold (a join, a subquery, a window) answers None, and the card says to read its query. A guess
in plain words would be worse than no words.
"""
from __future__ import annotations

import re
from typing import Optional

import sqlglot
from sqlglot import exp

from aughor.dashboards.queries import PARAM, engine_name


class _NoWords(ValueError):
    """Something in the statement these words do not hold."""


def _pretty(name: str) -> str:
    return (name or "").replace("_", " ").strip().capitalize()


def _is_number(node: Optional[exp.Expression], value: float) -> bool:
    return isinstance(node, exp.Literal) and node.is_number and float(node.name) == value


#: What a span of seconds divided by this is.
_SECONDS_IN = {86400: "Days", 3600: "Hours", 60: "Minutes"}
#: What `strftime` leaves of a date, by the format it is given.
_PART_OF_DATE = {"%Y": "Year", "%Y-%m": "Month", "%Y-%m-01": "Month", "%Y-%m-%d": "Day"}
_EXTRACTED = {exp.Year: "Year", exp.Month: "Month", exp.Day: "Day"}


def _seconds_between(node: exp.Expression) -> Optional[tuple[exp.Expression, exp.Expression]]:
    """The two ends of a span written in seconds, ``date_diff('second', a, b)`` or ``epoch(b - a)``, or None when it is not one."""
    if isinstance(node, exp.DateDiff) and node.text("unit").lower() == "second":
        return node.expression, node.this
    if isinstance(node, exp.TimeToUnix) and isinstance(node.this, exp.Sub):
        return node.this.expression, node.this.this
    return None


def _span(start: exp.Expression, end: exp.Expression, unit: str, values: dict[str, str]) -> str:
    return f"{unit} from {_term(start, values)} to {_term(end, values)}"


def _date_part(node: exp.Expression, values: dict[str, str]) -> Optional[str]:
    """A date reduced to its month, its day or its year, in words, or None when ``node`` is not one."""
    if isinstance(node, (exp.DateTrunc, exp.TimestampTrunc)):
        return f"{node.text('unit').capitalize()} of {_term(node.this, values)}"
    if isinstance(node, exp.TimeToStr):
        part = _PART_OF_DATE.get(node.text("format"))
        if part is None:
            raise _NoWords(node.sql())
        return f"{part} of {_term(node.this, values)}"
    if isinstance(node, exp.Extract):
        return f"{node.this.name.capitalize()} of {_term(node.expression, values)}"
    for kind, said in _EXTRACTED.items():
        if isinstance(node, kind):
            return f"{said} of {_term(node.this, values)}"
    return None


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
    if isinstance(node, (exp.Cast, exp.Paren, exp.Round, exp.Coalesce, exp.Nullif)):
        return _term(node.this, values)
    if isinstance(node, exp.Neg):
        return f"−{_term(node.this, values)}"
    part = _date_part(node, values)
    if part is not None:
        return part
    if isinstance(node, exp.DateDiff):
        return _span(node.expression, node.this, f"{node.text('unit').capitalize()}s", values)
    ends = _seconds_between(node)
    if ends is not None:
        return _span(*ends, "Seconds", values)
    if isinstance(node, exp.Div):
        ends = _seconds_between(node.left)
        if ends is not None and isinstance(node.right, exp.Literal) and node.right.is_number and int(float(node.right.name)) in _SECONDS_IN:
            return _span(*ends, _SECONDS_IN[int(float(node.right.name))], values)
        return f"{_term(node.left, values)} ÷ {_term(node.right, values)}"
    if isinstance(node, exp.Mul):
        if _is_number(node.right, 1) or _is_number(node.left, 1):        # how a query asks for a decimal
            return _term(node.left if _is_number(node.right, 1) else node.right, values)
        return f"{_term(node.left, values)} × {_term(node.right, values)}"
    if isinstance(node, exp.Add):
        return f"{_term(node.left, values)} + {_term(node.right, values)}"
    if isinstance(node, exp.Sub):
        return f"{_term(node.left, values)} − {_term(node.right, values)}"
    raise _NoWords(node.sql())


_COMPARED = {exp.GT: "is above", exp.GTE: "is at least", exp.LT: "is below", exp.LTE: "is at most"}
_COMPARED_DATES = {exp.GT: "is after", exp.GTE: "is on or after", exp.LT: "is before", exp.LTE: "is on or before"}
_DATE_TEXT = re.compile(r"^\d{4}-\d{2}(-\d{2})?")
_DATE_NAME = re.compile(r"((^|_)(date|timestamp)($|_))|(_(at|on|time)$)", re.I)


def _is_date(node: exp.Expression) -> bool:
    """Whether a side of a comparison reads as a date, so it is said as before and after. Read off the statement, which is all there is
    here: a cast to a date, a literal written like one, or a column named like one."""
    if isinstance(node, (exp.Cast, exp.Paren)):
        if isinstance(node, exp.Cast) and node.to.is_type(*exp.DataType.TEMPORAL_TYPES):
            return True
        return _is_date(node.this)
    if isinstance(node, exp.Literal):
        return not node.is_number and bool(_DATE_TEXT.match(node.name))
    return isinstance(node, exp.Column) and bool(_DATE_NAME.search(node.name))


def _same_column_or_values(node: exp.Or, values: dict[str, str]) -> Optional[str]:
    """``a = 1 OR a = 2``, said as a person would: "A is 1 or 2"."""
    arms = list(node.flatten(unnest=False))
    if all(isinstance(arm, exp.EQ) and isinstance(arm.left, exp.Column) for arm in arms) and len({arm.left.name for arm in arms}) == 1:
        return f"{_term(arms[0].left, values)} is " + " or ".join(_term(arm.right, values) for arm in arms)
    return None


def _condition(node: exp.Expression, values: dict[str, str]) -> str:
    if isinstance(node, exp.Paren):
        said = _condition(node.this, values)
        return f"({said})" if isinstance(node.this, exp.Or) and " or " in said and _same_column_or_values(node.this, values) is None else said
    if isinstance(node, exp.And):
        return f"{_condition(node.left, values)} and {_condition(node.right, values)}"
    if isinstance(node, exp.Or):
        same = _same_column_or_values(node, values)
        return same if same is not None else f"{_condition(node.left, values)} or {_condition(node.right, values)}"
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
            said = _COMPARED_DATES[kind] if _is_date(node.left) or _is_date(node.right) else said
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
        if len(branches) != 1 or (fallback is not None and not _is_number(fallback, 0)):
            raise _NoWords(inner.sql())
        own = _condition(branches[0].this, values)
        taken = branches[0].args["true"]
        read = "1" if _is_number(taken, 1) else _term(taken, values)
        return read, own if not where or _implied(own, where) else f"{own} and {where}"
    return _term(inner, values), where


def _share(node: exp.Avg, where: str, values: dict[str, str]) -> Optional[str]:
    """``AVG(CASE WHEN c THEN 1 ELSE 0 END)``: the share of rows where c, or None when it is not that. Out of the rows the WHERE leaves,
    which is why it is said apart: "late and delivered" and "late, out of delivered" are different numbers."""
    case = node.this
    if not isinstance(case, exp.Case):
        return None
    branches = case.args.get("ifs") or []
    if len(branches) != 1 or not _is_number(branches[0].args["true"], 1) or not _is_number(case.args.get("default"), 0):
        return None
    return f"Share of rows where {_condition(branches[0].this, values)}" + (f", out of rows where {where}" if where else "")


_AGGREGATES = {exp.Sum: "Sum of", exp.Avg: "Average of", exp.Min: "Least", exp.Max: "Most"}


def _words(node: exp.Expression, where: str, values: dict[str, str]) -> str:
    suffix = f" where {where}" if where else ""
    if isinstance(node, exp.Alias):
        return _words(node.this, where, values)
    if isinstance(node, exp.Paren):
        return f"({_words(node.this, where, values)})"
    if isinstance(node, exp.Filter):
        own = _condition(node.expression.this, values)
        return _words(node.this, own if not where or _implied(own, where) else f"{own} and {where}", values)
    if isinstance(node, exp.Round):
        return _words(node.this, where, values)
    if isinstance(node, exp.Avg):
        share = _share(node, where, values)
        if share is not None:
            return share
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
    if isinstance(node, (exp.DateDiff, exp.Literal, exp.Column, exp.Placeholder, exp.Neg)) or _date_part(node, values) is not None:
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
