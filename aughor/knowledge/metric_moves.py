"""
Metric moves — north-star trends as first-class brief candidates.

The biggest thing on a CEO's screen is rarely a single explorer finding — it is a
KPI that *moved* (margin 47% → 34%, AOV €75 → €56, repeat-rate 5% → 15%). Those moves
live in each north-star metric's ``chart_sql`` TIME TREND, not in the explorer's
findings, so the old brief never led with them.

This module turns a material trend into a synthetic "finding" so it competes for the
brief's lead through the SAME impact ranking as every other candidate (see
``knowledge.triage``): a −28% margin move scores high on the change term AND hits the
north-star term, so it out-ranks a noise-level ROAS contrast and earns the headline.

Split into a PURE core (``series_move`` / ``build_move_finding`` — unit-tested, no DB)
and a thin DB driver (``compute_metric_moves`` — runs each metric's chart_sql via an
injected ``run_sql`` and fails open per metric).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Callable, Optional

from aughor.knowledge.triage import currency_symbol


# A label that reads as a time bucket (year, ISO month, month name, quarter) — the
# signature that tells a TIME TREND (compute a move) from a TOP-N BREAKDOWN (no move).
_DATE_LABEL = re.compile(
    r"\b(?:19|20)\d{2}\b|\d{4}-\d{2}|\bq[1-4]\b|"
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*", re.I,
)

# Default: only surface a move of at least this relative magnitude (10%).
MATERIAL_REL = 0.10

#: A move compares WHOLE periods. An edge period standing on fewer rows than this — or on under half the rows of the
#: period beside it — is a part of one: the month the data begins in, or one it stopped in. 2026-10-11, luxexperience:
#: conversion "fell from 100% to 31%" from a first month of 39 sessions to an October eleven days old, while every whole
#: month in between read about 2% rising to 31%.
MIN_PERIOD_ROWS = 30
PARTIAL_SHARE = 0.5


@dataclass(frozen=True)
class Move:
    start: float
    end: float
    rel: float        # (end-start)/|start|
    direction: str    # 'up' | 'down'
    points: int
    # The periods compared and what was left out of the comparison, said — "" / None / () when the labels do not
    # read as dates or the rows behind each period were not counted.
    start_label: str = ""
    end_label: str = ""
    start_rows: Optional[int] = None
    end_rows: Optional[int] = None
    grain: str = ""
    left_out: tuple = ()


def parse_number(cell) -> Optional[float]:
    if isinstance(cell, bool):
        return None
    if isinstance(cell, (int, float)):
        return float(cell)
    if isinstance(cell, str):
        s = cell.strip().lstrip("$€£¥₹").rstrip("%").replace(",", "").strip()
        try:
            return float(s)
        except ValueError:
            return None
    try:
        return float(cell)
    except (TypeError, ValueError):
        return None


def _is_time_trend(labels: list) -> bool:
    """A series is a time trend when most of its labels read as time buckets — so a
    top-N breakdown ('Fragrance', 'Skincare', …) is never mistaken for a move."""
    if not labels:
        return False
    dated = sum(1 for v in labels if v is not None and _DATE_LABEL.search(str(v)))
    return dated >= (len(labels) + 1) // 2


_MONTH_NO = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun",
                                          "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
_ADJECTIVE = {"day": "daily", "week": "weekly", "month": "monthly", "quarter": "quarterly", "year": "yearly"}


def label_day(label) -> Optional[date]:
    """The first day of the period a time-bucket label names ('2026-09-01…', 'Sep 2026', 'Q3 2026', '2026'), or None."""
    if isinstance(label, datetime):
        return label.date()
    if isinstance(label, date):
        return label
    s = str(label or "").strip()
    try:
        m = re.match(r"(\d{4})-(\d{2})(?:-(\d{2}))?", s)
        if m:
            return date(int(m[1]), int(m[2]), int(m[3] or 1))
        m = re.fullmatch(r"([A-Za-z]{3})[a-z]*\.?\s+(\d{4})", s)
        if m and m[1].lower() in _MONTH_NO:
            return date(int(m[2]), _MONTH_NO[m[1].lower()], 1)
        m = re.fullmatch(r"q([1-4])\s*(\d{4})|(\d{4})[-\s]?q([1-4])", s, re.I)
        if m:
            q, y = (m[1], m[2]) if m[1] else (m[4], m[3])
            return date(int(y), 3 * (int(q) - 1) + 1, 1)
        if re.fullmatch(r"\d{4}", s):
            return date(int(s), 1, 1)
    except ValueError:
        return None
    return None


def period_key(label) -> str:
    """A period's key, the same whichever type the engine returned its label in (a DATE in one statement, a TIMESTAMP
    in its rewrite): the ISO day it begins on, else the label as written."""
    day = label_day(label)
    return day.isoformat() if day else str(label)


def _grain(days: list) -> str:
    """The series' period, read off the shortest step between two of its labels; "" when it cannot be read."""
    steps = [(b - a).days for a, b in zip(days, days[1:]) if a and b and b > a]
    if not steps:
        return ""
    step = min(steps)
    return "day" if step <= 1 else "week" if step <= 7 else "month" if step <= 31 else "quarter" if step <= 92 else "year"


def _period_end(start: date, grain: str) -> date:
    """The first day AFTER the period that begins on ``start``."""
    if grain == "day":
        return start + timedelta(days=1)
    if grain == "week":
        return start + timedelta(days=7)
    months = {"month": 1, "quarter": 3, "year": 12}[grain]
    m = start.month - 1 + months
    return date(start.year + m // 12, m % 12 + 1, 1)


def _period_words(label, day: Optional[date], grain: str) -> str:
    if day is None or not grain:
        return str(label)
    if grain == "month":
        return day.strftime("%b %Y")
    if grain == "quarter":
        return f"Q{(day.month - 1) // 3 + 1} {day.year}"
    if grain == "year":
        return str(day.year)
    return day.isoformat()


def _partial(edge: Optional[int], beside: Optional[int]) -> bool:
    """Is a period standing on ``edge`` rows, next to one on ``beside``, only a part of one? Unknown is never partial."""
    if edge is None:
        return False
    return edge < MIN_PERIOD_ROWS or (beside is not None and edge < PARTIAL_SHARE * beside)


def series_move(columns, rows, min_points: int = 3, *, counts: Optional[dict] = None,
                open_from: Optional[date] = None, uncounted_start: bool = False) -> Optional[Move]:
    """The net move of a TIME-TREND series between its first and last WHOLE periods, or None when it isn't a trend,
    is too short, or has a zero baseline (no defined relative move). Assumes the chart_sql ordered its buckets
    ascending (it does — see NorthStarMetric.chart_sql).

    Left out, and said in ``left_out``: a period still open on ``open_from`` (the first day the data is not yet settled
    for), and an edge period ``counts`` (rows behind each label) shows to be a part of one. ``uncounted_start`` leaves
    out the first period when its rows could not be counted — the period the data begins in is rarely whole. With none
    of the three, the series' first and last points are compared, as before."""
    if not rows or len(rows) < min_points:
        return None
    # Normalise to row-lists; label = first column, value = first numeric non-label column.
    norm = [list(r.values()) if isinstance(r, dict) else list(r) for r in rows]
    labels = [r[0] if r else None for r in norm]
    if not _is_time_trend(labels):
        return None
    ncols = max((len(r) for r in norm), default=0)
    val_idx = None
    for i in range(1, ncols):
        col = [parse_number(r[i]) for r in norm if i < len(r)]
        if col and sum(1 for v in col if v is not None) >= max(min_points, len(col) // 2):
            val_idx = i
            break
    if val_idx is None:
        return None
    pts = [(r[0], parse_number(r[val_idx])) for r in norm if val_idx < len(r)]
    pts = [(lab, v) for lab, v in pts if v is not None]
    days = [label_day(lab) for lab, _ in pts]
    grain = _grain(days) if all(days) else ""
    left: list[str] = []
    rows_of = (lambda i: counts.get(period_key(pts[i][0]))) if counts is not None else (lambda i: None)
    said = lambda i: _period_words(pts[i][0], days[i], grain)  # noqa: E731

    def drop(i: int, why: str) -> None:
        left.append(f"{said(i)} — {why}")
        pts.pop(i)
        days.pop(i)

    if open_from is not None and grain:
        while pts and _period_end(days[-1], grain) > open_from:
            drop(-1, f"the {grain} is not over yet")
    # Trimmed whatever is left: a move that only partial periods could make is not called at all.
    while len(pts) >= 2 and _partial(rows_of(0), rows_of(1)):
        drop(0, f"{rows_of(0):,} rows, a part of a {grain or 'period'}")
    while len(pts) >= 2 and _partial(rows_of(-1), rows_of(-2)):
        drop(-1, f"{rows_of(-1):,} rows, a part of a {grain or 'period'}")
    if counts is None and uncounted_start and pts:
        drop(0, f"the {grain or 'period'} the data begins in; its rows could not be counted")
    if len(pts) < min_points:
        return None
    start, end = pts[0][1], pts[-1][1]
    if start == 0:
        return None
    rel = (end - start) / abs(start)
    return Move(start=start, end=end, rel=rel,
                direction="up" if end >= start else "down", points=len(pts),
                start_label=said(0) if grain else "", end_label=said(-1) if grain else "",
                start_rows=rows_of(0), end_rows=rows_of(-1), grain=grain, left_out=tuple(left))


def period_rows_sql(chart_sql: str) -> Optional[str]:
    """The chart's own statement counting the rows behind each period — its first column kept, every other replaced
    by COUNT(*). None for a statement that is not one grouped SELECT."""
    import sqlglot
    from sqlglot import exp
    try:
        tree = sqlglot.parse_one((chart_sql or "").strip().rstrip(";"), read="duckdb")
    except Exception:  # noqa: BLE001 — a statement that does not parse is counted by nobody
        return None
    if not isinstance(tree, exp.Select) or not tree.args.get("group") or len(tree.expressions) < 2:
        return None
    counted = tree.copy()
    counted.set("expressions", [counted.expressions[0], exp.alias_(exp.Count(this=exp.Star()), "period_rows")])
    return counted.sql(dialect="duckdb")


def period_rows(chart_sql: str, run_sql: Callable[[str], tuple]) -> Optional[dict]:
    """``{period_key: rows}`` behind each period of a chart, or None when they cannot be counted — including a statement
    that reads rows already summed (one row a period), whose counts say nothing about a period being whole."""
    sql = period_rows_sql(chart_sql)
    if not sql:
        return None
    try:
        _cols, rows, error = run_sql(sql)
    except Exception as _e:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(_e, "metric-move: a chart's rows per period could not be counted", counter="brief.metric_move.count_failed")
        return None
    if error or not rows:
        return None
    out: dict = {}
    for r in rows:
        cells = list(r.values()) if isinstance(r, dict) else list(r)
        n = parse_number(cells[1]) if len(cells) > 1 else None
        if n is not None:
            out[period_key(cells[0])] = int(n)
    return out if out and max(out.values()) > 1 else None


# ── finding synthesis ────────────────────────────────────────────────────────

#: A money unit says so in its own text ("EUR", "$", "currency per shipment"). The NAME is read too — a
#: 'currency, strictly positive' MRR names no symbol — but never over a unit that states a ratio: "Net
#: Revenue Retention" and "ROAS (Return on Ad Spend)" are named for money and measured in multiples of it.
_CUR_UNIT = re.compile(r"usd|eur|gbp|jpy|cny|inr|\$|€|£|¥|₹|\bcurrency\b", re.I)
_CUR_NAME = re.compile(r"revenue|\bvalue\b|\baov\b|price|spend|sales|order\s+value", re.I)
_RATIO_UNIT = re.compile(r"\bratio\b|\bmultiple\b|\btimes\b|\bx\b|×", re.I)
#: A metric measured in multiples of what it returns (ROAS 4.2, LTV:CAC 3.1) — a figure, not money.
_MULTIPLE = re.compile(r"\broas\b|return on ad", re.I)
#: The unit a text OPENS with, before the commentary that follows it — 'hours per aircraft per day, 0..24
#: (physically capped at 24). Any value > 24 is impossible.' is stated in hours, and its closing "value" is
#: prose, not a currency. The same principle as the range reading: what the text states first is what it means.
_UNIT_HEAD = re.compile(r"[;(]|,|\.\s")


def _unit_head(unit: str) -> str:
    return _UNIT_HEAD.split(unit or "", maxsplit=1)[0]


def format_value(value: float, name: str, unit: str, sym: str) -> str:
    """Format a metric value for prose AT THE SCALE ITS TEXT STATES: a percent only for a stated 0..1 or
    0..100 rate (`stated_range`'s ratio01 / pct100), currency with the business's symbol, everything else as
    a plain number.

    Reading the scale off the words instead — percent|ratio|rate|margin|share anywhere in the name or unit,
    times 100 when the value was under 1.5 — phrased a 'ratio 0..∞' turnover moving 4 → 6 as "from 4% to
    6%" and a 'percent 0-100' defect rate moving 1.2 → 2.2 as "from 120% to 2%". Whether a text states a
    bounded rate is `business_profile/validate.py::stated_range`'s question, and the KPI tiles ask the same
    reader (the API ships it as each metric's `stated_range`)."""
    from aughor.business_profile.validate import stated_range

    kind = stated_range(unit)[0]
    # A percentage carries one decimal (2026-10-23, the user's default for the Olist study's group C):
    # "9%" hid whether a rate was 8.5% or 9.4%.
    if kind == "ratio01":
        # A 0..1 rate whose chart_sql came out on the 0..100 scale is still that rate's percent.
        return f"{value * 100 if abs(value) <= 1.5 else value:.1f}%"
    if kind == "pct100":
        return f"{value:.1f}%"
    if _CUR_UNIT.search(unit) or (_CUR_NAME.search(f"{name} {_unit_head(unit)}")
                                  and not _RATIO_UNIT.search(unit) and not _MULTIPLE.search(name)):
        return f"{sym}{value:,.0f}" if abs(value) >= 10 else f"{sym}{value:,.2f}"
    # Everything else: a count, a duration, a plain magnitude. `:g` gives six significant
    # figures, which is right for a count and wrong for anything measured — theLook's
    # ship-to-delivery lead time read "1.95529" days on the Briefing, five decimals of float
    # noise presented as a business figure. An integral value stays an integer (a count is not
    # "6951.00"); anything else is rounded to two decimals, which is as much precision as a
    # headline figure can carry honestly.
    if value == int(value):
        return f"{int(value):g}"
    return f"{round(value, 2):g}"


def _fmt_numeric(value: float, name: str, unit: str, sym: str) -> float:
    """The numeric magnitude a value would DISPLAY as (after unit formatting/rounding) —
    so a 0.004 ratio shown as '0%' reads back as 0.0."""
    disp = format_value(value, name, unit, sym)
    cleaned = re.sub(r"[^0-9.eE-]", "", disp) or "0"
    try:
        return abs(float(cleaned))
    except ValueError:
        return 0.0


def is_degenerate_move(move: Move, name: str, unit: str, currency_code: Optional[str]) -> bool:
    """True when a move rests on a near-zero base — its smaller endpoint rounds to zero at
    display precision (the '0% → 1% (+40%)' case). The big relative % is then an artifact of
    a near-zero denominator, not signal, so it must never surface (let alone lead). Mirrors
    the KPI strip's 'no rounds-to-zero on cards' rule, applied to a move's endpoints."""
    sym = currency_symbol(currency_code)
    lo = min(_fmt_numeric(move.start, name, unit, sym), _fmt_numeric(move.end, name, unit, sym))
    # A rate's base is near zero when it rounds to 0 at WHOLE percent — fixed here, not read off the
    # display, which carries one decimal since 2026-10-23: 0.4% → 0.6% (+50%) is still a near-zero
    # base, as it was when both printed "0%".
    from aughor.business_profile.validate import stated_range
    kind = stated_range(unit)[0]
    if kind in ("ratio01", "pct100"):
        return round(lo) == 0
    return lo == 0.0


def build_move_finding(name: str, unit: str, move: Move, currency_code: Optional[str],
                       domain: str = "Key Metrics", scope: str = "") -> dict:
    """A synthetic finding dict describing a metric move, shaped exactly like an explorer
    insight so it flows through triage/impact ranking unchanged. The 'from X to Y (±N%)'
    phrasing is what ``triage.extract_change`` reads to score the move's magnitude; the periods
    compared close the sentence when the labels read as dates. ``scope`` (a schema) keeps two
    datasets' moves of one metric apart — each is recorded under its id."""
    sym = currency_symbol(currency_code)
    verb = "risen" if move.direction == "up" else "fallen"
    start = format_value(move.start, name, unit, sym)
    end = format_value(move.end, name, unit, sym)
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:40]
    when = (f"between {move.start_label} and {move.end_label}" if move.start_label and move.end_label
            else "over the period")
    return {
        "id": f"metric-move::{scope + '.' if scope else ''}{slug}",
        "domain": domain,
        "angle": "Trend",
        "finding": f"{name} has {verb} from {start} to {end} ({move.rel * 100:+.0f}%) {when}.",
        "sql": "",   # populated by the driver with the metric's chart_sql
        "confidence": 0.8,   # a measured trend on the audited metric SQL — high trust
        "novelty": 3,
        "metric_move": True,
    }


def move_dossier(name: str, definition: str, move: Move, finding: str, chart_sql: str, measured_at: str) -> dict:
    """The move's derivation, in the explorer's dossier shape (``explorer/dossier.py``), so its Evidence reads like an
    explorer finding's and "Open in Ask" starts from it: what was measured, how, the two periods compared with the rows
    each stands on, checked against the finding by the explorer's own guard, and what was left out. Its structural
    ground — the joins its tables stand on — is the caller's to add from the explorer's facts."""
    from aughor.explorer.dossier import DOSSIER_VERSION
    from aughor.explorer.grounding import verify_finding

    per = move.grain or "period"
    on = lambda n: f" over {n:,} rows" if n is not None else ""  # noqa: E731
    figure = lambda v: f"{v:,.6g}"  # noqa: E731
    compared = [[move.start_label or "first", move.start], [move.end_label or "last", move.end]]
    grounding = verify_finding(finding, compared)
    how = (f"Read from its {_ADJECTIVE.get(per, per)} series ({move.points} whole {per}s), the move compares the first "
           f"and the last whole {per}.")
    left = f" Left out: {'; '.join(move.left_out)}." if move.left_out else ""
    return {
        "dossier_version": DOSSIER_VERSION,
        "asked_by": "briefing",
        "question": f"How has {name} moved between its first and last whole {per}s?",
        "sql": chart_sql,
        "finding": finding,
        "rationale": (f"{name}: {definition.strip().rstrip('.')}. " if (definition or "").strip() else "") + how + left,
        "result_cells": (f"{compared[0][0]}: {figure(move.start)}{on(move.start_rows)} · "
                         f"{compared[1][0]}: {figure(move.end)}{on(move.end_rows)}"),
        "grounding": {"grounded": grounding.grounded, "checked": grounding.checked,
                      "ungrounded": list(grounding.ungrounded)},
        "structural_ctx": {"null_meanings": {}, "joins": [], "lifecycles": {}, "distributions": {}},
        "generated_at": measured_at,
        "data_fingerprint": None,
        "data_version": None,
    }


# ── DB driver ────────────────────────────────────────────────────────────────

def compute_metric_moves(
    metrics: list[Any],
    run_sql: Callable[[str], tuple],
    currency_code: Optional[str] = None,
    *,
    material_rel: float = MATERIAL_REL,
    max_metrics: int = 8,
    settled_through: Optional[date] = None,
    scope: str = "",
    measured_at: str = "",
) -> list[dict]:
    """Run each north-star metric's ``chart_sql`` and return synthetic findings for the
    MATERIAL time-trend moves, biggest move first.

    ``metrics`` are NorthStarMetric models (or dicts) carrying ``name`` / ``chart_sql`` /
    ``unit_or_range`` / ``definition``. ``run_sql(sql) -> (columns, rows, error)`` is injected so this stays
    testable and never imports the DB layer. Fail-open per metric: a chart_sql that errors
    or isn't a trend simply contributes nothing.

    A move compares whole periods: each chart's rows per period are counted with its own statement
    (``period_rows``), a period still open on ``settled_through`` is left out, and so is an edge period
    standing on a part of one. Each finding carries its ``dossier`` (``move_dossier``) for the caller to
    record, and ``generated_at`` = ``measured_at``."""
    out: list[tuple[float, dict]] = []
    for m in (metrics or [])[:max_metrics]:
        get = (lambda k, m=m: (m.get(k) if isinstance(m, dict) else getattr(m, k, "")) or "")
        name, chart_sql, unit, definition = get("name"), get("chart_sql"), get("unit_or_range"), get("definition")
        if not name or not chart_sql.strip():
            continue
        try:
            columns, rows, error = run_sql(chart_sql)
        except Exception as _e:
            from aughor.kernel.errors import tolerate
            tolerate(_e, "metric-move: chart_sql execution failed", counter="brief.metric_move.sql_failed")
            continue
        if error or not rows:
            continue
        counts = period_rows(chart_sql, run_sql)
        move = series_move(columns, rows, counts=counts, open_from=settled_through, uncounted_start=counts is None)
        if move is None or abs(move.rel) < material_rel:
            continue
        if is_degenerate_move(move, name, unit, currency_code):
            continue   # near-zero base — a big relative % that is noise, not signal
        finding = build_move_finding(name, unit, move, currency_code, scope=scope)
        finding["sql"] = chart_sql
        if measured_at:
            finding["generated_at"] = measured_at
        finding["dossier"] = move_dossier(name, definition, move, finding["finding"], chart_sql, measured_at)
        out.append((abs(move.rel), finding))
    out.sort(key=lambda t: t[0], reverse=True)
    return [f for _, f in out]
