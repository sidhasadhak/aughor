"""Arc BR-2 · a metric that knows its date, so any range is measured by construction.

ROADMAP §3.48. Before this, a period Briefing measured a headline metric by finding a date
inside a model-written chart query — on theLook none in six of eight and the wrong one in the
seventh (2026-09-25). A metric now carries its time fields (``MetricDefinition``):

* ``time_column`` — the date that puts a row in a range;
* ``time_kind`` — **flow** (adds up over the range: revenue, orders), **stock** (a level at a
  date: a row counts from ``time_column`` until ``until_column``), or **cohort** (tied to
  ``time_column``, completed by a later ``outcome_column``, maturing over
  ``settles_after_days`` — the return rate);
* ``time_source`` — where they came from, in words; ``time_confirmed_by`` — the person who
  confirmed or corrected them.

**Set automatically** (the user's call, §6 item 34(b)): by RULE, from the metric's own formula
and filters and the profiler's table dates, and — for a cohort's maturity — by MEASUREMENT.
Never by a model: a rule can say which rule it applied, and a person corrects it in the metric
editor. A formula the rules cannot read (a whole SELECT) stays unset, and says why.

**Compiled, never cut**: ``measure_sql`` builds the query for a list of windows from the
definition — a flow filtered on its date, a stock's level at each window's end, a cohort
anchored in the window with its outcome counted only up to the window's as-of — one
``UNION ALL`` statement, one row per window (and group). Pure and DB-free; ``run_measure``
runs it through an injected ``run_sql(sql) -> (columns, rows, error)``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import reduce
from typing import Any, Callable, Optional

KINDS = ("flow", "stock", "cohort")
#: The fields an edit may send; ``time_source`` is written by the platform, never sent.
TIME_FIELDS = ("time_column", "time_kind", "outcome_column", "until_column",
               "settles_after_days", "time_confirmed_by")
#: A cohort's maturity is the day by which this share of its outcomes has arrived.
MATURITY_SHARE = 0.95
#: Fewer outcomes than this and a maturity is not measured — it is said to be unknown.
MATURITY_MIN_ROWS = 30

RunSql = Callable[[str], tuple]


def _get(m: Any, key: str):
    return m.get(key) if isinstance(m, dict) else getattr(m, key, None)


def declared(m: Any) -> bool:
    """True when the metric can be measured for a range: a kind and a date, and — for a
    stock or a cohort — the second column its kind needs."""
    kind, col = _get(m, "time_kind"), _get(m, "time_column")
    if kind not in KINDS or not col:
        return False
    if kind == "stock":
        return bool(_get(m, "until_column"))
    if kind == "cohort":
        return bool(_get(m, "outcome_column"))
    return True


def merge_time_edit(existing: Any, sent: dict) -> dict:
    """The time fields an edit writes: the existing ones, overlaid by what the edit SENT. A
    sent change is a person's — ``time_source`` says so and ``time_confirmed_by`` names them.
    An edit that sends none keeps what the platform set; it must not erase it."""
    out = {k: (_get(existing, k) if existing is not None else None)
           for k in (*TIME_FIELDS, "time_source")}
    if not sent:
        return out
    kind = sent.get("time_kind", out["time_kind"])
    if kind is not None and kind not in KINDS:
        raise ValueError(f"time_kind must be one of {', '.join(KINDS)}")
    before = {k: out[k] for k in TIME_FIELDS if k != "time_confirmed_by"}
    out.update({k: v for k, v in sent.items() if k in TIME_FIELDS})
    who = sent.get("time_confirmed_by") or out.get("time_confirmed_by") or "a person"
    out["time_confirmed_by"] = who
    changed = any(out[k] != v for k, v in before.items())
    # a confirmation keeps the rule and the measurement that set the fields, and adds who
    # stood behind them; a correction replaces them, so the source is the person's alone
    out["time_source"] = (f"set by {who} in the metric editor" if changed or not out.get("time_source")
                          else f"{out['time_source']}; confirmed by {who}")
    return out


# ── set automatically, by rule ─────────────────────────────────────────────────────────────

@dataclass
class Inference:
    fields: Optional[dict]   # the time fields to write, or None when no rule applies
    reason: str = ""         # why not, when ``fields`` is None


def _bare(name: str) -> str:
    return str(name or "").split(".")[-1].strip('`"[]').lower()


def _table_columns(profile_entry: dict, table: str) -> dict[str, str]:
    """column → declared type (lower-case), from the profiler's latest entry, whose columns are
    keyed FLAT as ``"table.column"`` (measured on theLook 2026-09-26 — a nested reading found
    none, and every metric fell back to its table's main date)."""
    out: dict[str, str] = {}
    for key, prof in ((profile_entry or {}).get("columns") or {}).items():
        if not isinstance(prof, dict):
            continue
        owner = str(prof.get("table") or str(key).split(".", 1)[0]).lower()
        if _bare(owner) != table:
            continue
        name = str(prof.get("column") or str(key).split(".", 1)[-1]).lower()
        out[name] = str(prof.get("dtype") or "").lower()
    return out


def _primary_date(profile_entry: dict, table: str) -> str:
    tp = ((profile_entry or {}).get("tables") or {}).get(table) or {}
    return str(tp.get("primary_timestamp") or "").lower() if isinstance(tp, dict) else ""


def _is_time(dtype: str) -> bool:
    return "date" in dtype or "time" in dtype


def _null_test(node) -> tuple[Optional[str], Optional[bool]]:
    """``X IS NOT NULL`` → (x, True); ``X IS NULL`` → (x, False); anything else → (None, None)."""
    from sqlglot import exp
    negated = isinstance(node, exp.Not)
    inner = node.this if negated else node
    if (isinstance(inner, exp.Is) and isinstance(inner.expression, exp.Null)
            and isinstance(inner.this, exp.Column)):
        return inner.this.name.lower(), negated
    return None, None


def _conjuncts(node) -> list:
    from sqlglot import exp
    while isinstance(node, exp.Paren):
        node = node.this
    if isinstance(node, exp.And):
        return _conjuncts(node.this) + _conjuncts(node.expression)
    return [node]


def _presence_tests(node, time_cols: set[str]) -> set[str]:
    """The date columns a formula tests for presence: ``X IS NOT NULL`` or ``COUNT(X)``."""
    from sqlglot import exp
    out: set[str] = set()
    for n in node.find_all(exp.Not):
        col, present = _null_test(n)
        if col in time_cols and present:
            out.add(col)
    for c in node.find_all(exp.Count):
        arg = c.this
        if isinstance(arg, exp.Column) and arg.name.lower() in time_cols:
            out.add(arg.name.lower())
    return out


def _ratio(node):
    """(numerator, denominator) of a formula that is a ratio — ``a / b``, ``100 * a / b``,
    ``100 * (a / b)`` — or None."""
    from sqlglot import exp
    while isinstance(node, exp.Paren):
        node = node.this
    if isinstance(node, exp.Div):
        return node.this, node.expression
    if isinstance(node, exp.Mul):
        for side in (node.this, node.expression):
            found = _ratio(side)
            if found:
                return found
    return None


def _set(kind: str, column: str, source: str, *, outcome: str = None, until: str = None) -> Inference:
    return Inference({"time_kind": kind, "time_column": column, "outcome_column": outcome,
                      "until_column": until, "time_source": source})


def infer(metric: Any, profile_entry: dict, *, dialect: str = "duckdb") -> Inference:
    """The time fields the platform sets for ``metric``, by rule, with the rule in words.

    In order: a filter keeping rows where a date is EMPTY makes a level (stock); a ratio whose
    numerator alone tests a later date makes a cohort; a filter requiring a date makes that
    date the flow's; a formula counting rows that have one date makes it the flow's; otherwise
    the table's main date — the one the platform reads to learn when its numbers settle."""
    import sqlglot

    sql = str(_get(metric, "sql") or "").strip()
    tables = list(_get(metric, "tables") or [])
    if not sql:
        return Inference(None, "it has no formula")
    if sql.lower().startswith("select"):
        return Inference(None, "its formula is a whole query, so its date must be set by a person")
    if not tables:
        return Inference(None, "it names no table")
    table = _bare(tables[0])
    time_cols = {c for c, d in _table_columns(profile_entry, table).items() if _is_time(d)}
    primary = _primary_date(profile_entry, table)
    if primary:
        time_cols.add(primary)
    try:
        expr = sqlglot.parse_one(sql, read=dialect)
        filters = [sqlglot.parse_one(str(f), read=dialect)
                   for f in (_get(metric, "filters") or []) if str(f).strip()]
    except Exception:  # noqa: BLE001 — a formula the parser refuses is said, not guessed
        return Inference(None, "its formula does not parse")
    required: set[str] = set()
    empty: set[str] = set()
    for f in filters:
        for c in _conjuncts(f):
            col, present = _null_test(c)
            if col in time_cols:
                (required if present else empty).add(col)

    if empty:
        until = sorted(empty)[0]
        start = primary if primary and primary != until else ""
        if not start:
            return Inference(None, f"it keeps rows where {until} is empty, but its table has no "
                                   "other date for a row to start counting from")
        return _set("stock", start, f"set automatically: its filter keeps rows where {until} is "
                                    f"empty, so it is a level — a row counts from {start} until "
                                    f"{until}", until=until)
    ratio = _ratio(expr)
    if ratio is not None:
        num, den = ratio
        later = _presence_tests(num, time_cols) - _presence_tests(den, time_cols) - required
        anchor = sorted(required)[0] if required else primary
        if later and anchor and anchor not in later:
            outcome = sorted(later)[0]
            return _set("cohort", anchor,
                        f"set automatically: its numerator counts rows that have {outcome} and its "
                        f"denominator counts every row, so it is tied to {anchor} and completed "
                        f"by {outcome}", outcome=outcome)
    if required:
        col = sorted(required)[0]
        return _set("flow", col, f"set automatically: its filter requires {col}, so a row counts "
                                 f"on the day of {col}")
    counted = _presence_tests(expr, time_cols)
    if ratio is None and len(counted) == 1:
        col = next(iter(counted))
        return _set("flow", col, f"set automatically: it counts rows that have {col}, so a row "
                                 f"counts on the day of {col}")
    if primary:
        return _set("flow", primary, f"set automatically: {primary} is the main date of {table} — "
                                     "the one the platform reads to learn when the table's numbers "
                                     "settle")
    return Inference(None, "its table has no date the profiler recognised")


def measure_maturity(metric: Any, run_sql: RunSql, *, dialect: str, today: date,
                     share: float = MATURITY_SHARE) -> tuple[Optional[int], str]:
    """A cohort's maturity, measured: the number of days by which ``share`` of its outcomes
    arrived, over rows anchored 120 to 365 days ago — old enough that an outcome up to 120
    days late is visible. Returns ``(days, how)`` or ``(None, why not)``."""
    from sqlglot import exp

    anchor, outcome = _get(metric, "time_column"), _get(metric, "outcome_column")
    tables = list(_get(metric, "tables") or [])
    if _get(metric, "time_kind") != "cohort" or not (anchor and outcome and tables):
        return None, "it is not a cohort with an anchor and an outcome"
    lo, hi = today - timedelta(days=365), today - timedelta(days=120)
    days = exp.DateDiff(this=_day(exp.column(outcome)), expression=_day(exp.column(anchor)),
                        unit=exp.var("DAY"))
    conds = [exp.Not(this=exp.Is(this=exp.column(outcome), expression=exp.Null())),
             exp.GTE(this=_day(exp.column(anchor)), expression=_lit(lo)),
             exp.LT(this=_day(exp.column(anchor)), expression=_lit(hi))]
    filters, why = _parsed_filters(metric, dialect)
    if filters is None:
        return None, why
    q = (exp.select(exp.alias_(days, "d"), exp.alias_(exp.Count(this=exp.Star()), "n"))
         .from_(_table(tables[0], dialect)).where(exp.and_(*conds, *filters))
         .group_by(exp.Literal.number(1)))
    try:
        _cols, rows, error = run_sql(q.sql(dialect=dialect))
    except Exception as exc:  # noqa: BLE001
        rows, error = [], type(exc).__name__
    if error:
        return None, f"its maturity query failed: {str(error)[:160]}"
    dist: dict[int, float] = {}
    for r in rows or []:
        cells = list(r.values()) if isinstance(r, dict) else list(r)
        d, n = _num(cells[0]), _num(cells[1])
        if d is not None and n:
            dist[int(d)] = dist.get(int(d), 0.0) + n
    total = sum(dist.values())
    if total < MATURITY_MIN_ROWS:
        return None, f"too few {outcome} rows to measure ({int(total)})"
    seen = 0.0
    for d in sorted(dist):
        seen += dist[d]
        if seen / total >= share:
            got = max(int(d), 0)
            return got, (f"measured {today.isoformat()}: {share:.0%} of {outcome} arrived within "
                         f"{got} days of {anchor}, over {int(total)} rows anchored "
                         f"{lo.isoformat()} to {hi.isoformat()}")
    return None, "its outcomes never reached the share"   # unreachable: the loop ends at 100%


# ── compiled, never cut ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Window:
    label: str                      # "current" | "previous" | "last_year" | …
    start: date
    end: date                       # exclusive — the day after the last day
    as_of: Optional[date] = None    # a cohort's outcomes are counted before this day

    @property
    def last_day(self) -> date:
        return self.end - timedelta(days=1)


def _day(node):
    from sqlglot import exp
    return exp.Cast(this=node, to=exp.DataType.build("date"))


def _lit(d: date):
    from sqlglot import exp
    return exp.Cast(this=exp.Literal.string(d.isoformat()), to=exp.DataType.build("date"))


def _table(name: str, dialect: str):
    from sqlglot import exp
    return exp.to_table(str(name), dialect=dialect)


def _parsed_filters(metric: Any, dialect: str) -> tuple[Optional[list], str]:
    import sqlglot
    try:
        return [sqlglot.parse_one(str(f), read=dialect)
                for f in (_get(metric, "filters") or []) if str(f).strip()], ""
    except Exception:  # noqa: BLE001
        return None, "a filter of its definition does not parse"


def bound_outcome(expr, outcome: str, as_of: date):
    """``expr`` with the cohort's outcome counted only before ``as_of``: ``X IS NOT NULL``
    becomes ``(X IS NOT NULL AND CAST(X AS DATE) < as_of)`` and ``COUNT(X)`` counts only
    those. Returns ``(expr, "")``, or ``(None, why)`` when ``X`` is used some other way —
    a bound the formula cannot take is refused, never approximated."""
    from sqlglot import exp

    out = expr.copy()
    target = outcome.lower()
    rewrites = []
    for n in out.find_all(exp.Not):
        col, present = _null_test(n)
        if col == target and present:
            rewrites.append((n, exp.paren(exp.and_(n.copy(), exp.LT(
                this=_day(exp.column(outcome)), expression=_lit(as_of))))))
    for c in out.find_all(exp.Count):
        if isinstance(c.this, exp.Column) and c.this.name.lower() == target and not c.args.get("distinct"):
            rewrites.append((c, exp.Count(this=exp.Case().when(
                exp.LT(this=_day(exp.column(outcome)), expression=_lit(as_of)), exp.column(outcome)))))
    handled = {id(col) for n, _ in rewrites for col in n.find_all(exp.Column)}
    stray = [c for c in out.find_all(exp.Column) if c.name.lower() == target and id(c) not in handled]
    if stray or not rewrites:
        return None, (f"its formula uses {outcome} in a way an as-of bound cannot rewrite"
                      if stray else f"its formula does not test {outcome}")
    for old, new in rewrites:
        old.replace(new)
    return out, ""


def measure_sql(metric: Any, windows: list[Window], *, dialect: str = "duckdb",
                by: Optional[str] = None) -> tuple[Optional[str], str]:
    """One statement measuring ``metric`` for every window — ``_w`` (the window's label),
    ``_g`` (the group, when ``by``), ``_v`` (the value), ``_first`` / ``_last`` (the first and
    last day its rows cover). ``(sql, "")`` or ``(None, why)``; never raises."""
    import sqlglot
    from sqlglot import exp

    if not windows:
        return None, "no window to measure"
    if not declared(metric):
        return None, "its dates are not set"
    formula = str(_get(metric, "sql") or "").strip()
    tables = list(_get(metric, "tables") or [])
    if not formula or formula.lower().startswith("select") or not tables:
        return None, "its formula is not an aggregate over a named table"
    kind = _get(metric, "time_kind")
    time_col = str(_get(metric, "time_column"))
    until = str(_get(metric, "until_column") or "")
    outcome = str(_get(metric, "outcome_column") or "")
    try:
        expr = sqlglot.parse_one(formula, read=dialect)
    except Exception:  # noqa: BLE001
        return None, "its formula does not parse"
    filters, why = _parsed_filters(metric, dialect)
    if filters is None:
        return None, why
    if kind == "stock":
        # "where until is empty" is the level NOW; at a past date it is replaced below
        filters = [c for f in filters for c in _conjuncts(f) if _null_test(c) != (until.lower(), False)]
    day = _day(exp.column(time_col))
    selects = []
    for w in windows:
        value = expr
        if kind == "stock":
            when = exp.and_(exp.LT(this=day.copy(), expression=_lit(w.end)),
                            exp.paren(exp.or_(exp.Is(this=exp.column(until), expression=exp.Null()),
                                              exp.GTE(this=_day(exp.column(until)), expression=_lit(w.end)))))
        else:
            when = exp.and_(exp.GTE(this=day.copy(), expression=_lit(w.start)),
                            exp.LT(this=day.copy(), expression=_lit(w.end)))
            if kind == "cohort" and w.as_of is not None:
                value, why = bound_outcome(expr, outcome, w.as_of)
                if value is None:
                    return None, why
        cols = [exp.alias_(exp.Literal.string(w.label), "_w")]
        if by:
            cols.append(exp.alias_(exp.column(by), "_g"))
        cols += [exp.alias_(exp.paren(value.copy()), "_v"),
                 exp.alias_(exp.Min(this=day.copy()), "_first"),
                 exp.alias_(exp.Max(this=day.copy()), "_last")]
        q = exp.select(*cols).from_(_table(tables[0], dialect)).where(
            exp.and_(*[f.copy() for f in filters], when))
        if by:
            q = q.group_by(exp.column(by))
        selects.append(q)
    try:
        stmt = reduce(lambda a, b: exp.union(a, b, distinct=False), selects)
        return stmt.sql(dialect=dialect), ""
    except Exception as exc:  # noqa: BLE001
        return None, f"its query could not be built ({type(exc).__name__})"


def _num(v) -> Optional[float]:
    if v is None or (isinstance(v, str) and v.strip().upper() in ("", "NULL", "NONE")):
        return None
    try:
        return float(str(v).replace(",", "")) if isinstance(v, str) else float(v)
    except (TypeError, ValueError):
        return None


def _as_date(v) -> Optional[date]:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def run_measure(metric: Any, windows: list[Window], run_sql: RunSql, *, dialect: str = "duckdb",
                by: Optional[str] = None) -> tuple[list[dict], str]:
    """Measure ``metric`` for every window. ``([{"window", "group", "value", "first", "last"}],
    "")`` or ``([], why)`` — a failed query is said with its error, never read as zero."""
    sql, why = measure_sql(metric, windows, dialect=dialect, by=by)
    if sql is None:
        return [], why
    try:
        _cols, rows, error = run_sql(sql)
    except Exception as exc:  # noqa: BLE001
        rows, error = [], type(exc).__name__
    if error:
        return [], f"its query failed: {str(error)[:160]}"
    out = []
    for r in rows or []:
        cells = list(r.values()) if isinstance(r, dict) else list(r)
        if len(cells) < (5 if by else 4):
            continue
        g = cells[1] if by else None
        v, first, last = cells[-3], cells[-2], cells[-1]
        out.append({"window": str(cells[0]), "group": g, "value": _num(v),
                    "first": _as_date(first), "last": _as_date(last)})
    return out, ""


def figure_status(metric: Any, window: Window, *, as_of: date, lag_days: int) -> str:
    """``to_date`` when the window reaches ``as_of`` (a month still under way); ``final`` once
    its last day has settled — the connection's lag for its rows, and for a cohort its
    maturity too; otherwise ``provisional``. A cohort with no known maturity stays
    provisional: nobody has measured when its outcome stops arriving."""
    if window.end > as_of:
        return "to_date"
    settle = max(int(lag_days or 1), 1)
    if _get(metric, "time_kind") == "cohort":
        maturity = _get(metric, "settles_after_days")
        if maturity is None:
            return "provisional"
        settle = max(settle, int(maturity))
    return "final" if (as_of - window.last_day).days >= settle else "provisional"


# ── the automatic setter (the user's call, §6 item 34(b)) ──────────────────────────────────

def ensure_dates(connection_id: str, *, run_sql: Optional[RunSql] = None, dialect: str = "duckdb",
                 today: Optional[date] = None) -> dict[str, str]:
    """Set the dates of every APPROVED metric of this connection by rule, and — given a runner —
    measure a cohort's maturity once. A metric a person confirmed or corrected is never touched;
    one set automatically is RE-DERIVED each time, so a corrected rule heals what an older rule
    set (measured 2026-09-26: the first live run saved every theLook metric as a flow on its
    table's main date, and a fixed rule could not replace them). Returns ``{metric: what
    happened}``, in words, for the Briefing to say."""
    from aughor.semantic.metrics import MetricDefinition, list_metrics, save_metric
    from aughor.tools.profile_cache import latest_profile_entry

    today = today or date.today()
    out: dict[str, str] = {}
    try:
        metrics = [m for m in list_metrics(connection_id=connection_id)
                   if m.status == "approved" and m.connection == connection_id]
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "an unreadable metric catalogue sets no dates", counter="metric_time.catalogue")
        return out
    profile = None
    for m in metrics:
        if m.time_confirmed_by:
            out[m.name] = f"confirmed by {m.time_confirmed_by}"
            continue
        if profile is None:
            profile = latest_profile_entry(connection_id)
        inf = infer(m, profile, dialect=dialect)
        if inf.fields is None:
            out[m.name] = ("set" if declared(m) else f"its dates cannot be set by rule: {inf.reason}")
            continue
        fields = dict(inf.fields)
        same = all(getattr(m, k) == fields[k]
                   for k in ("time_kind", "time_column", "outcome_column", "until_column"))
        if same and not (fields["time_kind"] == "cohort" and m.settles_after_days is None
                         and run_sql is not None):
            out[m.name] = "set"
            continue
        if same:
            fields["settles_after_days"] = m.settles_after_days
        if fields["time_kind"] == "cohort" and run_sql is not None and fields.get("settles_after_days") is None:
            days, how = measure_maturity({**m.model_dump(), **fields}, run_sql, dialect=dialect, today=today)
            fields["settles_after_days"] = days
            fields["time_source"] += f"; {how}" if days is not None else f"; maturity unknown: {how}"
        elif fields["time_kind"] != "cohort":
            fields["settles_after_days"] = None
        try:
            save_metric(MetricDefinition(**{**m.model_dump(), **fields}))
            out[m.name] = "set automatically"
        except Exception as exc:  # noqa: BLE001
            from aughor.kernel.errors import tolerate
            tolerate(exc, "a metric whose dates cannot be saved is measured without them",
                     counter="metric_time.save")
            out[m.name] = f"its dates could not be saved ({type(exc).__name__})"
    return out
