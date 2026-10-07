"""What each measured item of a Briefing is expected to read next (the 2027 study §V, screen 3;
decided 2026-10-05, ROADMAP §6 item 42c).

For every approved metric a range Briefing measures: the range after this one, and the band the
metric's own past says it will fall in — the mean of the six ranges before it, each stepped back
the way the range's own comparison is and read at the same age, with an interval at the stated
coverage and the backtest on those ranges. The method is the Record's "history" (`scenario.
backtest`, the same interval); the measurement is the Briefing's own (`metric_time.run_measure`),
so the prediction is OF the figure the next Briefing will print, and it is scored by measuring that
figure the same way once the next range has settled.

One prediction per connection, metric and next range, under a stable key: a Briefing opened twice
books it once, and the second read measures nothing. A metric with fewer than three readable
ranges is not predicted and says why. A range to date is not predicted at all.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Callable, Optional

from aughor.briefing import ranges as R
from aughor.semantic.metric_time import Window

#: The fewest readable ranges a band is drawn from — the history method's own floor.
MIN_RANGES = 3


def _key(conn_id: str, metric: str, last_day: str) -> str:
    from aughor.record import claims as C
    return C.claim_key("prediction", "briefing", conn_id, metric, last_day)


def _said(claim: Any) -> dict:
    x = claim.extra or {}
    return {"claim_id": claim.id, "low": x.get("low"), "mid": x.get("mid"), "high": x.get("high"),
            "text": str(x.get("band_text") or ""), "state": claim.state, "scored_against": x.get("scored_against"),
            "actual_text": str(x.get("actual_text") or ""), "must_say": list(x.get("must_say") or []),
            "n": int((x.get("backtest") or {}).get("n") or 0)}


def expected_next(conn_id: str, spec: R.RangeSpec, *, profile: Any = None, workspace_id: Optional[str] = None,
                  runner: Optional[Callable[[], Any]] = None, today: Optional[_dt.date] = None,
                  schema: Optional[str] = None) -> dict:
    """``{"target", "why", "items"}`` — the next range (``None`` with why when there is none to
    predict) and, per approved metric, the band expected for it or why none is stated. Books each
    new prediction; one already on record is read back and nothing is measured for it."""
    from aughor.knowledge import period_brief
    from aughor.record import claims as C
    from aughor.record import scenario as S
    from aughor.semantic import metric_time as mt
    from aughor.semantic.metrics import list_metrics

    from dataclasses import replace

    target = R.later_spec(spec)
    if target is None:
        return {"target": None, "items": [],
                "why": "a range to date is not predicted: its next reading is the same range, longer"}
    today = today or _dt.datetime.now(_dt.timezone.utc).date()
    # Every range — the earlier ones and the one predicted — is read at one age: this connection's
    # lag, never the age of an old custom range, so a prediction settles as soon as its range has.
    age = min(spec.as_of - spec.end, _dt.timedelta(days=max(int(spec.lag_days) - 1, 0)))
    target = replace(target, as_of=target.end + age)
    last_day, settles_on = R._d(target.last_day), R._d(target.as_of)
    label = R._span(target.start, target.end)
    out = {"target": {"start": R._d(target.start), "last_day": last_day, "label": label, "settles_on": settles_on},
           "why": "", "items": []}
    approved = R.governed_metrics(conn_id, schema)[:R.MAX_METRICS]
    fresh = [m for m in approved if C.latest(_key(conn_id, m.name, last_day)) is None]
    measured: dict[str, tuple[list, str]] = {}
    if fresh:
        windows = [Window(f"r{i}", s, e, as_of=e + age)
                   for i, (s, e) in enumerate(R.earlier_ranges(target, S.HISTORY_WINDOWS + 1)[:-1])]
        try:
            with (runner or (lambda: period_brief.connection_runner(conn_id)))() as (run_sql, dialect):
                said = mt.ensure_dates(conn_id, run_sql=run_sql, dialect=dialect, today=spec.as_of)
                by_name = {m.name: m for m in list_metrics(connection_id=conn_id)
                           if m.status == "approved" and m.connection == conn_id}
                for m in fresh:
                    m = by_name.get(m.name, m)
                    if not mt.declared(m):
                        measured[m.name] = ([], said.get(m.name) or "its dates are not set")
                        continue
                    rows, why = mt.run_measure(m, windows, run_sql, dialect=dialect)
                    got = {r["window"]: r for r in rows}
                    measured[m.name] = ([R.read_value(got.get(w.label)) for w in windows], why)
        except Exception as exc:  # noqa: BLE001
            from aughor.kernel.errors import tolerate
            tolerate(exc, "the earlier ranges could not be read; no band is stated", counter="briefing.expected.measure")
            for m in fresh:
                measured.setdefault(m.name, ([], f"the connection could not be opened ({type(exc).__name__})"))
    currency = R._currency(profile, workspace_id)
    for m in approved:
        name = m.label or m.name
        key = _key(conn_id, m.name, last_day)
        booked = C.latest(key)
        if booked is not None:
            out["items"].append({"metric": m.name, "name": name, "expected": _said(booked), "why": ""})
            continue
        values, why = measured.get(m.name, ([], "it was not read"))
        read = [v for v in values if v is not None]
        if why or len(read) < MIN_RANGES:
            out["items"].append({"metric": m.name, "name": name, "expected": None, "why": why or (
                f"only {len(read)} earlier range{'s' if len(read) != 1 else ''} held a reading; "
                f"{MIN_RANGES} are the least a band is drawn from")})
            continue
        mu, sd = S._mean(read), S._sd(read)
        low, high = mu - S._Z80 * sd, mu + S._Z80 * sd
        if m.time_kind != "cohort" and all(v >= 0 for v in read):
            low = max(low, 0.0)          # a count or a sum that was never below zero is not expected to be
        unit = R._read_unit(m.time_kind, m.unit or "", read)
        band = (f"{R._figure_text(low, name, unit, currency)} to {R._figure_text(high, name, unit, currency)}"
                if low != high else str(R._figure_text(mu, name, unit, currency)))
        bt = S.backtest(read, coverage=S.HISTORY_COVERAGE)
        must_say = [f"{len(read)} earlier ranges, each read at the same age: {band} at "
                    f"{int(S.HISTORY_COVERAGE * 100)}% stated coverage",
                    (f"on this metric the interval held {bt['held']} of {bt['cases']} times" if bt.get("cases")
                     else "too few ranges to test the interval")]
        claim = C.Claim(
            kind="prediction", tier=S._TIER_BY_METHOD["history"],
            about=C.About(kind="connection", key=conn_id),
            # The band is in the metric's own values. The scorer reads a "%" unit as a band RELATIVE to a
            # before-figure, which this is not — so the claim carries no unit and `metric_unit` keeps it.
            statement=C.Statement(text=f"expected: {name} {band} for {label} (its own past)"[:1000], metric=m.name,
                                  value=round(mu, 6), unit="" if unit == "%" else unit,
                                  range_start=R._d(target.start), range_end=last_day),
            status="To date", as_of=today.isoformat(), author="system", author_kind="system", state="open",
            falsifier="the metric measured for that range the Briefing's way, once it has settled: a figure "
                      "outside the band scores this wrong",
            next_check=settles_on,
            extra={"method": "history", "low": round(low, 6), "mid": round(mu, 6), "high": round(high, 6),
                   "coverage": S.HISTORY_COVERAGE, "settles_on": settles_on, "backtest": bt, "must_say": must_say,
                   "band_text": band, "metric_unit": unit, "for": f"briefing:{conn_id}:{m.name}:{last_day}",
                   "briefing": {"metric": m.name, "start": R._d(target.start), "end": R._d(target.end),
                                "as_of": settles_on, "preset": spec.preset}})
        try:
            C.book(claim, key=key, conn_id=conn_id)
            booked = C.latest(key)
        except Exception as exc:  # noqa: BLE001 — a band the Record will not take is said, not shown as booked
            out["items"].append({"metric": m.name, "name": name, "expected": None,
                                 "why": f"the Record did not take the prediction: {str(exc)[:160]}"})
            continue
        out["items"].append({"metric": m.name, "name": name, "why": "",
                             "expected": _said(booked) if booked is not None else None})
    return out


def score_due(*, runner_for: Optional[Callable[[str], Any]] = None, now: Optional[_dt.datetime] = None) -> list[str]:
    """Score every open Briefing prediction whose range has settled: the metric measured for the
    predicted range the Briefing's way, at the age it was predicted for. A metric that can no longer
    be measured scores ``cannot_tell`` and says why. Returns the restated claim ids."""
    from aughor.knowledge import period_brief
    from aughor.record import claims as C
    from aughor.record import scenario as S
    from aughor.semantic import metric_time as mt
    from aughor.semantic.metrics import list_metrics

    now = now or _dt.datetime.now(_dt.timezone.utc)
    today = now.date().isoformat()
    runner_for = runner_for or (lambda conn: period_brief.connection_runner(conn, cached=False))
    out = []
    for c in C.list_claims(kind="prediction", state="open", limit=2000):
        b = (c.extra or {}).get("briefing")
        if not isinstance(b, dict) or not c.extra.get("settles_on") or c.extra["settles_on"] > today:
            continue
        conn = c.about.key if c.about.kind == "connection" else ""
        actual, note = None, ""
        try:
            m = next((x for x in list_metrics(connection_id=conn)
                      if x.name == b.get("metric") and x.status == "approved" and x.connection == conn), None)
            if m is None:
                note = "its metric is no longer an approved definition on this connection"
            else:
                window = Window("target", _dt.date.fromisoformat(b["start"]), _dt.date.fromisoformat(b["end"]),
                                as_of=_dt.date.fromisoformat(b.get("as_of") or c.extra["settles_on"]))
                with runner_for(conn) as (run_sql, dialect):
                    # the same first step every measurement of a Briefing takes: a metric's dates set by rule
                    mt.ensure_dates(conn, run_sql=run_sql, dialect=dialect, today=now.date())
                    m = next((x for x in list_metrics(connection_id=conn)
                              if x.name == m.name and x.status == "approved" and x.connection == conn), m)
                    rows, why = mt.run_measure(m, [window], run_sql, dialect=dialect)
                actual = R.read_value(rows[0]) if rows and not why else None
                note = why or (f"measured for {R._span(window.start, window.end)}" if actual is not None
                               else "its range holds no rows")
        except Exception as exc:  # noqa: BLE001 — scored cannot_tell, with why
            note = f"measurement failed: {str(exc)[:160]}"
        out.append(S.score_prediction(c, actual=actual, measured_on=today, note=note))
    return out
