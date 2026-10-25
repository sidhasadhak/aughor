"""Every decision that expected something is reviewed on its date (PENDING 57, D-2 and D-3;
docs/DECISION_LOOP_STUDY_2026-10-24.md §4).

Before this only a recommendation was reviewed (`playbook.outcomes.run_due_reviews`, hourly); a decision declared on
Home, an approval or an autonomous action reached its review date and nothing measured it. The sweep here reads
``decisions.due_for_review()`` in the same hourly tick and books one Outcome per decision:

* **nothing expected** — the outcome says so once, *cannot tell*: there is nothing to score;
* **the metric** — the expectation's approved metric, measured by its own compiler (``metric_time.measure_sql``, the
  path the Briefing and a monitor read a period by) over the thirty days after the decision, and over the six
  thirty-day windows before it;
* **what would have happened anyway** — for one part of a metric that adds up, the rest of its group at the part's
  usual share (``scenario.comparison``); otherwise the metric's own past (``scenario.history_of``), which says
  *cannot tell* where the Record's own calibration shows that past drifting one way (``scenario.drift_words``);
* **the data has ended or not arrived** — a review window with no rows is no figure, and says so;
* **another decision on the same metric in the same weeks** — named on the outcome; the effect is not split by guess.

A recommendation's review stays where it was; its outcome now carries the same drift guard. SQL only, never a model.
"""
from __future__ import annotations

import datetime as _dt
from contextlib import contextmanager
from typing import Any, Callable, Iterator, Optional

from aughor.record import claims as _claims
from aughor.record import decisions as _dec

#: The window a review reads after the decision, and the length of each prior window — the default review period.
WINDOW_DAYS = _dec.DEFAULT_REVIEW_DAYS
#: Prior windows read for the baseline — the history method's own count.
PRIOR_WINDOWS = 6

Runner = Callable[[str], Any]     # conn_id -> context manager yielding (run_sql, dialect)


@contextmanager
def _default_runner(conn_id: str) -> Iterator[tuple[Callable[[str], tuple], str]]:
    from aughor.knowledge.period_brief import connection_runner
    with connection_runner(conn_id) as got:
        yield got


def _today() -> _dt.date:
    return _dt.datetime.now(_dt.timezone.utc).date()


def review_due_decisions(*, now: Optional[_dt.datetime] = None, runner: Optional[Runner] = None) -> list[str]:
    """Review every due decision that is not a recommendation's (those have their own review); returns the outcome
    ids booked. Each decision is reviewed once — a booked outcome takes it off the due list. Nothing when the loop is
    off."""
    if not _dec.loop_on():
        return []
    booked: list[str] = []
    for d in _dec.due_for_review(now):
        if d.source.kind == "recommendation":
            continue
        try:
            oid = review_decision(d, runner=runner, today=(now.date() if now else _today()))
        except Exception as exc:  # noqa: BLE001 — one decision's failed review never stops the others'
            from aughor.kernel.errors import tolerate
            tolerate(exc, "a decision's review could not be booked; it stays due", counter="record.decision_review",
                     conn_id=d.connection_id or None)
            continue
        if oid:
            booked.append(oid)
    return booked


def _outcome(d: _dec.Decision, today: _dt.date, verdict: str, why: str, **kw) -> str:
    return _dec.book_outcome(_dec.Outcome(of=d.id, measured_on=today.isoformat(), verdict=verdict, why=why,
                                          measured_by="system:review", **kw))


def _windows(decided: _dt.date) -> list:
    from aughor.semantic.metric_time import Window
    current = Window("current", decided, decided + _dt.timedelta(days=WINDOW_DAYS))
    prior = [Window(f"prior_{k}", decided - _dt.timedelta(days=WINDOW_DAYS * k),
                    decided - _dt.timedelta(days=WINDOW_DAYS * (k - 1))) for k in range(PRIOR_WINDOWS, 0, -1)]
    return prior + [current]


def _label(w) -> str:
    return f"{w.start.isoformat()} → {w.last_day.isoformat()}"


#: The grains whose periods thirty days can fall between: a month-end snapshot is never inside a window from the 1st
#: to the 30th (the decision-framework run, defect 6 — Lux's inventory, dated on the last day of each month).
PERIOD_GRAINS = ("month", "quarter", "year")
_MONTHS = {"month": 1, "quarter": 3, "year": 12}


def _period_start(d: _dt.date, grain: str) -> _dt.date:
    step = _MONTHS[grain]
    return _dt.date(d.year, ((d.month - 1) // step) * step + 1, 1)


def _shift(d: _dt.date, months: int) -> _dt.date:
    k = d.year * 12 + (d.month - 1) + months
    return _dt.date(k // 12, k % 12 + 1, 1)


def _period_windows(decided: _dt.date, grain: str) -> list:
    """Whole periods of ``grain``: the first that starts on or after the decision, and the six before the one the
    decision fell in — a period the decision split is neither before nor after it."""
    from aughor.semantic.metric_time import Window
    step = _MONTHS[grain]
    anchor = _period_start(decided, grain)
    start = anchor if anchor == decided else _shift(anchor, step)
    current = Window("current", start, _shift(start, step))
    prior = [Window(f"prior_{k}", _shift(anchor, -step * k), _shift(anchor, -step * (k - 1)))
             for k in range(PRIOR_WINDOWS, 0, -1)]
    return prior + [current]


def _lag(conn_id: str) -> int:
    try:
        from aughor.settling.store import learned_lag_days
        return int(learned_lag_days(conn_id) or 0) if conn_id else 0
    except Exception as exc:  # noqa: BLE001 — an unreadable lag reads as none, and the review says nothing it did not
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the settling lag could not be read; a period's review waits for its end only",
                 counter="record.review_lag", conn_id=conn_id or None)
        return 0


def _wait_for_period(d: _dec.Decision, grain: str, current, label: str, lag: int) -> None:
    """The first whole period after the decision has not ended and settled: the decision's review date moves to when
    it has — a new version, the earlier kept, the move said."""
    cur = _dec._current(d)
    cur.review_on = (current.end + _dt.timedelta(days=lag)).isoformat()
    cur.extra["review_by"] = grain
    cur.extra["review_on_why"] = (f"thirty days after the decision held no rows of {label}, which is dated by the "
                                  f"{grain}: the review reads the first whole {grain} after it ({_label(current)}), "
                                  f"once it has ended" + (f" and settled ({lag} days)" if lag else ""))
    _dec.book_decision(cur)


def _read(rows: list, by: Optional[str], part: str) -> tuple[dict, dict]:
    readings: dict[str, dict[str, Optional[float]]] = {}
    counts: dict[str, int] = {}
    for r in rows:
        group = str(r["group"]) if by else "_all"
        readings.setdefault(r["window"], {})[group] = r["value"]
        counts[r["window"]] = counts.get(r["window"], 0) + (r["n"] if (not by or group == part) else 0)
    return readings, counts


def review_decision(d: _dec.Decision, *, runner: Optional[Runner] = None, today: Optional[_dt.date] = None) -> Optional[str]:
    """Measure one due decision and book its Outcome. Returns the outcome id; None when it already had one, or when
    its review waits for the first whole period of the metric's grain to end (its review date moves, said)."""
    from aughor.record import scenario as S
    from aughor.record.byproducts import against_expectation, band_of, verdict_against_baseline
    from aughor.semantic import metric_time as mt
    today = today or _today()
    if d.outcome:
        return None
    pred = _claims.get(d.expectation_claim) if d.expectation_claim else None
    if pred is None:
        return _outcome(d, today, "cannot_tell", "nothing was expected when it was decided, so there is nothing to score",
                        against_expectation="no expectation")
    name = pred.statement.metric
    from aughor.semantic.metrics import get_metric
    metric = get_metric(name, connection_id=d.connection_id or None) if name else None
    if metric is None:
        return _outcome(d, today, "cannot_tell", f"{name or 'the expected metric'} is not a metric on this connection, so "
                        "the review could not measure it", against_expectation="cannot_tell")
    label = getattr(metric, "label", None) or metric.name
    ok, why_not = mt.measurable(metric)
    if not ok:
        return _outcome(d, today, "cannot_tell", f"{label} cannot be measured for a period: {why_not}",
                        against_expectation="cannot_tell")
    decided = _dt.date.fromisoformat((d.decided_at or today.isoformat())[:10])
    period = str(d.extra.get("review_by") or "")
    period = period if period in PERIOD_GRAINS else ""
    windows = _period_windows(decided, period) if period else _windows(decided)
    segment = pred.extra.get("segment") if isinstance(pred.extra.get("segment"), dict) else None
    by = str((segment or {}).get("dimension") or "") or None
    part = str((segment or {}).get("value") or "")
    thirty = _label(_windows(decided)[-1])
    with (runner or _default_runner)(d.connection_id) as (run_sql, dialect):
        # a whole-statement metric is cut to the part and the rest of its group; an expression to every value
        rows, why = mt.run_measure(metric, windows, run_sql, dialect=dialect, by=by, part=part or None)
        if why:
            return _outcome(d, today, "cannot_tell", f"the review could not measure {label}: {why}",
                            against_expectation="cannot_tell")
        readings, counts = _read(rows, by, part)
        grain = mt.reported_grain(metric)
        if not counts.get("current") and not period and grain in PERIOD_GRAINS:
            # thirty days can fall between a metric's dates when it is dated by the month (or coarser): read whole
            # periods of the grain it is reported by instead, once the first after the decision has ended
            by_period = _period_windows(decided, grain)
            lag = _lag(d.connection_id)
            if by_period[-1].end + _dt.timedelta(days=lag) > today:
                _wait_for_period(d, grain, by_period[-1], label, lag)
                return None
            rows2, why2 = mt.run_measure(metric, by_period, run_sql, dialect=dialect, by=by, part=part or None)
            if not why2:
                readings2, counts2 = _read(rows2, by, part)
                if counts2.get("current"):
                    windows, readings, counts, period = by_period, readings2, counts2, grain
    current = windows[-1]
    if not counts.get("current"):
        span = f"the whole {period} after the decision" if period else "the thirty days after the decision"
        return _outcome(d, today, "cannot_tell",
                        f"{span} ({_label(current)}) hold{'s' if period else ''} no rows of {label}"
                        + (f" for {by} = {part}" if by else "")
                        + ("" if period or grain not in PERIOD_GRAINS else f", nor does the whole {grain} after it")
                        + " — the data ended before it, or has not arrived",
                        against_expectation="cannot_tell", extra={"review_window": _label(current)})
    key = part if by else "_all"
    actual = readings.get("current", {}).get(key)
    before = readings.get(windows[-2].label, {}).get(key)
    prior = [w.label for w in windows[:-1]]
    drift = ""
    if by and mt.adds_up(metric, dialect=dialect):
        proj = S.comparison(readings, segment=part, prior=prior, current="current")
        method = "comparison"
    else:
        values = [readings[w][key] for w in prior if readings.get(w, {}).get(key) is not None]
        proj = S.history_of(values, days=WINDOW_DAYS, labels=[_label(w) for w in windows[:-1]
                                                             if readings.get(w.label, {}).get(key) is not None])
        method = "history"
        drift = S.drift_words(d.connection_id, name)
    # a relative band is read against what would have happened anyway — the baseline the verdict is read against —
    # and against the window before only when no baseline could be drawn (the decision-framework run, defect 8)
    reference = proj.value if proj.value is not None else before
    against, _ = against_expectation(d, actual, reference)
    verdict, why, effect = verdict_against_baseline(
        actual=actual, baseline=proj.value, low=proj.low, high=proj.high,
        direction=str(pred.extra.get("direction") or ""), against=against,
        history_note=proj.note, drift=drift, method=method, band=band_of(pred))
    shared = _overlapping(d, name, part, decided)
    if shared:
        why += (f"; {len(shared)} other decision{'s' if len(shared) != 1 else ''} on {label} in the same weeks "
                f"({', '.join(shared[:3])}) — the effect is theirs too, and is not split")
    extra = {"review_window": _label(current), "before": before, "after": actual, "method": method,
             **({"review_by": period, "thirty_days_held_none": thirty} if period else {}),
             **({"band_read_against": "baseline" if proj.value is not None else "before"}
                if pred.statement.unit == "%" else {}),
             "baseline_says": proj.must_say, **({"segment": {"dimension": by, "value": part}} if by else {}),
             **({"drift": drift} if drift else {}), **({"shared_with": shared} if shared else {}),
             "review": "decision_loop"}
    return _outcome(d, today, verdict, why, actual=actual, baseline=proj.value, effect=effect,
                    against_expectation=against, extra=extra)


def _overlapping(d: _dec.Decision, metric: str, part: str, decided: _dt.date) -> list[str]:
    """Other decisions on the same connection whose expectation names the same metric (and the same part, when one
    is named) and whose thirty days after deciding overlap this one's."""
    out: list[str] = []
    for other in _dec.list_decisions(conn_id=d.connection_id or None, limit=2000):
        if other.id == d.id or other.key == d.key or not other.expectation_claim:
            continue
        pred = _claims.get(other.expectation_claim)
        if pred is None or pred.statement.metric != metric:
            continue
        seg = pred.extra.get("segment") if isinstance(pred.extra.get("segment"), dict) else {}
        if str((seg or {}).get("value") or "") != part:
            continue
        try:
            start = _dt.date.fromisoformat((other.decided_at or "")[:10])
        except ValueError:
            continue
        if abs((start - decided).days) < WINDOW_DAYS:
            out.append(other.id)
    return out
