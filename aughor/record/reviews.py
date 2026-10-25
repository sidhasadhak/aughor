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


def review_decision(d: _dec.Decision, *, runner: Optional[Runner] = None, today: Optional[_dt.date] = None) -> Optional[str]:
    """Measure one due decision and book its Outcome. Returns the outcome id; None when it already had one."""
    from aughor.record import scenario as S
    from aughor.record.byproducts import against_expectation, verdict_against_baseline
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
    windows = _windows(decided)
    segment = pred.extra.get("segment") if isinstance(pred.extra.get("segment"), dict) else None
    by = str((segment or {}).get("dimension") or "") or None
    part = str((segment or {}).get("value") or "")
    with (runner or _default_runner)(d.connection_id) as (run_sql, dialect):
        # a whole-statement metric is cut to the part and the rest of its group; an expression to every value
        rows, why = mt.run_measure(metric, windows, run_sql, dialect=dialect, by=by, part=part or None)
    if why:
        return _outcome(d, today, "cannot_tell", f"the review could not measure {label}: {why}",
                        against_expectation="cannot_tell")
    readings: dict[str, dict[str, Optional[float]]] = {}
    counts: dict[str, int] = {}
    for r in rows:
        group = str(r["group"]) if by else "_all"
        readings.setdefault(r["window"], {})[group] = r["value"]
        counts[r["window"]] = counts.get(r["window"], 0) + (r["n"] if (not by or group == part) else 0)
    current = windows[-1]
    if not counts.get("current"):
        return _outcome(d, today, "cannot_tell",
                        f"the thirty days after the decision ({_label(current)}) hold no rows of {label}"
                        + (f" for {by} = {part}" if by else "") + " — the data ended before it, or has not arrived",
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
    against, _ = against_expectation(d, actual, before)
    verdict, why, effect = verdict_against_baseline(
        actual=actual, baseline=proj.value, low=proj.low, high=proj.high,
        direction=str(pred.extra.get("direction") or ""), against=against,
        history_note=proj.note, drift=drift, method=method)
    shared = _overlapping(d, name, part, decided)
    if shared:
        why += (f"; {len(shared)} other decision{'s' if len(shared) != 1 else ''} on {label} in the same weeks "
                f"({', '.join(shared[:3])}) — the effect is theirs too, and is not split")
    extra = {"review_window": _label(current), "before": before, "after": actual, "method": method,
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
