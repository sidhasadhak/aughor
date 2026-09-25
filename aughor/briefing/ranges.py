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

#: The presets a range control offers, in its order.
PRESETS = ("yesterday", "last_week", "last_month", "last_year", "month_to_date",
           "year_to_date", "custom")
#: A named preset is §3.27's period.
PRESET_PERIOD = {"yesterday": "day", "last_week": "week", "last_month": "month", "last_year": "year"}
PERIOD_PRESET = {v: k for k, v in PRESET_PERIOD.items()}
LABEL = {"yesterday": "Daily", "last_week": "Weekly", "last_month": "Monthly", "last_year": "Yearly",
         "month_to_date": "Month-to-date", "year_to_date": "Year-to-date", "custom": "Custom range"}
#: The longest custom range; a longer question is the Year recipe's, or Ask's.
MAX_RANGE_DAYS = 3 * 366
#: The most headline metrics measured per Briefing — the standing Briefing's own cap.
MAX_METRICS = 8
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


def phrases(spec: RangeSpec) -> dict:
    """What the Briefing covers and what it is compared with, in words a reader checks against a
    calendar — ISO dates, never "last week", which is ambiguous the day after."""
    if spec.preset in PRESET_PERIOD:
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


def resolve_range(preset: Optional[str] = None, *, start: Optional[date] = None,
                  end: Optional[date] = None, today: date, lag_days: int = 1,
                  lag_source: str = "default", still_moving: tuple = (),
                  fiscal_start_month: int = 1) -> tuple[Optional[RangeSpec], str]:
    """The range a Briefing reads, or ``(None, why)``. ``end`` is the LAST day, inclusive, as a
    calendar picks it; the spec's ``end`` is exclusive. Pure: no clock, no store."""
    from aughor.automations.temporal import clamp_lag, complete_period

    preset = preset or ("custom" if start else "")
    if preset not in PRESETS:
        return None, f"a range is one of {', '.join(PRESETS)}"
    lag = clamp_lag(lag_days)
    anchor = today - timedelta(days=lag)          # the newest settled day
    common = dict(as_of=today, lag_days=lag, lag_source=lag_source, still_moving=tuple(still_moving))
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
    weeks = max(1, -(-(e - start).days // 7))      # ceil: the whole weeks that clear the range
    shift = timedelta(days=7 * weeks)
    year = timedelta(days=364)
    return RangeSpec("custom", start, e, start - shift, e - shift, start - year, e - year, **common), ""


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
            "measured": [], "unmeasured": []}


# ── measuring a range ──────────────────────────────────────────────────────────────────────

def _norm(s: str) -> str:
    return "".join(ch for ch in str(s or "").lower() if ch.isalnum())


def _rel(cur: Optional[float], prev: Optional[float]) -> Optional[float]:
    if cur is None or prev in (None, 0):
        return None
    return (cur - prev) / abs(prev)


def measure_range(conn_id: str, spec: RangeSpec, *, run_sql: Callable[[str], tuple], dialect: str,
                  north_stars: Optional[list] = None) -> dict:
    """Every approved metric measured for the range and its comparisons. Returns ``{"measured",
    "unmeasured"}``; every approved metric lands in exactly one list, and a north star with no
    approved definition is named in ``unmeasured`` with that reason."""
    from aughor.knowledge.period_brief import partial_span
    from aughor.semantic import metric_time as mt
    from aughor.semantic.metrics import list_metrics

    said = mt.ensure_dates(conn_id, run_sql=run_sql, dialect=dialect, today=spec.as_of)
    approved = [m for m in list_metrics(connection_id=conn_id)
                if m.status == "approved" and m.connection == conn_id][:MAX_METRICS]
    windows = spec.windows()
    slack = _slack(spec.days)
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
        if not cur or cur["value"] is None:
            unmeasured.append({"name": name, "reason": "its data has no rows in this range"})
            continue
        prev, ly = got.get("previous"), got.get("last_year")
        cur_partial = (None if m.time_kind == "stock"
                       else partial_span(cur["first"], cur["last"], spec.start, spec.end, slack))
        prev_partial = (None if (prev is None or prev["value"] is None or m.time_kind == "stock")
                        else partial_span(prev["first"], prev["last"], spec.previous_start, spec.previous_end, slack))
        pv = prev["value"] if prev else None
        lv = ly["value"] if ly else None
        measured.append({
            "name": name, "metric": m.name, "unit": m.unit or "", "time_kind": m.time_kind,
            "time_source": m.time_source, "confirmed": bool(m.time_confirmed_by),
            "current": cur["value"], "previous": pv, "last_year": lv,
            "rel": None if (cur_partial or prev_partial) else _rel(cur["value"], pv),
            "rel_last_year": None if cur_partial else _rel(cur["value"], lv),
            "status": mt.figure_status(m, windows[0], as_of=spec.as_of, lag_days=spec.lag_days),
            "current_partial": cur_partial, "previous_partial": prev_partial,
            "sql": mt.measure_sql(m, windows, dialect=dialect)[0] or "",
        })
    seen = {_norm(m.name) for m in approved} | {_norm(m.label) for m in approved}
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


def build_range_briefing(conn_id: str, spec: RangeSpec, *, scope_key: str, domain_data: dict,
                         profile: Any, workspace_id: Optional[str] = None,
                         col_types: Optional[dict] = None, force_refresh: bool = False,
                         runner: Optional[Callable[[], Any]] = None) -> dict:
    """The Briefing for one range. Cached per scope and range key; rebuilt when the window or
    the lag moves. ``runner`` opens ``(run_sql, dialect)``; it defaults to the connection's own."""
    from aughor.knowledge import period_brief
    from aughor.knowledge.briefing import get_briefing
    from aughor.orgsettings import resolve_currency

    block = range_block(spec)
    north = list(getattr(profile, "north_star_metrics", None) or []) if profile is not None else []
    currency = resolve_currency(getattr(profile, "currency_code", None) or "", workspace_id)

    def measure() -> dict:
        try:
            with (runner or (lambda: period_brief.connection_runner(conn_id)))() as (run_sql, dialect):
                got = measure_range(conn_id, spec, run_sql=run_sql, dialect=dialect, north_stars=north)
        except Exception as exc:  # noqa: BLE001
            from aughor.kernel.errors import tolerate
            tolerate(exc, "the range measurement could not open the connection",
                     counter="briefing.range.measure")
            return {"findings": [], "measured": [],
                    "unmeasured": [{"name": "headline metrics",
                                    "reason": f"the connection could not be opened ({type(exc).__name__})"}]}
        for m in got["measured"]:   # the screen shows the SAME text the lines and the narrator read
            m["declared_unit"] = m["unit"]
            vals = [m.get(k) for k in ("current", "previous", "last_year")]
            if m.get("time_kind") == "cohort" and all(v is None or 0 <= v <= 1 for v in vals):
                # a cohort's value is the share of its rows whose outcome arrived: 0..1 by
                # construction, so it reads as a percentage (theLook's return rate read 0.142857)
                m["unit"] = "ratio 0..1"
            for k in ("current", "previous", "last_year"):
                m[f"{k}_text"] = (_share(m.get(k)) if m["unit"] == "ratio 0..1" and m.get(k) is not None
                                  else period_brief._fmt(m.get(k), m["name"], m["unit"], currency))
        return {**got, "findings": range_findings(got["measured"], block, currency)}

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
                today: Optional[date] = None) -> tuple[Optional[RangeSpec], str]:
    """``resolve_range`` with this connection's lag (idea 4, honest about unsettled tables) and
    the organisation's fiscal year."""
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
    return resolve_range(preset, start=start, end=end, today=today, lag_days=lag,
                         lag_source=lag_source, still_moving=tuple(moving), fiscal_start_month=fiscal)
