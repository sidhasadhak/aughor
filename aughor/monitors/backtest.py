"""Idea 6, first half · backtest an alert before it interrupts anyone.

Replay an EXISTING monitor over the last year of its own series, under the rule it actually
runs with (`monitors/rules.py`), and say how often it would have fired and on which days —
"41 times, 30 of them Mondays" is the sentence that tells a person to raise the σ or to
exclude the weekday before the alert teaches them to ignore it.

What can be replayed: an anomaly monitor whose SQL returns a (date, value) series, a
threshold monitor on such a series, and a `metric_name` monitor whose approved definition
sits on a table with a timestamp (its expression per day, the way the Watcher reads it).
A check that returns one number as of now has no history to replay, and the backtest says
so rather than inventing one. Days younger than the connection's learned settling lag are
not replayed: they are not final, and the monitor does not score them either.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Optional

from aughor.monitors.models import Monitor
from aughor.monitors.rules import anomaly_verdict, threshold_verdict

#: A year of the monitor's own days.
BACKTEST_DAYS = 365
#: The σ ladder the sentence offers when the replay is noisy — the same as the Watcher's.
SIGMA_LADDER = (2.5, 3.0, 3.5, 4.0)
#: A monthly alert is worth a person's minute; more than one a month over a year is noise.
MAX_FIRINGS_PER_YEAR = 12

RunSql = Callable[[str], tuple[list, list, Optional[str]]]


@dataclass
class Firing:
    day: str
    value: float
    severity: str
    z: float = 0.0


@dataclass
class Backtest:
    monitor_id: str
    rule: str                      # "anomaly" | "threshold" | ""
    ok: bool
    reason: str = ""
    sigma: Optional[float] = None
    days: int = 0
    series_from: str = ""
    series_to: str = ""
    settle_days: int = 1
    firings: list[Firing] = field(default_factory=list)
    by_weekday: dict[str, int] = field(default_factory=dict)
    sentence: str = ""
    quieter_sigma: Optional[float] = None

    @property
    def count(self) -> int:
        return len(self.firings)


# ── the series ───────────────────────────────────────────────────────────────────


def series_sql_for(monitor: Monitor, *, since: date) -> tuple[str, str]:
    """(sql, how) — the monitor's own SQL when it is a series, or the approved metric's
    expression per day when the monitor names a metric on a time table; ("", why) otherwise."""
    if (monitor.custom_sql or "").strip():
        return monitor.custom_sql.strip(), "the monitor's own SQL"
    name = (monitor.metric_name or "").strip()
    if not name:
        return "", "the monitor has neither SQL nor a metric"
    try:
        from aughor.monitors.sentinel import daily_series_sql
        from aughor.semantic.metrics import get_metric
        from aughor.settling.sampler import time_tables
        metric = get_metric(name, connection_id=monitor.conn_id)
        if metric is None:
            metric = get_metric(name)
        if metric is None or not metric.tables:
            return "", f"metric {name!r} is not registered on this connection"
        if (metric.sql or "").strip().lower().startswith("select"):
            return "", f"metric {name!r} states its own SELECT; it has no day to replay by"
        ts = {t.split(".")[-1]: col for t, col, _ in time_tables(monitor.conn_id)}
        col = ts.get(str(metric.tables[0]).split(".")[-1])
        if not col:
            return "", f"metric {name!r} sits on a table with no profiled timestamp"
        return daily_series_sql(metric.sql, metric.tables[0], col, list(metric.filters or []),
                                since=since), f"metric {name!r} per day"
    except Exception as exc:  # noqa: BLE001 — the reason is the result
        return "", f"could not build a series for metric {name!r}: {str(exc)[:120]}"


# ── the replay ───────────────────────────────────────────────────────────────────


def replay(points: list[tuple[date, float]], monitor: Monitor) -> tuple[str, list[Firing]]:
    """The monitor's rule over its series, day by day: (rule name, firings)."""
    values = [v for _, v in points]
    fired: list[Firing] = []
    if monitor.alert_on == "anomaly":
        for i, (d, v) in enumerate(points):
            verdict = anomaly_verdict(values[:i], v, monitor.sigma_threshold)
            if verdict.fired:
                fired.append(Firing(d.isoformat(), v, verdict.severity, verdict.z))
        return "anomaly", fired
    if monitor.alert_on == "threshold_cross":
        for d, v in points:
            verdict = threshold_verdict(v, direction=monitor.threshold_direction,
                                        warning=monitor.warning_threshold,
                                        critical=monitor.critical_threshold)
            if verdict.fired:
                fired.append(Firing(d.isoformat(), v, verdict.severity))
        return "threshold", fired
    return "", fired


def _by_weekday(firings: list[Firing]) -> dict[str, int]:
    out: dict[str, int] = {}
    for f in firings:
        name = calendar.day_name[date.fromisoformat(f.day).weekday()]
        out[name] = out.get(name, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def _sentence(bt: Backtest) -> str:
    n = bt.count
    head = (f"would have fired {n} time{'s' if n != 1 else ''} in the last {bt.days} days"
            if n else f"would never have fired in the last {bt.days} days")
    if n >= 2 and bt.by_weekday:
        day, k = next(iter(bt.by_weekday.items()))
        if k >= 2 and k / n >= 0.5:
            head += f", {k} of them {day}s"
    if bt.quieter_sigma is not None:
        head += f"; {bt.quieter_sigma}σ would have fired at most {MAX_FIRINGS_PER_YEAR} times"
    if bt.settle_days > 1:
        head += f" (the youngest {bt.settle_days} days are still settling and were not replayed)"
    return head + "."


def backtest_monitor(monitor: Monitor, *, run_sql: Optional[RunSql] = None,
                     today: Optional[date] = None) -> Backtest:
    today = today or datetime.now(timezone.utc).date()
    try:
        from aughor.settling import learned_lag_days
        settle_days = learned_lag_days(monitor.conn_id) or 1
    except Exception:
        settle_days = 1
    since = today - timedelta(days=BACKTEST_DAYS + 30 + settle_days)
    sql, how = series_sql_for(monitor, since=since)
    if not sql:
        return Backtest(monitor.id, "", False, reason=f"nothing to replay: {how}", settle_days=settle_days)
    if run_sql is None:
        from aughor.db.measure import run_sql_for
        run_sql = run_sql_for(monitor.conn_id)
    from aughor.monitors.sentinel import read_series
    points = read_series(run_sql, sql)
    if not points:
        return Backtest(monitor.id, "", False, settle_days=settle_days,
                        reason=f"nothing to replay: {how} returned no (day, value) series — a check "
                               f"that returns one number as of now has no history")
    cutoff = today - timedelta(days=max(1, settle_days))
    points = [(d, v) for d, v in points if d <= cutoff][-(BACKTEST_DAYS + 30):]
    if points[-1][0] < today - timedelta(days=BACKTEST_DAYS):
        return Backtest(monitor.id, "", False, settle_days=settle_days,
                        reason=f"the series ends on {points[-1][0].isoformat()} — stale, or "
                               f"truncated by the executor's row cap")
    rule, firings = replay(points, monitor)
    if not rule:
        return Backtest(monitor.id, "", False, settle_days=settle_days,
                        reason=f"a {monitor.alert_on} monitor has no day-by-day rule to replay")
    window = [f for f in firings if f.day >= (today - timedelta(days=BACKTEST_DAYS)).isoformat()]
    days = len([1 for d, _ in points if d >= today - timedelta(days=BACKTEST_DAYS)])
    bt = Backtest(monitor.id, rule, True, sigma=monitor.sigma_threshold if rule == "anomaly" else None,
                  days=days, series_from=points[0][0].isoformat(), series_to=points[-1][0].isoformat(),
                  settle_days=settle_days, firings=window, by_weekday=_by_weekday(window))
    if rule == "anomaly" and bt.count > MAX_FIRINGS_PER_YEAR:
        values = [v for _, v in points]
        for sigma in SIGMA_LADDER:
            if sigma <= monitor.sigma_threshold:
                continue
            n = sum(1 for i in range(len(values)) if anomaly_verdict(values[:i], values[i], sigma).fired)
            if n <= MAX_FIRINGS_PER_YEAR:
                bt.quieter_sigma = sigma
                break
    bt.sentence = _sentence(bt)
    return bt
