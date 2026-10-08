"""Arc BR-3 · one control: any range, the four periods as presets (ROADMAP §3.48).

The window model knew one thing — the most recent COMPLETE period relative to today
(``automations.temporal.complete_period``). "17–26 August, asked on 26 September", "August,
asked on 15 September", "September so far" and "2025" are one question with different dates,
and three of them could not be asked. A range is now a start and an end, read as of a day:

* **presets** — ``yesterday`` · ``last_week`` · ``last_month`` · ``last_year`` resolve to the
  last SETTLED day, week, month or (fiscal) year exactly as ``complete_period`` does; the
  ``*_to_date`` presets end at the last settled day, never today; ``custom`` is any range;
* **comparisons** — a named period against the one before (§3.27's rule), a custom range
  against the same number of days shifted back by WHOLE WEEKS so the weekday mix matches, and
  every range against the same weekdays 52 weeks earlier (364 days) — or the same month or
  span a year earlier for a month or a to-date range;
* **as of** — the day it is read. A cohort's comparisons are read at the SAME AGE (their
  as-of shifted by the same distance), because a young cohort against a matured one always
  reads as an improvement (§3.48 BR-6).

Measurement is BR-2's: every APPROVED metric of the connection, its dates set by rule when
missing (``semantic.metric_time.ensure_dates``), compiled for every window in one statement,
each figure *final*, *provisional* or *to date*. A north star with no approved definition is
listed as not measured, with that reason — what the departure gate's law 2 already requires
of every number that leaves.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Optional

from aughor.semantic.metric_time import Window

#: The Cockpit's periods (the user, 2026-10-08): the day, week, month or year under way — "current" —
#: and the one before it — "last". Each is read only over days whose data has ARRIVED (``data_through``,
#: read from the warehouse): most sources hold yesterday at best, so a current day read off the calendar
#: alone is empty. The Briefing's settled presets above are unchanged.
CURRENT_PRESETS = ("current_day", "current_week", "current_month", "current_year")
PREVIOUS_PRESETS = ("previous_week", "previous_month", "previous_year")
EDGE_PRESETS = CURRENT_PRESETS + PREVIOUS_PRESETS
EDGE_UNIT = {"current_day": "day", "current_week": "week", "current_month": "month",
             "current_year": "year", "previous_week": "week", "previous_month": "month",
             "previous_year": "year"}
#: The presets a range control offers, in its order.
PRESETS = ("yesterday", "last_week", "last_month", "last_year", "month_to_date",
           "year_to_date", "custom") + EDGE_PRESETS
#: A named preset is §3.27's period.
PRESET_PERIOD = {"yesterday": "day", "last_week": "week", "last_month": "month", "last_year": "year"}
PERIOD_PRESET = {v: k for k, v in PRESET_PERIOD.items()}
LABEL = {"yesterday": "Daily", "last_week": "Weekly", "last_month": "Monthly", "last_year": "Yearly",
         "month_to_date": "Month-to-date", "year_to_date": "Year-to-date", "custom": "Custom range",
         "current_day": "Current day", "current_week": "Current week", "current_month": "Current month",
         "current_year": "Current year", "previous_week": "Last week", "previous_month": "Last month",
         "previous_year": "Last year"}
#: The longest custom range; a longer question is the Year recipe's, or Ask's.
MAX_RANGE_DAYS = 3 * 366
#: The most headline metrics measured per Briefing — the standing Briefing's own cap.
#: Raised from 8 to 12 on 2026-09-27: theLook had ten approved definitions and the Briefing
#: measured seven, so three were silently reported as having "no approved definition" — the
#: cap's overflow falls through to the north-star loop, which cannot tell "over the cap" from
#: "never approved" and says the second. Twelve covers a connection that has governed its
#: headline set without inviting a Briefing that measures everything; the cost is per metric
#: per window (three windows), so each one past the cap is three more warehouse queries.
MAX_METRICS = 12
#: How many days a window's rows may start late or end early before its value stops being
#: that window's (§3.27's slack, by length).
def _slack(days: int) -> int:
    return 0 if days <= 1 else 2 if days <= 7 else 7 if days <= 31 else 31


@dataclass(frozen=True)
class RangeSpec:
    preset: str
    start: date
    end: date                              # exclusive
    previous_start: date
    previous_end: date
    last_year_start: Optional[date]
    last_year_end: Optional[date]
    as_of: date
    lag_days: int
    lag_source: str
    still_moving: tuple = field(default_factory=tuple)
    period: str = "range"                  # §3.27's word for the narrator: day|week|month|year|range
    #: The newest day whose data has arrived, as read when the range was resolved; None when unread.
    data_through: Optional[date] = None
    #: What the data's edge did to the range, in words ("" when it did nothing).
    edge_note: str = ""
    #: The day, week, month or year holding the range goes on past its last day: a period so far.
    under_way: bool = False
    fiscal_start_month: int = 1

    @property
    def last_day(self) -> date:
        return self.end - timedelta(days=1)

    @property
    def days(self) -> int:
        return (self.end - self.start).days

    @property
    def key(self) -> str:
        """The cache key: one entry per preset and dates, so two custom ranges never share one."""
        return f"range:{self.preset}:{self.start.isoformat()}..{self.last_day.isoformat()}"

    def windows(self) -> list[Window]:
        """current, previous and (when there is one) last_year — each comparison read at the
        same age as the range, so a cohort is never compared young against mature."""
        age = self.as_of - self.end
        out = [Window("current", self.start, self.end, as_of=self.as_of),
               Window("previous", self.previous_start, self.previous_end, as_of=self.previous_end + age)]
        if self.last_year_start and self.last_year_end:
            out.append(Window("last_year", self.last_year_start, self.last_year_end,
                              as_of=self.last_year_end + age))
        return out


def _d(d: date) -> str:
    return d.isoformat()


def _span(start: date, end: date) -> str:
    last = end - timedelta(days=1)
    return _d(start) if start == last else f"{_d(start)} to {_d(last)}"


def _year_back(d: date) -> date:
    try:
        return d.replace(year=d.year - 1)
    except ValueError:               # 29 February
        return d.replace(year=d.year - 1, day=28)


def _year_on(d: date) -> date:
    try:
        return d.replace(year=d.year + 1)
    except ValueError:               # 29 February
        return d.replace(year=d.year + 1, day=28)


def _unit_start(unit: str, d: date, fiscal: int) -> date:
    """The first day of the day, week (Monday), month or (fiscal) year holding ``d``."""
    if unit == "day":
        return d
    if unit == "week":
        return d - timedelta(days=d.weekday())
    if unit == "month":
        return d.replace(day=1)
    s = date(d.year, fiscal, 1)
    return s if s <= d else date(d.year - 1, fiscal, 1)


def _unit_end(unit: str, start: date) -> date:
    """The day after the unit that begins on ``start`` ends."""
    if unit == "day":
        return start + timedelta(days=1)
    if unit == "week":
        return start + timedelta(days=7)
    if unit == "month":
        return (start + timedelta(days=32)).replace(day=1)
    return _year_on(start)


def _unit_before(unit: str, start: date) -> date:
    """The first day of the unit before the one that begins on ``start``."""
    if unit == "day":
        return start - timedelta(days=1)
    if unit == "week":
        return start - timedelta(days=7)
    if unit == "month":
        return (start - timedelta(days=1)).replace(day=1)
    return _year_back(start)


def _year_words(start: date) -> str:
    return str(start.year) if start.month == 1 else f"the fiscal year from {_d(start)}"


def _edge_note(*, today: date, through: Optional[date], complete: date, held_by: tuple,
               tables: dict, fell_back: Optional[str], asked_to: Optional[date]) -> str:
    """What the data's edge did to a range, in words a reader checks: where the data ends, which
    table holds it there, and what the range became because of it."""
    if through is None:
        said = (f"Whether data has arrived after {_d(complete)} was not read, so figures run to it, "
                "yesterday.")
    elif through >= today:
        said = (f"Today ({_d(today)}) is still loading, so it is left out: figures run to "
                f"{_d(complete)}, the newest complete day.")
    elif through == today - timedelta(days=1):
        said = f"Data runs to {_d(through)}: today ({_d(today)}) has no rows yet."
    else:
        said = f"Data runs to {_d(through)}: nothing after it has arrived yet."
    if through is not None and held_by and len(set(tables.values())) > 1:
        ahead = sorted(t for t, d in tables.items() if d > through)
        said += (f" {', '.join(held_by)} {'has' if len(held_by) == 1 else 'have'} no rows after "
                 f"{_d(through)}; {', '.join(ahead)} {'runs' if len(ahead) == 1 else 'run'} later.")
    if fell_back:
        said = f"{fell_back} has no complete day yet, so this is the newest that has. " + said
    if asked_to is not None:
        said = f"Asked to {_d(asked_to)}, read to {_d(complete)}. " + said
    return said


def _edge_range(preset: str, *, today: date, through: Optional[date], held_by: tuple, tables: dict,
                fiscal: int, common: dict) -> RangeSpec:
    """A current or last period, read over the days whose data has arrived.

    The newest COMPLETE day is ``complete``: the data's own last day, never today — a day still
    loading is part of a day, and a part against a whole is not a comparison. A current period is
    the one holding today, cut at ``complete``; one with no data yet falls back to the newest that
    has (and says so). A last period is the one before it, cut the same way when its data has not
    all arrived. A cut period is compared with the same days of the period before, so every
    comparison is like for like."""
    unit = EDGE_UNIT[preset]
    yesterday = today - timedelta(days=1)
    complete = yesterday if through is None else min(through, yesterday)
    if preset in CURRENT_PRESETS:
        s = _unit_start(unit, today, fiscal)
    else:
        s = _unit_before(unit, _unit_start(unit, today, fiscal))
    fell_back = None
    if complete < s:
        if unit != "day":
            fell_back = {"week": f"The week of {_d(s)}", "month": s.strftime("%B %Y"),
                         "year": _year_words(s)[0].upper() + _year_words(s)[1:]}[unit]
        s = _unit_start(unit, complete, fiscal)
    whole = _unit_end(unit, s)
    e = min(whole, complete + timedelta(days=1))
    days = e - s
    if unit == "day":
        ps, pe = s - timedelta(days=7), e - timedelta(days=7)
    elif unit == "week":
        ps = s - timedelta(days=7)
        pe = ps + days
    elif unit == "month":
        ps = _unit_before("month", s)
        pe = min(ps + days, s)
    else:
        ps, pe = _year_back(s), _year_back(e)
    if unit in ("day", "week"):
        ly_s, ly_e = s - timedelta(days=364), e - timedelta(days=364)
    elif unit == "month":
        ly_s, ly_e = _year_back(s), _year_back(e)
    else:
        ly_s, ly_e = None, None                  # the comparison already is the year before
    note = _edge_note(today=today, through=through, complete=complete, held_by=held_by, tables=tables,
                      fell_back=fell_back, asked_to=None)
    return RangeSpec(preset, s, e, ps, pe, ly_s, ly_e, period=unit, data_through=through, edge_note=note,
                     under_way=e < whole, fiscal_start_month=fiscal, **common)


def phrases(spec: RangeSpec) -> dict:
    """What the Briefing covers and what it is compared with, in words a reader checks against a
    calendar — ISO dates, never "last week", which is ambiguous the day after."""
    unit = EDGE_UNIT.get(spec.preset)
    if unit and spec.under_way:
        if unit == "week":
            covers = f"the week of {_d(spec.start)} so far, {_span(spec.start, spec.end)}"
            against = f"the same days of the week before, {_span(spec.previous_start, spec.previous_end)}"
        elif unit == "month":
            covers = f"{spec.start.strftime('%B %Y')} so far, {_span(spec.start, spec.end)}"
            against = (f"the same days of {spec.previous_start.strftime('%B')}, "
                       f"{_span(spec.previous_start, spec.previous_end)}")
        else:
            covers = f"{_year_words(spec.start)} so far, {_span(spec.start, spec.end)}"
            against = f"the same span a year earlier, {_span(spec.previous_start, spec.previous_end)}"
    elif spec.preset in PRESET_PERIOD or unit:
        from aughor.automations.temporal import PeriodWindow
        from aughor.knowledge import period_brief
        covers, against = period_brief.phrases(PeriodWindow(
            spec.period, spec.start, spec.end, spec.previous_start, spec.previous_end, spec.lag_days))
    elif spec.preset == "month_to_date":
        covers = f"{spec.start.strftime('%B %Y')} to date, {_span(spec.start, spec.end)}"
        against = f"the same days of {spec.previous_start.strftime('%B')}, {_span(spec.previous_start, spec.previous_end)}"
    elif spec.preset == "year_to_date":
        covers = f"the year to date, {_span(spec.start, spec.end)}"
        against = f"the same span a year earlier, {_span(spec.previous_start, spec.previous_end)}"
    else:
        weeks = (spec.start - spec.previous_start).days // 7
        covers = f"{_span(spec.start, spec.end)} ({spec.days} day{'s' if spec.days != 1 else ''})"
        against = (f"the same {spec.days} days {weeks} week{'s' if weeks != 1 else ''} earlier, "
                   f"{_span(spec.previous_start, spec.previous_end)}")
    last_year = (f"a year earlier, {_span(spec.last_year_start, spec.last_year_end)}"
                 if spec.last_year_start and spec.last_year_end else None)
    return {"covers": covers, "compared_with": against, "last_year": last_year}


def compared_word(spec: RangeSpec) -> str:
    """What the range is compared with, short enough to follow "higher than" on a cockpit's card.
    ``phrases`` says it in full, with its dates; a card carries the full phrase as its title."""
    p = PRESET_PERIOD.get(spec.preset) or EDGE_UNIT.get(spec.preset)
    if spec.under_way and p == "week":
        return "the same days of the week before"
    if spec.under_way and p == "month":
        return f"the same days of {spec.previous_start.strftime('%B')}"
    if spec.under_way and p == "year":
        return "the same span a year earlier"
    if p == "month":
        same_year = spec.previous_start.year == spec.start.year
        return spec.previous_start.strftime("%B" if same_year else "%B %Y")
    if p == "year":
        return str(spec.previous_start.year)
    if p == "week":
        return "the week before"
    if p == "day":
        return "the same weekday a week earlier"
    if spec.preset == "month_to_date":
        return f"the same days of {spec.previous_start.strftime('%B')}"
    if spec.preset == "year_to_date":
        return "the same span a year earlier"
    return "the span before it"


def resolve_range(preset: Optional[str] = None, *, start: Optional[date] = None,
                  end: Optional[date] = None, today: date, lag_days: int = 1,
                  lag_source: str = "default", still_moving: tuple = (),
                  fiscal_start_month: int = 1, edge: Optional[dict] = None) -> tuple[Optional[RangeSpec], str]:
    """The range a Briefing reads, or ``(None, why)``. ``end`` is the LAST day, inclusive, as a
    calendar picks it; the spec's ``end`` is exclusive. Pure: no clock, no store.

    ``edge`` is ``data_edge``'s reading — where the data ends. The current and last periods are read
    to it; a custom range that runs past it is cut there and says so."""
    from aughor.automations.temporal import clamp_lag, complete_period

    preset = preset or ("custom" if start else "")
    if preset not in PRESETS:
        return None, f"a range is one of {', '.join(PRESETS)}"
    lag = clamp_lag(lag_days)
    anchor = today - timedelta(days=lag)          # the newest settled day
    common = dict(as_of=today, lag_days=lag, lag_source=lag_source, still_moving=tuple(still_moving))
    fiscal = fiscal_start_month if 1 <= int(fiscal_start_month or 1) <= 12 else 1
    edge = edge or {}
    through = edge.get("through")
    if preset in EDGE_PRESETS:
        return _edge_range(preset, today=today, through=through, held_by=tuple(edge.get("held_by") or ()),
                           tables=dict(edge.get("tables") or {}), fiscal=fiscal, common=common), ""
    if preset in PRESET_PERIOD:
        w = complete_period(PRESET_PERIOD[preset], today, lag, fiscal_start_month=fiscal_start_month)
        if w.period == "year":
            ly_start, ly_end = None, None          # the comparison already is the year before
        elif w.period == "month":
            ly_start, ly_end = _year_back(w.start), _year_back(w.end)
        else:
            ly_start, ly_end = w.start - timedelta(days=364), w.end - timedelta(days=364)
        return RangeSpec(preset, w.start, w.end, w.previous_start, w.previous_end, ly_start, ly_end,
                         period=w.period, **common), ""
    if preset == "month_to_date":
        s, e = anchor.replace(day=1), anchor + timedelta(days=1)
        ps = (s - timedelta(days=1)).replace(day=1)
        pe = min(ps + (e - s), s)
        return RangeSpec(preset, s, e, ps, pe, _year_back(s), _year_back(e), **common), ""
    if preset == "year_to_date":
        month = fiscal_start_month if 1 <= int(fiscal_start_month or 1) <= 12 else 1
        s = date(anchor.year, month, 1)
        if s > anchor:
            s = date(anchor.year - 1, month, 1)
        e = anchor + timedelta(days=1)
        return RangeSpec(preset, s, e, _year_back(s), _year_back(e), None, None, **common), ""
    # custom
    if start is None or end is None:
        return None, "a custom range needs a first and a last day"
    if end < start:
        return None, "the range ends before it starts"
    if start > today:
        return None, "the range is in the future: there is no data for it yet"
    e = end + timedelta(days=1)
    if (e - start).days > MAX_RANGE_DAYS:
        return None, f"the range is longer than {MAX_RANGE_DAYS} days — read it as years"
    note = ""
    if through is not None:
        # Days whose data has not arrived are not read: a range asked to today against a whole
        # comparison reads part of a day against a whole one.
        complete = min(through, today - timedelta(days=1))
        if start <= complete < end:
            note = _edge_note(today=today, through=through, complete=complete,
                              held_by=tuple(edge.get("held_by") or ()), tables=dict(edge.get("tables") or {}),
                              fell_back=None, asked_to=end)
            e = complete + timedelta(days=1)
    weeks = max(1, -(-(e - start).days // 7))      # ceil: the whole weeks that clear the range
    shift = timedelta(days=7 * weeks)
    year = timedelta(days=364)
    return RangeSpec("custom", start, e, start - shift, e - shift, start - year, e - year,
                     data_through=through, edge_note=note, **common), ""


def range_block(spec: RangeSpec) -> dict:
    """The block a range Briefing carries — what §3.27's period block carries, plus the range's
    own key, its last-year comparison and its as-of."""
    words = phrases(spec)
    return {"period": spec.period, "key": spec.key, "preset": spec.preset,
            "label": LABEL[spec.preset], "start": _d(spec.start), "end": _d(spec.end),
            "last_day": _d(spec.last_day), "previous_start": _d(spec.previous_start),
            "previous_end": _d(spec.previous_end),
            "last_year_start": _d(spec.last_year_start) if spec.last_year_start else None,
            "last_year_end": _d(spec.last_year_end) if spec.last_year_end else None,
            "as_of": _d(spec.as_of), "lag_days": spec.lag_days, "lag_source": spec.lag_source,
            "still_moving": list(spec.still_moving), "covers": words["covers"],
            "compared_with": words["compared_with"], "last_year_label": words["last_year"],
            "data_through": _d(spec.data_through) if spec.data_through else None,
            "edge_note": spec.edge_note, "under_way": spec.under_way,
            "measured": [], "unmeasured": []}


# ── measuring a range ──────────────────────────────────────────────────────────────────────

def _norm(s: str) -> str:
    return "".join(ch for ch in str(s or "").lower() if ch.isalnum())


def _rel(cur: Optional[float], prev: Optional[float]) -> Optional[float]:
    if cur is None or prev in (None, 0):
        return None
    return (cur - prev) / abs(prev)


def equal_age(metric: Any, status: str) -> dict:
    """Is this figure's comparison read at the same age as the figure itself? (BR-6)

    `RangeSpec.windows` gives every comparison its OWN as-of — August read on 15 September is
    14 days old, so July is read at 14 days too — and `metric_time.measure_sql` bounds a
    COHORT's outcome to that as-of. Proven 2026-09-27: all three windows come back 14 days old.
    So a cohort is already compared at equal age, and a settled figure needs no bound at all:
    both periods have stopped moving.

    What is left is the case §3.48 names and nothing said out loud. A **flow** figure that is
    still provisional — theLook restates its recent days for eight — is compared with a period
    that has finished restating. Its rows arrive late with no outcome date, so there is nothing
    to bound; the honest reading needs BR-8's daily readings, which do not exist yet. Until
    then the comparison SAYS it is not at equal age rather than letting a reader take a
    difference of maturity for a move. The number is still shown: a stated caveat beside a
    figure is worth more than a blank.
    """
    if status == "final":
        return {"equal": True, "why": ""}
    kind = str(_get_kind(metric) or "")
    if kind == "cohort":
        return {"equal": True, "why": ""}
    label = getattr(metric, "label", "") or getattr(metric, "name", "") or "this figure"
    return {"equal": False, "why": (
        f"{label} is still {'to date' if status == 'to_date' else 'provisional'}, and what it is "
        "compared with has settled — part of any difference is the difference in age, not a move. "
        "Comparing them at the same age needs a daily reading this source does not keep yet.")}


def _get_kind(metric: Any) -> str:
    return str(getattr(metric, "time_kind", "") or "")


def governed_metrics(conn_id: str, schema: Optional[str] = None) -> list:
    """The connection's approved metrics in reading order (§6 item 43(d)): sales first, profit
    last, the industry's own order within. Ordered BEFORE any cap, so a connection past it keeps
    its headline end — and every reader that caps (the measured table, the predictions) caps
    the same list.

    ``schema`` — the dataset in view: its own definitions and the ones promoted to every dataset,
    never another dataset's. The Cockpit of the workspace's Uber data measured Daily Gross Revenue,
    which reads the `main` dataset, beside the rides (2026-10-07)."""
    from aughor.briefing.reading_order import industry_reading, ordered
    from aughor.semantic.metrics import list_metrics

    order, statement = industry_reading(conn_id)
    return ordered([m for m in list_metrics(connection_id=conn_id, schema_name=schema or None)
                    if m.status == "approved" and m.connection == conn_id],
                   order, statement)


def statement_lines(conn_id: str) -> Callable[[Any], Optional[dict]]:
    """The income-statement line a governed metric reads on, as ``{"line", "label"}`` — or None for
    every metric when the connection's industry declares no statement."""
    from aughor.briefing.reading_order import STATEMENT_LINES, industry_reading, line_of

    order, statement = industry_reading(conn_id)

    def line(m: Any) -> Optional[dict]:
        got = line_of(getattr(m, "name", "") or "", getattr(m, "label", "") or "", order, statement)
        return {"line": got, "label": STATEMENT_LINES[got]} if got else None
    return line


def data_ends(m: Any, run_sql: Callable[[str], tuple], dialect: str) -> Optional[date]:
    """The last day a metric's own date has rows — one statement over the table its date is on — or
    None when it cannot be read."""
    from sqlglot import exp

    from aughor.semantic import metric_time as mt
    from aughor.semantic.metric_statement import split_grain

    table, col = split_grain(getattr(m, "time_column", None))
    table = table or next(iter(mt.tables_read(m)), None)
    if not (table and col):
        return None
    try:
        sql = (exp.select(exp.alias_(exp.Max(this=mt._day(exp.column(col))), "last_day"))
               .from_(mt._table(table, dialect)).sql(dialect=dialect))
        _cols, rows, error = run_sql(sql)
    except Exception as exc:  # noqa: BLE001 — not known is said by the caller, never guessed
        from aughor.kernel.errors import tolerate
        tolerate(exc, "a metric's last day of data could not be read", counter="briefing.range.data_ends")
        return None
    if error or not rows:
        return None
    first = rows[0]
    cells = list(first.values()) if isinstance(first, dict) else list(first)
    return mt._as_date(cells[0]) if cells else None


#: Where a connection's data ends, per (connection, dataset, day), kept ten minutes: a page asks for
#: the figures, the expected bands and a trend in a breath, and each resolves the same range.
_EDGE_CACHE: dict[tuple, tuple[float, dict]] = {}
_EDGE_TTL_S = 10 * 60
#: A table whose data ends this long before the newest is not holding the edge back — it stopped,
#: and its metric reads its own last range instead (``anchored_spec``), saying so.
STOPPED_DAYS = 31


def data_edge(conn_id: str, schema: Optional[str] = None, *, today: date,
              runner: Optional[Callable[[], Any]] = None) -> dict:
    """Where the data ends: ``{"through", "held_by", "tables", "why"}``.

    ``through`` is the newest day EVERY measured table has rows for — the last day of each approved
    metric's own date column (a level is read as it stands, so it does not count), the earliest of
    them, ignoring a table that stopped long before the rest. ``held_by`` names the tables that end
    there, ``tables`` each table's own last day. None (with ``why``) when nothing could be read.
    One statement per table, uncached by the result cache: an edge read from yesterday's cache is
    the stale answer this exists to replace."""
    import time as _t

    from aughor.semantic import metric_time as mt
    from aughor.semantic.metric_statement import split_grain

    key = (conn_id, schema or "", today.isoformat())
    hit = _EDGE_CACHE.get(key)
    if hit and _t.monotonic() - hit[0] < _EDGE_TTL_S:
        return hit[1]
    metrics = [m for m in governed_metrics(conn_id, schema) if mt.declared(m) and m.time_kind != "stock"]
    if not metrics:
        return {"through": None, "held_by": [], "tables": {}, "why": "no approved metric names a date"}
    from aughor.knowledge import period_brief

    lasts: dict[str, Optional[date]] = {}
    try:
        with (runner or (lambda: period_brief.connection_runner(conn_id, cached=False)))() as (run_sql, dialect):
            for m in metrics:
                table, _col = split_grain(getattr(m, "time_column", None))
                table = mt.bare_name(table or next(iter(mt.tables_read(m)), "") or "")
                if table and table not in lasts:
                    lasts[table] = data_ends(m, run_sql, dialect)
    except Exception as exc:  # noqa: BLE001 — not known is said, never guessed
        from aughor.kernel.errors import tolerate
        tolerate(exc, "where the data ends could not be read", counter="briefing.range.edge")
        return {"through": None, "held_by": [], "tables": {},
                "why": f"the connection could not be opened ({type(exc).__name__})"}
    read = {t: min(d, today) for t, d in lasts.items() if d is not None}
    if not read:
        out = {"through": None, "held_by": [], "tables": {}, "why": "no table's last day could be read"}
    else:
        newest = max(read.values())
        live = {t: d for t, d in read.items() if (newest - d).days <= STOPPED_DAYS}
        through = min(live.values())
        out = {"through": through, "held_by": sorted(t for t, d in live.items() if d == through),
               "tables": live, "why": ""}
    _EDGE_CACHE[key] = (_t.monotonic(), out)
    return out


def anchored_spec(spec: RangeSpec, last_day: date) -> Optional[RangeSpec]:
    """The same kind of range, ending where a metric's data does: the month, week, day or year that
    holds its last day, or a custom range of the same length ending there. None when the data does
    not end before the range — then the range itself is the right one to read."""
    if last_day >= spec.start:
        return None
    lag = spec.lag_days
    if spec.preset in EDGE_PRESETS:
        # As if read the day after its data ends: the period holding that day, or the one before.
        from dataclasses import replace
        new, _ = resolve_range(spec.preset, today=last_day + timedelta(days=1), lag_days=lag,
                               lag_source=spec.lag_source, fiscal_start_month=spec.fiscal_start_month,
                               edge={"through": last_day})
        return replace(new, as_of=spec.as_of, edge_note="") if new else None
    if spec.preset == "custom":
        new, _ = resolve_range("custom", start=last_day - (spec.end - spec.start) + timedelta(days=1),
                               end=last_day, today=spec.as_of, lag_days=lag, lag_source=spec.lag_source)
        return new
    if spec.preset in ("month_to_date", "year_to_date"):
        fiscal = spec.start.month if spec.preset == "year_to_date" else 1
        new, _ = resolve_range(spec.preset, today=last_day + timedelta(days=lag), lag_days=lag,
                               lag_source=spec.lag_source, fiscal_start_month=fiscal)
        return new
    period = PRESET_PERIOD.get(spec.preset)
    fiscal = spec.start.month if period == "year" else 1
    # The period that holds the last day ends at `ends`; read as of its own last day, it is complete.
    if period == "day":
        ends = last_day + timedelta(days=1)
    elif period == "week":
        ends = last_day - timedelta(days=last_day.weekday()) + timedelta(days=7)
    elif period == "month":
        ends = (last_day.replace(day=1) + timedelta(days=32)).replace(day=1)
    else:
        ends = date(last_day.year + (1 if last_day.month >= fiscal else 0), fiscal, 1)
    new, _ = resolve_range(spec.preset, today=ends - timedelta(days=1) + timedelta(days=lag), lag_days=lag,
                           lag_source=spec.lag_source, fiscal_start_month=fiscal)
    return new


def _unsettled(m: Any, spec: RangeSpec) -> bool:
    """Whether a figure reads a table the platform has not yet seen stop changing — by the tables its
    statement reads, which a statement's empty `tables` field never named."""
    from aughor.semantic import metric_time as mt
    return bool({mt.bare_name(t) for t in mt.tables_read(m)} & set(spec.still_moving))


def measure_range(conn_id: str, spec: RangeSpec, *, run_sql: Callable[[str], tuple], dialect: str,
                  north_stars: Optional[list] = None, schema: Optional[str] = None) -> dict:
    """Every approved metric measured for the range and its comparisons. Returns ``{"measured",
    "unmeasured"}``; every approved metric lands in exactly one list, and a north star with no
    approved definition is named in ``unmeasured`` with that reason.

    A metric whose data ENDED before the range is read over the same kind of range at its data's
    end, and says so (``anchored``) — a dataset that stopped in 2024 reads its last month, never a
    blank in every preset (the user, 2026-10-07: *"no static or stale metrics"*). A range with no
    rows is never a figure: a count over it answers 0, and that 0 was shown as measured."""
    from aughor.knowledge.period_brief import partial_span
    from aughor.semantic import metric_time as mt

    said = mt.ensure_dates(conn_id, run_sql=run_sql, dialect=dialect, today=spec.as_of)
    governed = governed_metrics(conn_id, schema)
    approved, over_cap = governed[:MAX_METRICS], governed[MAX_METRICS:]
    line_of = statement_lines(conn_id)
    windows = spec.windows()
    measured: list[dict] = []
    unmeasured: list[dict] = []
    for m in approved:
        name = m.label or m.name
        if not mt.declared(m):
            unmeasured.append({"name": name, "reason": said.get(m.name) or "its dates are not set"})
            continue
        rows, why = mt.run_measure(m, windows, run_sql, dialect=dialect)
        if why:
            unmeasured.append({"name": name, "reason": why})
            continue
        got = {r["window"]: r for r in rows}
        cur = got.get("current")
        read, at, anchored = spec, windows, None
        if read_value(cur) is None and m.time_kind != "stock":
            last = data_ends(m, run_sql, dialect)
            moved = anchored_spec(spec, last) if last is not None else None
            if moved is not None:
                rows, why = mt.run_measure(m, moved.windows(), run_sql, dialect=dialect)
                got = {r["window"]: r for r in rows} if not why else {}
                if read_value(got.get("current")) is not None:
                    read, at, cur = moved, moved.windows(), got.get("current")
                    words = phrases(moved)
                    anchored = {"start": _d(moved.start), "end": _d(moved.end), "data_ends": _d(last),
                                "covers": words["covers"], "compared_with": words["compared_with"],
                                "last_year_label": words["last_year"],
                                "why": (f"its data ends {_d(last)}, before this range — this is "
                                        f"{words['covers']}, the latest it covers")}
            if anchored is None:
                reason = (f"its data ends {_d(last)}, before this range" if last is not None and last < spec.start
                          else "its data has no rows in this range")
                unmeasured.append({"name": name, "reason": reason})
                continue
        elif cur is None or cur["value"] is None:
            unmeasured.append({"name": name, "reason": "its data has no rows in this range"})
            continue
        slack = _slack(read.days)
        prev, ly = got.get("previous"), got.get("last_year")
        cur_partial = (None if m.time_kind == "stock"
                       else partial_span(cur["first"], cur["last"], read.start, read.end, slack))
        prev_partial = (None if (prev is None or prev["value"] is None or m.time_kind == "stock")
                        else partial_span(prev["first"], prev["last"], read.previous_start, read.previous_end, slack))
        pv = read_value(prev) if m.time_kind != "stock" else (prev["value"] if prev else None)
        lv = read_value(ly) if m.time_kind != "stock" else (ly["value"] if ly else None)
        windows_read = at
        measured.append({
            "name": name, "metric": m.name, "unit": m.unit or "", "time_kind": m.time_kind,
            "time_source": m.time_source, "confirmed": bool(m.time_confirmed_by),
            "current": cur["value"], "previous": pv, "last_year": lv,
            "rel": None if (cur_partial or prev_partial) else _rel(cur["value"], pv),
            "rel_last_year": None if cur_partial else _rel(cur["value"], lv),
            "status": mt.figure_status(m, windows_read[0], as_of=read.as_of, lag_days=read.lag_days,
                                       unsettled=_unsettled(m, read)),
            "current_partial": cur_partial, "previous_partial": prev_partial,
            # BR-6 — said, never implied: a provisional flow figure against a settled comparison
            # is not a fair move, and the reader is told so beside the number.
            "equal_age": equal_age(m, mt.figure_status(
                m, windows_read[0], as_of=read.as_of, lag_days=read.lag_days,
                unsettled=_unsettled(m, read))),
            "sql": mt.measure_sql(m, windows_read, dialect=dialect)[0] or "",
            "anchored": anchored,
            "line": line_of(m),
        })
    # A metric the CAP cut says the cap cut it. Measured 2026-09-27: theLook had ten approved
    # definitions against a cap of eight, and the two it dropped fell through to the north-star
    # loop below — which sees only that the name is unaccounted for and reports "no approved
    # definition; approve one in the Semantic Layer", about metrics that had just been approved
    # there. A reader who follows that instruction finds the work already done and no way to
    # learn why the figure is missing. Named here first, so the loop below never sees them.
    for m in over_cap:
        unmeasured.append({"name": m.label or m.name, "metric": m.name,
                           "reason": (f"past this Briefing's cap of {MAX_METRICS} headline metrics — "
                                      "it is approved and governed, and measuring it needs the cap "
                                      "raised, not a definition")})
    # `seen` reads the WHOLE governed set, not the capped slice, for the same reason.
    seen = {_norm(m.name) for m in governed} | {_norm(m.label) for m in governed}
    for ns in north_stars or []:
        ns_name = ns.get("name") if isinstance(ns, dict) else getattr(ns, "name", "")
        if ns_name and _norm(ns_name) not in seen:
            unmeasured.append({"name": ns_name, "reason": "no approved definition; approve one in the "
                                                          "Semantic Layer to measure it"})
    return {"measured": measured, "unmeasured": unmeasured}


_STATUS_WORDS = {
    "provisional": "provisional — its newest days are still settling",
    "to_date": "to date — the range is still under way",
}


def _share(v: Optional[float]) -> str:
    return "no value" if v is None else f"{v * 100:.1f}%"


def metric_line(m: dict, block: dict, currency_code: Optional[str]) -> str:
    """§3.27's sentence for a measured metric, with the figure's status when it is not final
    and the year-earlier comparison when there is one. A share (a cohort's 0..1 value) moves in
    POINTS: "15.1% to 14.3% (-0.8 pts)", never "a 6% improvement" of a rate."""
    from aughor.knowledge import period_brief

    if m.get("anchored"):
        # Read over its own data's last range — its sentence names THAT range, not the one asked for.
        a = m["anchored"]
        block = {**block, "covers": a["covers"], "compared_with": a["compared_with"],
                 "last_year_label": a.get("last_year_label")}
    share = m.get("unit") == "ratio 0..1"
    if share and m.get("rel") is not None and m.get("previous") is not None:
        pts = (m["current"] - m["previous"]) * 100
        line = (f"{m['name']} moved from {_share(m['previous'])} to {_share(m['current'])} "
                f"({pts:+.1f} pts): {block['covers']} against {block['compared_with']}.")
    else:
        line = period_brief.metric_line(m, block, currency_code)
    if m.get("last_year") is not None and m.get("rel_last_year") is not None and block.get("last_year_label"):
        if share:
            ly = _share(m["last_year"])
            change = f"{(m['current'] - m['last_year']) * 100:+.1f} pts"
        else:
            ly = period_brief._fmt(m["last_year"], m["name"], m.get("unit") or "", currency_code)
            change = f"{m['rel_last_year'] * 100:+.0f}%"
        line = line.rstrip(".") + f"; {ly} {block['last_year_label']} ({change})."
    status = m.get("status")
    if status in _STATUS_WORDS:
        why = ("its outcome is still arriving" if status == "provisional" and m.get("time_kind") == "cohort"
               else None)
        line = line.rstrip(".") + (f" — provisional: {why}." if why else f" — {_STATUS_WORDS[status]}.")
    return line


def range_findings(measured: list[dict], block: dict, currency_code: Optional[str]) -> list[dict]:
    """The measured metrics as candidate findings, shaped like explorer findings so the triage
    ranks them — the range's biggest move leads on its size."""
    import re
    out = []
    for m in measured:
        slug = re.sub(r"[^a-z0-9]+", "_", m["name"].lower()).strip("_")[:40]
        out.append({"id": f"range-move::{block['key']}::{slug}", "domain": "Key Metrics",
                    "angle": "Range", "finding": metric_line(m, block, currency_code),
                    "sql": m["sql"], "confidence": 0.8, "novelty": 3, "period_move": True,
                    "status": m.get("status")})
    return out


def _read_unit(time_kind: Optional[str], unit: str, values: list) -> str:
    """A cohort's value is the share of its rows whose outcome arrived: 0..1 by construction, so it
    reads as a percentage (theLook's return rate read 0.142857)."""
    if time_kind == "cohort" and all(v is None or 0 <= v <= 1 for v in values):
        return "ratio 0..1"
    return unit


def _figure_text(value: Optional[float], name: str, unit: str, currency: Optional[str]) -> Optional[str]:
    from aughor.knowledge import period_brief
    if unit == "ratio 0..1" and value is not None:
        return _share(value)
    return period_brief._fmt(value, name, unit, currency)


def say_figures(measured: list[dict], currency: Optional[str]) -> None:
    """Each measured figure worded once, in place: the screen shows the SAME text the lines and the
    narrator read, whichever door measured it."""
    for m in measured:
        m["declared_unit"] = m["unit"]
        m["unit"] = _read_unit(m.get("time_kind"), m["unit"], [m.get(k) for k in ("current", "previous", "last_year")])
        for k in ("current", "previous", "last_year"):
            m[f"{k}_text"] = _figure_text(m.get(k), m["name"], m["unit"], currency)


def _currency(profile: Any, workspace_id: Optional[str]) -> Optional[str]:
    from aughor.orgsettings import resolve_currency
    return resolve_currency(getattr(profile, "currency_code", None) or "", workspace_id)


def measured_block(conn_id: str, spec: RangeSpec, *, profile: Any = None, workspace_id: Optional[str] = None,
                   runner: Optional[Callable[[], Any]] = None, schema: Optional[str] = None) -> dict:
    """The range's approved metrics, measured, and nothing else — the Cockpit's default view (ROADMAP
    §6 item 43). The same measurement and the same wording a range Briefing carries, with no recipe
    section, no narrative and no model call."""
    from aughor.knowledge import period_brief

    block = range_block(spec)
    north = list(getattr(profile, "north_star_metrics", None) or []) if profile is not None else []
    try:
        with (runner or (lambda: period_brief.connection_runner(conn_id)))() as (run_sql, dialect):
            got = measure_range(conn_id, spec, run_sql=run_sql, dialect=dialect, north_stars=north,
                                schema=schema)
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the range measurement could not open the connection", counter="briefing.range.measure")
        return {**block, "unmeasured": [{"name": "headline metrics",
                                         "reason": f"the connection could not be opened ({type(exc).__name__})"}]}
    say_figures(got["measured"], _currency(profile, workspace_id))
    return {**block, **got}


#: How many ranges a metric's trend reads, the range itself included. A year reaches less far back.
TREND_RANGES = 8
TREND_YEARS = 4


def earlier_ranges(spec: RangeSpec, n: int) -> list[tuple[date, date]]:
    """The range and the ``n - 1`` before it, oldest first, as ``(start, end)`` with ``end`` exclusive.
    Each is stepped back the way the range's own comparison is: a month by a calendar month, a year
    by a year, anything else by the whole weeks between the range and its comparison — so a day is
    read against the same weekday."""
    monthly = spec.period == "month" or spec.preset == "month_to_date"
    yearly = spec.period == "year" or spec.preset == "year_to_date"
    whole_month = spec.period == "month" and not spec.under_way
    step = spec.start - spec.previous_start
    out = [(spec.start, spec.end)]
    s, e = spec.start, spec.end
    for _ in range(max(0, n - 1)):
        if yearly:
            s, e = _year_back(s), _year_back(e)
        elif monthly:
            before = (s - timedelta(days=1)).replace(day=1)
            # a whole month ends where the next begins; a month so far reads the same days of it
            s, e = before, (s if whole_month else min(before + (e - s), s))
        elif step.days > 0:
            s, e = s - step, e - step
        else:
            break
        out.append((s, e))
    return out[::-1]


def later_spec(spec: RangeSpec) -> Optional[RangeSpec]:
    """The range after this one, of the same kind — the next day, week, month or year; a custom range
    moved on by its own length — read at the same age as this one. None for a range to date: its next
    reading is the same range, longer, not a new one. Its comparison is this range's own step back, so
    ``earlier_ranges`` walks from it exactly as it walks from this one."""
    from dataclasses import replace
    if spec.preset in ("month_to_date", "year_to_date") or spec.under_way:
        return None
    start = spec.end
    if spec.period == "year":
        try:
            end = start.replace(year=start.year + 1)
        except ValueError:           # 29 February
            end = start.replace(year=start.year + 1, day=28)
    elif spec.period == "month":
        end = (start + timedelta(days=32)).replace(day=1)
    else:
        end = start + (spec.end - spec.start)
    step = spec.start - spec.previous_start
    return replace(spec, start=start, end=end, previous_start=start - step, previous_end=end - step,
                   last_year_start=None, last_year_end=None, as_of=end + (spec.as_of - spec.end),
                   edge_note="")


def read_value(row: Optional[dict]) -> Optional[float]:
    """A window's value, or None when it is not a reading: no row came back for it, or the rows it was
    cut from number none. A count over an empty window answers 0 where a sum answers nothing; neither
    is a figure anybody measured, and a trend or a band that took the 0 would be drawn from it."""
    if not row or row.get("value") is None or not int(row.get("n") or 0):
        return None
    return row["value"]


def metric_trend(conn_id: str, spec: RangeSpec, metric_name: str, *, profile: Any = None,
                 workspace_id: Optional[str] = None, runner: Optional[Callable[[], Any]] = None,
                 schema: Optional[str] = None) -> dict:
    """One approved metric read for the range and the ranges before it, with how it is defined and
    dated — what a reader opens a figure for. One warehouse statement and no model call. A cohort's
    earlier ranges are read at the same age as the range, as its comparison is; a flow's are read as
    their rows stand today, and each range still settling says so. A metric that cannot be read says
    why and carries no series."""
    from aughor.knowledge import period_brief
    from aughor.knowledge.period_brief import partial_span
    from aughor.semantic import metric_time as mt
    from aughor.semantic.metrics import list_metrics

    def approved():
        return next((x for x in list_metrics(connection_id=conn_id, schema_name=schema or None)
                     if x.name == metric_name and x.status == "approved" and x.connection == conn_id), None)

    def describe(m) -> dict:
        return {"metric": m.name, "found": True, "name": m.label or m.name, "unit": m.unit or "",
                "definition": m.sql, "tables": list(m.tables), "filters": list(m.filters),
                "caveats": m.caveats or "", "owner": m.owner or "", "approved_by": m.approved_by or "",
                "version": m.version, "time_kind": m.time_kind, "time_source": m.time_source or "",
                "confirmed": bool(m.time_confirmed_by), "series": [], "why": ""}

    m = approved()
    if m is None:
        return {"metric": metric_name, "found": False, "series": [],
                "why": "no approved metric by that name is on this connection"}
    yearly = spec.period == "year" or spec.preset == "year_to_date"
    age = spec.as_of - spec.end
    windows = [Window(f"r{i}", s, e, as_of=e + age)
               for i, (s, e) in enumerate(earlier_ranges(spec, TREND_YEARS if yearly else TREND_RANGES))]
    try:
        with (runner or (lambda: period_brief.connection_runner(conn_id)))() as (run_sql, dialect):
            # the same first step a Briefing's measurement takes: a metric's dates are set by rule
            said = mt.ensure_dates(conn_id, run_sql=run_sql, dialect=dialect, today=spec.as_of)
            m = approved() or m
            if not mt.declared(m):
                return {**describe(m), "why": said.get(m.name) or "its dates are not set"}
            rows, why = mt.run_measure(m, windows, run_sql, dialect=dialect)
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "a metric's trend could not open the connection", counter="briefing.range.trend")
        rows, why = [], f"the connection could not be opened ({type(exc).__name__})"
    about, name = describe(m), m.label or m.name
    if why:
        return {**about, "why": why}
    got = {r["window"]: r for r in rows}
    values = [read_value(got.get(w.label)) for w in windows]
    unit = _read_unit(m.time_kind, m.unit or "", values)
    currency, slack = _currency(profile, workspace_id), _slack(spec.days)
    settled_by = spec.as_of - timedelta(days=max(int(spec.lag_days or 1), 1))
    series = []
    for w, v in zip(windows, values):
        row = got.get(w.label)
        partial = (None if (row is None or v is None or m.time_kind == "stock")
                   else partial_span(row["first"], row["last"], w.start, w.end, slack))
        series.append({"start": _d(w.start), "last_day": _d(w.last_day), "label": _span(w.start, w.end),
                       "value": v, "value_text": _figure_text(v, name, unit, currency) if v is not None else None,
                       "partial": partial, "current": w is windows[-1],
                       # inside the days this source keeps changing: its figure may still move
                       "settling": w.last_day > settled_by})
    # Only a cohort's comparisons are bounded to an equal age (its outcomes, by each window's
    # as-of). A flow or a level is read as its rows stand today, so a range still settling is
    # not at the age of the ones before it — and the drawer said they all were (2026-10-08).
    return {**about, "unit": unit, "series": series, "same_age": m.time_kind == "cohort",
            "lag_days": spec.lag_days}


def build_range_briefing(conn_id: str, spec: RangeSpec, *, scope_key: str, domain_data: dict,
                         profile: Any, workspace_id: Optional[str] = None,
                         col_types: Optional[dict] = None, force_refresh: bool = False,
                         runner: Optional[Callable[[], Any]] = None) -> dict:
    """The Briefing for one range. Cached per scope and range key; rebuilt when the window or
    the lag moves. ``runner`` opens ``(run_sql, dialect)``; it defaults to the connection's own."""
    from aughor.knowledge import period_brief
    from aughor.knowledge.briefing import get_briefing

    from aughor.briefing.recipes import SECTIONS, recipe_for

    block = {**range_block(spec), "recipe": recipe_for(spec.preset),
             "sections": list(SECTIONS[recipe_for(spec.preset)])}
    north = list(getattr(profile, "north_star_metrics", None) or []) if profile is not None else []
    currency = _currency(profile, workspace_id)

    def measure() -> dict:
        from aughor.briefing import recipes
        try:
            with (runner or (lambda: period_brief.connection_runner(conn_id)))() as (run_sql, dialect):
                # The dataset in view rides the scope key (`conn:schema`), as every caller writes it.
                got = measure_range(conn_id, spec, run_sql=run_sql, dialect=dialect, north_stars=north,
                                    schema=(scope_key.split(":", 1)[1] if ":" in scope_key else None))
                # Arc BR-4: the recipe's own sections — what moved, why, the Day's early read …
                try:
                    extra = recipes.apply(conn_id, spec, got, run_sql=run_sql, dialect=dialect,
                                          domain_data=domain_data, currency=currency, block=block)
                except Exception as exc:  # noqa: BLE001 — a section that fails never costs the figures
                    from aughor.kernel.errors import tolerate
                    tolerate(exc, "a recipe section failed; the Briefing keeps its measured figures",
                             counter="briefing.range.recipe")
                    extra = {"recipe_error": f"its recipe sections could not be built ({type(exc).__name__})"}
        except Exception as exc:  # noqa: BLE001
            from aughor.kernel.errors import tolerate
            tolerate(exc, "the range measurement could not open the connection",
                     counter="briefing.range.measure")
            return {"findings": [], "measured": [],
                    "unmeasured": [{"name": "headline metrics",
                                    "reason": f"the connection could not be opened ({type(exc).__name__})"}]}
        say_figures(got["measured"], currency)
        candidates = extra.pop("candidates", {})
        return {**got, **extra, "findings": range_findings(got["measured"], block, currency),
                "candidates": candidates}

    candidates = period_brief.findings_in_window(domain_data, spec)
    alerts = period_brief.alert_findings(conn_id, spec)
    if alerts:
        candidates = {**candidates, "Alerts": alerts + list(candidates.get("Alerts", []))}
    return get_briefing(
        connection_id=conn_id, domain_data=candidates, patterns=[],
        force_refresh=force_refresh, scope_key=scope_key, profile=profile,
        workspace_id=workspace_id, col_types=col_types, period=block, period_measure=measure,
        period_note_today=spec.as_of)


def resolve_for(conn_id: str, preset: Optional[str] = None, *, start: Optional[date] = None,
                end: Optional[date] = None, workspace_id: Optional[str] = None,
                today: Optional[date] = None, schema: Optional[str] = None) -> tuple[Optional[RangeSpec], str]:
    """``resolve_range`` with this connection's lag (idea 4, honest about unsettled tables), the
    organisation's fiscal year and — for a current or last period, or a custom range reaching the
    last month — where the data ends (``data_edge``)."""
    from aughor.knowledge.period_brief import resolve_window

    today = today or datetime.now(timezone.utc).date()
    _w, lag_source, moving = resolve_window(conn_id, "day", workspace_id=workspace_id, today=today)
    lag = (today - _w.start).days          # the day window starts at the newest settled day
    fiscal = 1
    try:
        from aughor.orgsettings import effective_settings
        fiscal = int(getattr(effective_settings(workspace_id), "fiscal_year_start_month", 1) or 1)
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "org settings unreadable; a year range is the calendar year",
                 counter="briefing.range.fiscal")
    edge = None
    if preset in EDGE_PRESETS or (end is not None and (today - end).days <= STOPPED_DAYS):
        edge = data_edge(conn_id, schema, today=today)
    return resolve_range(preset, start=start, end=end, today=today, lag_days=lag,
                         lag_source=lag_source, still_moving=tuple(moving), fiscal_start_month=fiscal,
                         edge=edge)


# ── the send (Arc BR-5) ────────────────────────────────────────────────────────────────────

def sheet_lines(brief: dict, currency_code: Optional[str] = None) -> list[tuple[str, list[str]]]:
    """A range Briefing as the sections a send departs with, in order: its measured figures
    with their status, what moved, the early read, what was not measured (one line per reason),
    the alerts and records it cited, then the narrative. Each line is judged on its own."""
    from aughor.briefing import recipes

    block = brief.get("period") or {}
    currency = currency_code or brief.get("currency_code")
    sections: list[tuple[str, list[str]]] = []
    measured = [metric_line(m, block, currency) for m in block.get("measured") or []]
    if measured:
        sections.append(("measured", measured))
    moves = [recipes.move_line(c, block, currency) for c in block.get("moves") or []]
    if moves:
        sections.append(("moves", moves))
    early = block.get("early") or {}
    if early.get("figures"):
        figs = "; ".join(f"{f['name']} {f.get('value_text') or f['value']}" for f in early["figures"])
        sections.append(("early", [f"Still settling (early), {early['start']} to {early['end']}: {figs}."]))
    by_reason: dict[str, list[str]] = {}
    for u in block.get("unmeasured") or []:
        by_reason.setdefault(u["reason"], []).append(u["name"])
    if by_reason:
        sections.append(("unmeasured", [f"Not measured: {', '.join(n)} — {r}." for r, n in by_reason.items()]))
    cited = [(c.get("domain"), str(c.get("finding") or "").strip())
             for c in brief.get("citations") or [] if str(c.get("finding") or "").strip()]
    alerts = [text for domain, text in cited if domain == "Alerts"]
    if alerts:
        sections.append(("alerts", alerts))
    records = [text for domain, text in cited if domain not in ("Alerts", "Key Metrics", "What moved")]
    if records:
        sections.append(("records", records))
    paragraphs = [p.strip() for p in str(brief.get("narrative") or "").split("\n\n") if p.strip()]
    if paragraphs:
        sections.append(("narrative", paragraphs))
    return sections


def fresh_measurement(conn_id: str, brief: dict, *, runner: Optional[Callable[[], Any]] = None):
    """Law 1's basis for a range send: every query the Briefing measured with — the headline
    metrics, each segment breakdown, the early read — RE-RUN now, never the values it was
    written from, with the changes between each figure and its comparison (a line that says
    "+$2,805" states a difference of two measured values, and the difference is measured too)."""
    from aughor.govern.departure import Measurement
    from aughor.knowledge import period_brief

    def _num(v) -> Optional[float]:
        try:
            return None if v is None else float(str(v).replace(",", "")) if isinstance(v, str) else float(v)
        except (TypeError, ValueError):
            return None

    block = brief.get("period") or {}
    sqls = {m.get("sql") for m in block.get("measured") or []}
    sqls |= {c.get("sql") for c in block.get("moves") or []}
    sqls |= {f.get("sql") for f in (block.get("early") or {}).get("figures") or []}
    values: list[float] = []
    try:
        with (runner or (lambda: period_brief.connection_runner(conn_id, cached=False)))() as (run_sql, _d):
            for sql in sorted(s for s in sqls if s):
                cols, rows, error = run_sql(sql)
                if error:
                    continue
                names = [str(c).lower() for c in cols or []]
                vi = names.index("_v") if "_v" in names else None
                gi = names.index("_g") if "_g" in names else None
                wi = names.index("_w") if "_w" in names else 0
                if vi is None:
                    continue
                by: dict = {}
                for r in rows or []:
                    cells = list(r.values()) if isinstance(r, dict) else list(r)
                    v = _num(cells[vi])
                    if v is None:
                        continue
                    values.append(v)
                    by.setdefault(cells[gi] if gi is not None else None, {})[str(cells[wi])] = v
                for w in by.values():
                    for other in ("previous", "last_year"):
                        if "current" in w and other in w:
                            values += [w["current"] - w[other], abs(w["current"] - w[other])]
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the range's queries could not be re-run at departure; its lines hold",
                 counter="briefing.range.remeasure")
    return Measurement(source=f"the {str(block.get('label', '')).lower()} briefing's queries",
                       values=values,
                       measured_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                       as_of=str(block.get("last_day") or ""),
                       definition="each approved metric compiled for the range from its definition")
