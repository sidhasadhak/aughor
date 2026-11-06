"""The North Star, as a query — closed loops per quarter, guarded by calibration error (Track G5).

`docs/PLATFORM_2027_STUDY_2026-10-04.md` §X chose it and defined it so it would be "a query and not an
impression"; until 2026-11-06 nothing computed it. A loop is CLOSED when all five hold:

1. a Decision with a named owner;
2. at least one prediction booked AT OR BEFORE ``decided_at`` (a target or an interval, a coverage, a
   method, a ``settles_on``) — a prediction booked after the fact is hindsight, whatever it says;
3. an Outcome written on or after the review date;
4. the outcome records both verdicts — against the expectation and against the metric's own baseline —
   or says *cannot tell* and why;
5. the write-back ran (the outcome names what it updated).

A loop closes in the quarter its outcome was written. A decision with no expectation is reliance
recorded, counted separately — still worth having, not a closed loop. The guard is calibration error:
over the predictions that SETTLED in the quarter, the mean absolute gap between stated and observed
interval coverage, weighted by how many each reference class (method × metric) judged. Reported as a
pair, never as one figure, each with its *n*; and every outcome that did not close says which part
failed, so the number can be argued with rather than believed.
"""
from __future__ import annotations

import datetime as _dt
from typing import Optional

#: How long after ``decided_at`` a prediction may be written and still count as booked WITH the
#: decision: one booking writes the decision's time first and its prediction a moment later.
BOOKING_SLACK = _dt.timedelta(minutes=5)

#: Rule 2's fields: a prediction a later outcome can be scored against.
_PREDICTION_NEEDS = ("settles_on",)


def quarter_bounds(quarter: str = "", *, today: Optional[_dt.date] = None) -> tuple[str, _dt.date, _dt.date]:
    """``("2026-Q4", 2026-10-01, 2027-01-01)`` for ``"2026-Q4"``, or for the quarter ``today`` is in."""
    if quarter:
        year, q = quarter.upper().split("-Q")
        y, n = int(year), int(q)
        if not 1 <= n <= 4:
            raise ValueError(f"no such quarter: {quarter!r}")
    else:
        d = today or _dt.datetime.now(_dt.timezone.utc).date()
        y, n = d.year, (d.month - 1) // 3 + 1
    start = _dt.date(y, 3 * (n - 1) + 1, 1)
    end = _dt.date(y + 1, 1, 1) if n == 4 else _dt.date(y, 3 * n + 1, 1)
    return f"{y}-Q{n}", start, end


def _at(value: str) -> Optional[_dt.datetime]:
    if not value:
        return None
    try:
        t = _dt.datetime.fromisoformat(str(value).replace("Z", "+00:00").replace(" ", "T"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=_dt.timezone.utc)


def _day(value: str) -> str:
    return str(value or "")[:10]


def why_not_closed(decision, outcome, prediction) -> str:
    """The first of the five rules this decision's loop fails, in plain words; "" when it is closed."""
    if not (decision.owner or "").strip():
        return "no owner is named"
    if prediction is None:
        return "no prediction was booked with the decision"
    if any(not (prediction.extra or {}).get(f) for f in _PREDICTION_NEEDS):
        return "the prediction states no day it settles on"
    booked, decided = _at(prediction.recorded_at), _at(decision.decided_at)
    if booked and decided and booked > decided + BOOKING_SLACK:
        return (f"the prediction was booked {booked.date().isoformat()}, after the decision it predicts "
                f"({decided.date().isoformat()}): hindsight, not a prediction")
    if outcome is None:
        return "no outcome has been written"
    if decision.review_on and _day(outcome.recorded_at) < decision.review_on:
        return f"the outcome was written before the review date ({decision.review_on})"
    if outcome.verdict == "cannot_tell":
        if not (outcome.why or "").strip():
            return "the outcome says it cannot tell, and not why"
    elif not outcome.against_expectation:
        return "the outcome has a verdict against the baseline but none against the expectation"
    if not outcome.writes_back:
        return "the write-back did not run: the outcome names nothing it updated"
    return ""


def rule_of(reason: str) -> str:
    """The rule a reason names, without the dates it carries — what a reader groups by."""
    if "hindsight" in reason:
        return "the prediction was booked after the decision it predicts (hindsight)"
    if "before the review date" in reason:
        return "the outcome was written before the review date"
    return reason


def closed_loops(start: _dt.date, end: _dt.date, *, conn_id: Optional[str] = None) -> dict:
    """Every decision whose outcome was written in ``[start, end)``: closed or not, and why not."""
    from aughor.record import claims as C
    from aughor.record import decisions as D
    closed, open_, reliance = [], [], 0
    for d in D.list_decisions(conn_id=conn_id, limit=5000):
        if d.superseded_by or not d.outcome:
            continue
        outcome = D.outcome_by_id(d.outcome)
        written = _at(outcome.recorded_at) if outcome else None
        if not written or not (start <= written.date() < end):
            continue
        if not d.expectation_claim:
            reliance += 1
            continue
        prediction = C.get(d.expectation_claim)
        row = {"decision": d.id, "question": d.question[:160], "owner": d.owner,
               "outcome_written": written.date().isoformat(), "verdict": outcome.verdict}
        why = why_not_closed(d, outcome, prediction)
        (open_ if why else closed).append({**row, **({"not_closed": why, "rule": rule_of(why)} if why else {})})
    return {"closed": closed, "not_closed": open_, "reliance_without_expectation": reliance}


def calibration_error(start: _dt.date, end: _dt.date, *, conn_id: Optional[str] = None) -> dict:
    """Mean |stated − observed| interval coverage over the predictions that settled in ``[start, end)``,
    weighted by what each reference class judged. ``None`` with n = 0 — nothing settled is said, not 0."""
    from aughor.record import claims as C
    classes: dict[tuple[str, str], dict] = {}
    for c in C.list_claims(kind="prediction", state="scored", conn_id=conn_id, limit=5000):
        settles = _day((c.extra or {}).get("settles_on", ""))
        if not settles or not (start.isoformat() <= settles < end.isoformat()):
            continue
        g = classes.setdefault((str(c.extra.get("method") or "declared"), c.statement.metric),
                               {"inside": 0, "judged": 0, "stated": [], "cannot_tell": 0})
        against = str(c.extra.get("scored_against") or "")
        if against in ("inside", "above", "below"):
            g["judged"] += 1
            g["inside"] += against == "inside"
            if c.extra.get("coverage") is not None:
                g["stated"].append(float(c.extra["coverage"]))
        else:
            g["cannot_tell"] += 1
    rows, weighted, n = [], 0.0, 0
    for (method, metric), g in sorted(classes.items()):
        if not g["judged"] or not g["stated"]:
            rows.append({"method": method, "metric": metric, "judged": g["judged"], "cannot_tell": g["cannot_tell"],
                         "gap": None})
            continue
        stated = sum(g["stated"]) / len(g["stated"])
        observed = g["inside"] / g["judged"]
        gap = abs(stated - observed)
        weighted += gap * g["judged"]
        n += g["judged"]
        rows.append({"method": method, "metric": metric, "judged": g["judged"], "cannot_tell": g["cannot_tell"],
                     "stated": round(stated, 3), "observed": round(observed, 3), "gap": round(gap, 3)})
    return {"error": round(weighted / n, 3) if n else None, "n": n, "classes": rows}


def north_star(quarter: str = "", *, conn_id: Optional[str] = None, today: Optional[_dt.date] = None) -> dict:
    """The pair for one quarter, with its n and its reasons — and the sentence that reports it."""
    label, start, end = quarter_bounds(quarter, today=today)
    loops = closed_loops(start, end, conn_id=conn_id)
    cal = calibration_error(start, end, conn_id=conn_id)
    outcomes = len(loops["closed"]) + len(loops["not_closed"])
    loops_part = (f"{len(loops['closed'])} loop{'s' if len(loops['closed']) != 1 else ''} closed of "
                  f"{outcomes} outcome{'s' if outcomes != 1 else ''} written")
    cal_part = (f"calibration error {cal['error']:.2f} over {cal['n']} settled prediction{'s' if cal['n'] != 1 else ''}"
                if cal["n"] else "calibration error: no prediction settled this quarter")
    return {"quarter": label, "from": start.isoformat(), "until": end.isoformat(),
            "loops_closed": len(loops["closed"]), "outcomes_written": outcomes,
            "reliance_without_expectation": loops["reliance_without_expectation"],
            "closed": loops["closed"], "not_closed": loops["not_closed"],
            "calibration": cal, "sentence": f"{label}: {loops_part} · {cal_part}"}
