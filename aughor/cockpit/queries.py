"""Arc AP-7 — your own query on the cockpit (ROADMAP §3.57; docs/COCKPIT_APP_BUILDER_STUDY_2026-10-10.md §9).

A card has always run its own SQL behind the read-only door (`aughor/dashboard`). What a person could not do was write
that SQL in the builder and choose how it is shown: a card's shape came from its result, so a date series was drawn as a
line whatever was picked, and a chart had no buckets for its dates and no split shown stacked, side by side or as shares.

A card that reads a person's own SQL now says how it is shown (``render.shown``): a table, a figure, a bar, a line, an
area or a scatter; what runs along the bottom and in what buckets; what is summed; what splits it, the top few and the
rest as Other. When the SQL returns rows the platform sums them around the statement — the statement is embedded word for
word, never rewritten — and when it already sums it is drawn as it returns. Every run is stopped after a set time. A query
over a table whose entity has a row policy is refused while the policies hold: it reads the table straight, so it cannot
be narrowed to each reader (the user's call, 2026-10-11).
"""
from __future__ import annotations

import contextlib
import re
import threading
import time
from typing import Any, Iterator, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError

FLAG = "cockpit.queries"

SHOWN = ("table", "figure", "bar", "line", "area", "scatter")
CHARTS = ("bar", "line", "area", "scatter")
AGGS = ("count", "count_distinct", "sum", "avg", "min", "max")
BUCKETS = ("day", "week", "month", "quarter", "year")
SEGMENTS = ("stacked", "side_by_side", "shares")
#: The most series one chart sums, and the most values a split draws before the rest are Other.
MAX_SERIES = 4
MAX_TOP = 12
#: The most groups — buckets × split values — a summed chart reads; past it, the chart says it was cut.
MAX_GROUPS = 2000
#: The most points a scatter, or a chart drawn as its statement returns, reads.
MAX_POINTS = 2000
#: The rows a table shows, and the rows a preview in the builder carries.
TABLE_ROWS = 200
PREVIEW_ROWS = 20
#: A run is stopped after this many seconds, unless the connection's budget sets its own limit.
RUN_LIMIT_S = 60.0
#: The words each calculation is said in.
AGG_WORDS = {"count": "Count", "count_distinct": "Count of different", "sum": "Sum", "avg": "Average",
             "min": "Least", "max": "Most"}
_SOURCE = "cockpit_query"
_INNER = "aughor_q_inner"
#: Arc AP-8 — a variable in a query of the person's own: ``{{name}}``, one of the cockpit's values by its name.
PARAM = re.compile(r"\{\{\s*([a-z][a-z0-9_-]{0,39})\s*\}\}")


class Refused(ValueError):
    """A query card that cannot be kept or run as asked; ``str(exc)`` is the sentence to show."""


class Series(BaseModel):
    """One thing a chart sums — or, drawn as the statement returns, one column it draws."""
    model_config = ConfigDict(extra="forbid")
    column: str = ""
    agg: str = "sum"


class Shown(BaseModel):
    """How a query card is shown (``render.shown``)."""
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    as_: str = Field(default="table", alias="as")
    #: True — the platform sums the statement's rows; False — it is drawn as it returns.
    summed: bool = True
    #: What runs along the bottom, and the buckets a date or a time is put in.
    x: str = ""
    bucket: str = ""
    #: What is summed (or drawn).
    series: list[Series] = Field(default_factory=list)
    #: What splits it: the top few values by size, the rest as Other.
    split: str = ""
    top: int = 5
    segments: str = "stacked"
    running: bool = False
    labels: bool = False
    #: A table's columns, in order — none, every column — and its sort.
    columns: list[str] = Field(default_factory=list)
    sort: str = ""
    descending: bool = True
    #: A figure's label.
    label: str = ""

    def said(self) -> dict:
        return self.model_dump(by_alias=True)


# ── columns, as their types read ──────────────────────────────────────────────────────────────────────────────────────

_NUMBER = re.compile(r"INT|DOUBLE|FLOAT|DECIMAL|NUMERIC|REAL|NUMBER|HUGEINT|BIGNUMERIC", re.I)


def kind_of(type_name: str) -> str:
    """A column's kind as a chart reads it: ``number``, ``date``, ``time`` (a moment) or ``text``."""
    t = (type_name or "").upper()
    if t.startswith("DATE") and "TIME" not in t:
        return "date"
    if "TIMESTAMP" in t or "DATETIME" in t:
        return "time"
    if _NUMBER.search(t):
        return "number"
    return "text"


def _kinds(columns: list[dict]) -> dict[str, str]:
    return {str(c.get("name")): kind_of(str(c.get("type") or "")) for c in columns if isinstance(c, dict)}


def shown_of(render: Any) -> Optional[Shown]:
    """The way a card is shown, when it says one — None for a card that says none (every card before AP-7)."""
    raw = render.get("shown") if isinstance(render, dict) else None
    if not isinstance(raw, dict):
        return None
    try:
        return Shown.model_validate(raw)
    except ValidationError as e:
        raise Refused(f"How this card is shown cannot be read: {e.errors()[0].get('msg', 'it is not a setup')}.")


def normalized(shown: Shown, columns: list[dict]) -> Shown:
    """The setup as it runs: a date or a time summed along the bottom is put in days unless it names its buckets, a
    scatter is drawn as it returns, and a split is never the thing along the bottom."""
    kinds = _kinds(columns)
    update: dict[str, Any] = {}
    if shown.as_ == "scatter":
        update["summed"] = False
    if shown.as_ in CHARTS and shown.as_ != "scatter" and shown.summed and kinds.get(shown.x) in ("date", "time") \
            and not shown.bucket:
        update["bucket"] = "day"
    return shown.model_copy(update=update) if update else shown


def check(shown: Shown, columns: list[dict]) -> list[str]:
    """Each thing the setup asks that the statement's columns cannot give, as a sentence — none when it reads."""
    kinds = _kinds(columns)
    names = ", ".join(kinds) or "none"
    out: list[str] = []

    def column(name: str, what: str) -> bool:
        if name not in kinds:
            out.append(f"{what} names “{name}”, which this query does not return (it returns {names}).")
            return False
        return True

    if shown.as_ not in SHOWN:
        return [f"A card is shown as a table, a figure, a bar, a line, an area or a scatter — not “{shown.as_}”."]
    if shown.as_ == "table":
        for c in shown.columns:
            column(c, "The table")
        if shown.sort:
            column(shown.sort, "The sort")
        return out
    single = shown.as_ in ("figure", "scatter")
    if not shown.series or (single and len(shown.series) != 1):
        out.append("A figure shows one value and a scatter one height." if single else "A chart sums at least one thing.")
        return out
    if len(shown.series) > MAX_SERIES:
        out.append(f"A chart sums at most {MAX_SERIES} things.")
    for s in shown.series:
        if s.agg not in AGGS:
            out.append(f"“{s.agg}” is not a calculation: count, count of different, sum, average, least or most.")
            continue
        if not shown.summed or shown.as_ == "scatter":
            if column(s.column, "The height") and kinds[s.column] != "number":
                out.append(f"“{s.column}” is {kinds[s.column]}, and a height is a number.")
            continue
        if s.agg == "count" and not s.column:
            continue
        if column(s.column, AGG_WORDS[s.agg]) and s.agg in ("sum", "avg") and kinds[s.column] != "number":
            out.append(f"{AGG_WORDS[s.agg]} reads a number, and “{s.column}” is {kinds[s.column]}.")
    if shown.as_ == "figure":
        return out
    if not shown.x:
        out.append("A chart says what runs along the bottom.")
    elif column(shown.x, "Along the bottom"):
        if shown.bucket and shown.bucket not in BUCKETS:
            out.append(f"“{shown.bucket}” is not a bucket: day, week, month, quarter or year.")
        elif shown.bucket and kinds[shown.x] not in ("date", "time"):
            out.append(f"Only a date or a time is put in buckets, and “{shown.x}” is {kinds[shown.x]}.")
        if shown.as_ == "scatter" and kinds[shown.x] == "text":
            out.append(f"A scatter places each point by two numbers or a moment, and “{shown.x}” is words.")
    if shown.split:
        if column(shown.split, "Split by") and shown.split == shown.x:
            out.append("A chart is not split by what runs along the bottom.")
        if len(shown.series) > 1:
            out.append("A chart of more than one series is split by its series: take off the split or a series.")
    if not 1 <= shown.top <= MAX_TOP:
        out.append(f"A split draws between 1 and {MAX_TOP} values before the rest are Other.")
    if shown.segments not in SEGMENTS:
        out.append("Segments are stacked, side by side or shares.")
    elif shown.segments == "shares" and shown.as_ not in ("bar", "area"):
        out.append("Shares are drawn as bars or an area.")
    if shown.running and shown.as_ == "scatter":
        out.append("A scatter has no running total.")
    return out


# ── variables: a value of the cockpit's, bound — never pasted in ──────────────────────────────────────────────────────

def params_of(sql: str) -> list[str]:
    """The cockpit's values a query reads, by name, each once, in the order it names them."""
    out: list[str] = []
    for m in PARAM.finditer(sql or ""):
        if m.group(1) not in out:
            out.append(m.group(1))
    return out


def engine_name(name: str) -> str:
    """A value's name as a placeholder may spell it: ``window`` → ``v_window``, ``chosen-order`` → ``v_chosen_order``."""
    return "v_" + name.replace("-", "_")


#: What a value's kind is (`web/lib/cockpit/catalog.ts` VALUE_KINDS), and the longest word a value holds there.
VALUE_KINDS = ("days", "number", "text", "date")
MAX_WORD = 120
#: A string, a quoted name or a comment — where ``{{name}}`` would be read as those words, never bound.
_QUOTED = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|`[^`]*`|--[^\n]*|/\*.*?\*/", re.S)


def quoted_params(sql: str) -> list[str]:
    """Each value named inside quotes or a comment, once: there it is part of the words, and the engine never binds it."""
    out: list[str] = []
    for m in _QUOTED.finditer(sql or ""):
        for p in PARAM.finditer(m.group(0)):
            if p.group(1) not in out:
                out.append(p.group(1))
    return out


def typed_value(name: str, kind: str, value: Any) -> Any:
    """A value as the engine binds it: a number of days or a number as a number, a word as text, a day as a date."""
    import datetime as dt
    if kind not in VALUE_KINDS:
        raise Refused(f"The query reads {{{{{name}}}}}, a {kind or 'value'} — a value is days, a number, words or a day.")
    if value is None or value == "":
        raise Refused(f"The query reads {{{{{name}}}}}, which holds nothing yet.")
    try:
        if kind in ("days", "number"):
            if isinstance(value, bool):
                raise TypeError(value)
            n = float(value)
            if n != n or n in (float("inf"), float("-inf")):
                raise ValueError(value)
            if kind == "days" and not (n.is_integer() and n >= 1):
                raise ValueError(value)
            return int(n) if n.is_integer() else n
        if kind == "date":
            return dt.date.fromisoformat(str(value))
        if not isinstance(value, str) or len(value) > MAX_WORD:
            raise ValueError(value)
        return value
    except (TypeError, ValueError):
        what = {"days": "a whole number of days", "number": "a number", "date": "a day, written 2026-10-11"}.get(
            kind, f"words, at most {MAX_WORD} characters")
        raise Refused(f"The query reads {{{{{name}}}}} as {what}, and it holds {str(value)[:40]!r}.")


def bind(sql: str, values: dict) -> tuple[str, dict]:
    """The statement with each ``{{name}}`` as the SQL editor's own ``:name`` placeholder, and the values to bind to them —
    the engine binds each; it is never pasted into the statement. ``values`` is name → ``{"kind", "value"}``: the
    cockpit's values as the page holds them now. A name the cockpit holds no value for is refused, said, and so is one
    written inside quotes or a comment, where it would be read as words and never as the value."""
    quoted = quoted_params(sql)
    if quoted:
        raise Refused(f"{', '.join('{{' + n + '}}' for n in quoted)} is written inside quotes or a comment, where it is read "
                      f"as those words and never as the value. Write it bare: WHERE country = {{{{{quoted[0]}}}}}.")
    names = params_of(sql)
    missing = [n for n in names if not isinstance((values or {}).get(n), dict)]
    if missing:
        raise Refused(f"The query reads {', '.join('{{' + n + '}}' for n in missing)}, and this cockpit holds no value of "
                      f"{'that name' if len(missing) == 1 else 'those names'}.")
    params = {engine_name(n): typed_value(n, str(values[n].get("kind") or ""), values[n].get("value")) for n in names}
    return PARAM.sub(lambda m: ":" + engine_name(m.group(1)), sql), params


# ── the statement around a person's own ───────────────────────────────────────────────────────────────────────────────

def _inner(sql: str) -> str:
    return re.sub(r"[\s;]+$", "", sql or "")


def _col(name: str):
    from sqlglot import exp
    return exp.column(name, table="q", quoted=True)


def _bucketed(name: str, kind: str, bucket: str, dialect: str):
    from sqlglot import exp
    unit = bucket.upper()
    col = _col(name)
    if dialect == "bigquery":
        # BigQuery truncates a DATE and a TIMESTAMP by different functions; a DATETIME reads as a TIMESTAMP when cast.
        # Its weeks start on Sunday unless told — every other engine here starts them on Monday.
        unit_var = exp.var("WEEK(MONDAY)" if unit == "WEEK" else unit)
        if kind == "date":
            return exp.DateTrunc(this=col, unit=unit_var)
        # sqlglot spells BigQuery's TIMESTAMP as a timestamp with a time zone: its plain TIMESTAMP is BigQuery's DATETIME,
        # which TIMESTAMP_TRUNC refuses
        return exp.TimestampTrunc(this=exp.cast(col, exp.DataType.build("timestamptz")), unit=unit_var)
    return exp.DateTrunc(this=col, unit=exp.var(unit))


def _aggregates(series: list[Series]) -> list:
    from sqlglot import exp
    out = []
    for i, s in enumerate(series):
        if s.agg == "count":
            out.append(exp.Count(this=_col(s.column) if s.column else exp.Star()).as_(f"v{i}"))
        elif s.agg == "count_distinct":
            out.append(exp.Count(this=exp.Distinct(expressions=[_col(s.column)])).as_(f"v{i}"))
        elif s.agg == "avg":
            # an average is kept as its sum and its count, so the rest of a split folds into Other exactly
            out.append(exp.Sum(this=_col(s.column)).as_(f"v{i}_sum"))
            out.append(exp.Count(this=_col(s.column)).as_(f"v{i}_n"))
        else:
            fn = {"sum": exp.Sum, "min": exp.Min, "max": exp.Max}[s.agg]
            out.append(fn(this=_col(s.column)).as_(f"v{i}"))
    return out


def _embed(outer, inner: str, dialect: str) -> str:
    """The generated statement, with the person's own put in word for word where it reads ``aughor_q_inner``."""
    text = outer.sql(dialect=dialect)
    if text.count(_INNER) != 1:
        raise Refused("The statement around this query could not be written.")
    return text.replace(_INNER, f"(\n{inner}\n)")


def statement(sql: str, shown: Shown, columns: list[dict], dialect: str) -> tuple[str, int]:
    """What runs for a card shown as asked, and the most rows to read: the person's statement summed around, sorted or
    as it is. The statement itself is never rewritten."""
    from sqlglot import exp
    inner = _inner(sql)
    kinds = _kinds(columns)
    source = exp.Table(this=exp.to_identifier(_INNER), alias=exp.TableAlias(this=exp.to_identifier("q")))
    if shown.as_ == "table":
        if not shown.columns and not shown.sort:
            return inner, TABLE_ROWS + 1
        picked = [_col(c) for c in shown.columns] or [exp.Star()]
        outer = exp.select(*picked).from_(source)
        if shown.sort:
            outer = outer.order_by(exp.Ordered(this=_col(shown.sort), desc=shown.descending))
        return _embed(outer.limit(TABLE_ROWS + 1), inner, dialect), TABLE_ROWS + 1
    if shown.as_ == "figure":
        if not shown.summed:
            return inner, 2
        return _embed(exp.select(*_aggregates(shown.series)).from_(source), inner, dialect), 2
    if not shown.summed:
        return inner, MAX_POINTS + 1
    x = _bucketed(shown.x, kinds.get(shown.x, "text"), shown.bucket, dialect) if shown.bucket else _col(shown.x)
    picked = [x.as_("x")]
    groups = [exp.Literal.number(1)]
    if shown.split:
        picked.append(_col(shown.split).as_("s"))
        groups.append(exp.Literal.number(2))
    outer = (exp.select(*picked, *_aggregates(shown.series)).from_(source).group_by(*groups)
             .order_by(exp.Literal.number(1)).limit(MAX_GROUPS + 1))
    return _embed(outer, inner, dialect), MAX_GROUPS + 1


# ── what a run is shaped into ─────────────────────────────────────────────────────────────────────────────────────────

def _num(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _order(v: Any) -> tuple:
    """Numbers along the bottom in their own order — 2 before 10 — everything else as it reads."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return (0, float(v), "")
    return (1, 0.0, "" if v is None else str(v))


def series_name(s: Series) -> str:
    return AGG_WORDS.get(s.agg, s.agg) + (f" of {s.column}" if s.column else "")


def _fold(agg: str, a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None:
        return b
    if b is None:
        return a
    return min(a, b) if agg == "min" else max(a, b) if agg == "max" else a + b


def shape(columns: list[dict], rows: list[list], shown: Shown) -> dict:
    """A run as a card draws it: a figure's value, a table's rows, or a chart's points — ``{x, s, v}``, a series per
    split value (the top few, the rest as Other) or per thing summed — with what was left out said."""
    names = [str(c.get("name")) for c in columns]
    at = {n: i for i, n in enumerate(names)}
    said: list[str] = []
    if shown.as_ == "table":
        more = len(rows) > TABLE_ROWS
        return {"as": "table", "columns": columns, "rows": rows[:TABLE_ROWS], "more": more,
                "said": [f"The first {TABLE_ROWS} rows; the query returns more."] if more else []}
    if shown.as_ == "figure":
        s = shown.series[0]
        if shown.summed:
            v = _num(rows[0][at["v0"]]) if rows and "v0" in at else None
            if s.agg == "avg" and rows and "v0_sum" in at:
                total, n = _num(rows[0][at["v0_sum"]]), _num(rows[0][at["v0_n"]])
                v = (total / n) if total is not None and n else None
        else:
            v = _num(rows[0][at[s.column]]) if rows and s.column in at else None
            if len(rows) > 1:
                said.append("The query returns more than one row; the figure is its first.")
        return {"as": "figure", "value": v, "label": shown.label or series_name(s), "said": said}
    # a date or a time put in buckets is said by the day each bucket starts on
    xk = "date" if shown.summed and shown.bucket else kind_of(
        next((str(c.get("type") or "") for c in columns if c.get("name") == ("x" if shown.summed else shown.x)), ""))
    limit = MAX_GROUPS if shown.summed else MAX_POINTS
    if len(rows) > limit:
        rows = rows[:limit]
        said.append(f"Only the first {limit:,} {'groups' if shown.summed else 'points'} are drawn; "
                    + ("split by fewer values or put the dates in larger buckets." if shown.summed else "the query returns more."))
    points: list[dict] = []
    if not shown.summed:
        xi = at.get(shown.x)
        si = at.get(shown.split) if shown.split else None
        for r in rows:
            for s in shown.series:
                yi = at.get(s.column)
                if xi is None or yi is None:
                    continue
                points.append({"x": r[xi], "s": (str(r[si]) if si is not None else series_name(s) if len(shown.series) > 1
                                                 else ""), "v": _num(r[yi])})
    else:
        for r in rows:
            for i, s in enumerate(shown.series):
                if s.agg == "avg":
                    v = (_num(r[at[f"v{i}_sum"]]), _num(r[at[f"v{i}_n"]]))
                else:
                    v = _num(r[at[f"v{i}"]])
                split = str(r[at["s"]]) if shown.split else (series_name(s) if len(shown.series) > 1 else "")
                points.append({"x": r[at["x"]], "s": split, "v": v, "agg": s.agg})
    order: list[str] = []
    other = False
    if shown.split:
        totals: dict[str, float] = {}
        for p in points:
            v = p["v"][0] if isinstance(p["v"], tuple) else p["v"]
            totals[p["s"]] = totals.get(p["s"], 0.0) + (v or 0.0)
        ranked = sorted(totals, key=lambda k: (-totals[k], k))
        order = ranked[:shown.top]
        rest = set(ranked[shown.top:])
        if rest:
            agg = shown.series[0].agg
            if not shown.summed or agg == "count_distinct":
                # a query's own numbers are never added up — an average or a rate is not a sum — nor are counts of
                # different values, where one customer can be in two
                points = [p for p in points if p["s"] not in rest]
                said.append(f"The {len(rest)} other values of {shown.split} are not drawn: "
                            + ("the query's own numbers are not added up into Other." if not shown.summed
                               else "a count of different values cannot be added up into Other."))
            else:
                folded: dict[Any, Any] = {}
                kept = []
                for p in points:
                    if p["s"] not in rest:
                        kept.append(p)
                        continue
                    prev = folded.get(p["x"])
                    if isinstance(p["v"], tuple):
                        folded[p["x"]] = p["v"] if prev is None else (_fold("sum", prev[0], p["v"][0]), _fold("sum", prev[1], p["v"][1]))
                    else:
                        folded[p["x"]] = _fold(agg, prev, p["v"])
                kept += [{"x": x, "s": "Other", "v": v, "agg": agg} for x, v in folded.items()]
                points = kept
                other = True
    else:
        order = [series_name(s) for s in shown.series] if len(shown.series) > 1 else [""]
    for p in points:
        if isinstance(p["v"], tuple):
            total, n = p["v"]
            p["v"] = (total / n) if total is not None and n else None
        p.pop("agg", None)
    points.sort(key=lambda p: (_order(p["x"]), p["s"]))
    if shown.running:
        acc: dict[str, float] = {}
        for p in points:
            acc[p["s"]] = acc.get(p["s"], 0.0) + (p["v"] or 0.0)
            p["v"] = acc[p["s"]]
    return {"as": shown.as_, "x": {"name": shown.x, "kind": xk, "bucket": shown.bucket},
            "series": order + (["Other"] if other else []), "points": points, "other": other, "said": said}


# ── reading a statement, and where its tables come from ───────────────────────────────────────────────────────────────

def tables_of(sql: str, dialect: str) -> list[str]:
    """The tables a statement reads, by their own names (the last part of a qualified one), its own CTEs left out."""
    import sqlglot
    from sqlglot import exp
    try:
        tree = sqlglot.parse_one(PARAM.sub("NULL", _inner(sql)), read=dialect or None)
    except Exception:
        return []
    ctes = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    names = {(t.name or "").lower() for t in tree.find_all(exp.Table)} - ctes - {""}
    text = (sql or "").lower()

    def first(name: str) -> int:
        found = re.search(rf"\b{re.escape(name)}\b", text)
        return found.start() if found else len(text)
    return sorted(names, key=lambda n: (first(n), n))       # in the order the statement names them


def policy_refusal(graph: Any, tables: list[str]) -> Optional[str]:
    """Why a query cannot be kept or run while row policies hold — it reads the table of an entity a policy narrows,
    straight, so no reader's policy can narrow it — or None."""
    from aughor.ontology import security
    if graph is None or not security.enabled():
        return None
    for name in tables:
        for entity in getattr(graph, "entities", {}).values():
            backing = getattr(entity, "backing", None)
            read = {str(t or "").split(".")[-1].lower() for t in [getattr(backing, "table", "") if backing else "",
                                                                    *(getattr(entity, "source_tables", []) or []),
                                                                    *(getattr(b, "table", "") for b in
                                                                      getattr(entity, "bindings", []) or [])]} - {""}
            if name in read and entity.row_policies:
                return (f"This query reads {name} straight from its table, and {entity.id} has a row policy: a query "
                        f"cannot be narrowed to each reader. Read {entity.id} through a set instead.")
    return None


# ── running ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def time_limit(connection_id: str) -> float:
    """The seconds a run may take: the connection's own budget when it sets one, else `RUN_LIMIT_S`."""
    try:
        from aughor.security.sandbox import get_budget
        ms = float(get_budget(connection_id).max_time_ms or 0)
    except Exception:
        ms = 0.0
    return ms / 1000.0 if ms > 0 else RUN_LIMIT_S


@contextlib.contextmanager
def stopped_after(db: Any, seconds: float) -> Iterator[dict]:
    """Run the body with the engine asked to stop it after ``seconds``; ``out["stopped"]`` says whether it was."""
    out = {"stopped": False}

    def stop() -> None:
        from aughor.kernel.errors import tolerate
        out["stopped"] = True
        try:
            db.interrupt()
        except Exception as exc:
            tolerate(exc, "cockpit query: the engine could not be asked to stop", counter="cockpit.query_interrupt")
    timer = threading.Timer(seconds, stop)
    timer.daemon = True
    timer.start()
    try:
        yield out
    finally:
        timer.cancel()


def execute(db: Any, sql: str, *, max_rows: int, seconds: float, params: Optional[dict] = None) -> dict:
    """One statement through the connection's own door — the read-only checks every person's SQL meets in the SQL editor —
    typed, bounded and stopped after ``seconds``; with ``params``, its ``:name`` placeholders bound by the engine."""
    from aughor.routers.query import typed_response
    started = time.monotonic()
    with stopped_after(db, seconds) as watch:
        if params:
            result, payload = db.execute_with_params_typed(_SOURCE, sql, params, max_rows=max_rows)
        else:
            result, payload = db.execute_typed(_SOURCE, sql, max_rows=max_rows)
    ms = (time.monotonic() - started) * 1000
    if watch["stopped"]:
        return {"error": f"The query was stopped after {seconds:g} s.", "columns": [], "rows": [], "duration_ms": ms,
                "caveats": [], "truncated": False}
    if result.error or payload is None:
        return {"error": result.error or "The query returned nothing this card can read.", "columns": [], "rows": [],
                "duration_ms": ms, "caveats": list(result.caveats or []), "truncated": False}
    typed = typed_response(result, payload, max_rows, ms, None, list(result.caveats or []), requested_sql=sql)
    return {"error": None, "columns": typed["columns_typed"], "rows": typed["rows"], "duration_ms": typed["duration_ms"],
            "caveats": typed.get("caveats") or [], "truncated": bool(typed.get("truncated"))}


def dialect_of(db: Any) -> str:
    return str(getattr(db, "dialect", "") or "duckdb").lower()


def probe(db: Any, sql: str, *, seconds: float, rows: int = PREVIEW_ROWS, params: Optional[dict] = None) -> dict:
    """The statement as it is: its typed columns and first rows, and how long it took."""
    return execute(db, _inner(sql), max_rows=rows + 1, seconds=seconds, params=params)


def run(db: Any, sql: str, shown: Shown, columns: list[dict], *, seconds: float, params: Optional[dict] = None) -> dict:
    """A card shown as asked: the statement around the person's own, run and shaped."""
    stmt, max_rows = statement(sql, shown, columns, dialect_of(db))
    out = execute(db, stmt, max_rows=max_rows, seconds=seconds, params=params)
    if out["error"]:
        return {**out, "shown": None}
    return {**out, "shown": shape(out["columns"], out["rows"], shown)}
