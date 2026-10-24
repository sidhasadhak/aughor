"""Monitor runner — M20a (threshold / change) + M20b (anomaly / drift / freshness).

Each public function accepts a Monitor + a live DatabaseConnection and returns
a MonitorAlert (or None if no alert condition is met).  The scheduler calls
these on cron; they never raise — errors are caught and surfaced as info alerts.

A query the warehouse refuses is neither (GM-4): the check did not run. Read strictly, it
raises `QueryRefused` out of the monitor's function, `check_monitor` records the run as
failed, and `health_alert` sends one alert when a monitor starts failing and one when it
runs again — theLook's two monitors failed 1,737 times on 09-25/26, and every run was
recorded "executed · no alert".
"""
from __future__ import annotations

import contextvars
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from aughor.db.connection import QueryRefused
from aughor.monitors.models import Monitor, MonitorAlert

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

from aughor.util.time import now_iso as _now_iso


def _query(db, sql: str) -> list:
    """Rows for a monitor check ([] on error). Thin wrapper over the connection adapter
    (``db.rows``); the connection API is ``execute(label, sql) -> QueryResult(.rows/.error)``,
    NOT the phantom ``execute_query`` the runner once called → "No condition met" forever.

    The SQL a monitor carries is platform SQL in DuckDB's dialect (`sentinel.daily_series_sql`
    double-quotes its identifiers and says so), and it is declared so to the door, which
    translates it for the engine (GM-1): on BigQuery a double-quoted identifier is a string
    literal, and theLook's Units Sold watch failed every minute with "Invalid date:
    'created_at'" (2026-09-26, 2,283 errors on the Security page) because this wrapper ran
    it as written.

    Strict (GM-4): a refused query raises `QueryRefused` rather than returning [], which read as
    "no condition met" and recorded a monitor that never ran as one that found nothing."""
    return db.rows(sql, label="__monitor__", sql_dialect="duckdb", strict=True)


def _metric_of(monitor: Monitor):
    """The approved definition a monitor names, or None.

    SCOPED to the connection this monitor runs against. Resolving by name alone returns the first row carrying that
    name whatever connection owns it, so a monitor on one warehouse could evaluate another's formula — and unlike the
    read routes that shared this defect, a monitor ALERTS on the number, unattended, to people who never see which
    definition produced it. `conn_id` is required on `Monitor` and has always been right here; only this lookup
    ignored it."""
    try:
        from aughor.semantic.metrics import get_metric
        return get_metric(monitor.metric_name, connection_id=monitor.conn_id or None)
    except Exception:
        return None


def _resolve_sql(monitor: Monitor, db=None) -> Optional[str]:
    """Return the scalar SQL statement for this monitor (custom_sql wins). A metric's is its governed value query
    (`semantic.metrics.value_query`): its expression wrapped over its table with its filters. The bare expression it
    used to return ("SUM(amount)") is no statement, so every such check failed and never read a value.

    When ``monitor.reanchor_window`` is set and a live ``db`` is provided, the SQL's
    absolute date window is slid forward to the data's current activity edge — so a
    monitor built from a Briefing finding tracks the trailing window instead of a
    frozen one. Re-anchoring is fallback-safe (returns the SQL unchanged on any issue).
    """
    sql: Optional[str] = None
    if monitor.custom_sql:
        sql = monitor.custom_sql.strip()
    elif monitor.metric_name:
        m = _metric_of(monitor)
        if m:
            from aughor.semantic.metrics import value_query
            sql = value_query(m).strip() or None
    if sql and db is not None and getattr(monitor, "reanchor_window", False):
        try:
            from aughor.monitors.window import reanchor_trailing_window
            sql = reanchor_trailing_window(sql, db, getattr(db, "dialect", "duckdb"))
        except Exception:
            pass
    return sql


def monitor_sql(monitor: Monitor) -> Optional[str]:
    """The query this monitor runs — its own SQL, else its metric's — as written, not re-anchored: the evidence an
    alert it fired stands on. None when it resolves to none."""
    return _resolve_sql(monitor)


#: The values a check read, in order — so a check that raised nothing still says what it read (the Olist study,
#: Gap 36: "No condition met", and whether the threshold read August's R$848,860 or the all-time R$13.49M was never shown).
_READINGS: contextvars.ContextVar[Optional[list]] = contextvars.ContextVar("monitor_readings", default=None)


def _scalar(db, sql: str, dialect: Optional[str] = "duckdb") -> Optional[float]:
    """First cell of a monitor query as float, or None. Wrapper over ``db.scalar``, declared
    DuckDB as `_query` is: the threshold, any-change and trend-reversal monitors read this
    path, and the gate-map census (2026-09-26) found it still sending DuckDB-quoted SQL to
    native engines after the anomaly path was fixed. Strict, as `_query` is. A metric's period
    reading is compiled in the connection's own dialect, so it is handed on as written (``dialect=None``)."""
    value = db.scalar(sql, label="__monitor__", cast=float, sql_dialect=dialect, strict=True)
    seen = _READINGS.get()
    if seen is not None and value is not None:
        seen.append(value)
    return value


#: What the value a check read covers, in words — "August 2018", or "all history" with why.
_COVERED: contextvars.ContextVar[Optional[list]] = contextvars.ContextVar("monitor_covered", default=None)


class PeriodUnreadable(QueryRefused):
    """A monitor over a dated metric whose period could not be read: the check did not run, which is said as a failed
    run (GM-4) — never read over all history instead, which is the defect this replaced."""


class SeriesUndated(QueryRefused):
    """An anomaly check whose query's first column is not a date — a category breakdown, say. Its rows are no daily
    series, so z-scoring them as days could never mean anything; the check is a failed run that says why (GM-4)."""


def _covered(words: str) -> None:
    seen = _COVERED.get()
    if seen is not None and words not in seen:
        seen.append(words)


def covered_words() -> str:
    """What the current check's reading covers ("" when nothing said it)."""
    return next(iter(_COVERED.get() or []), "")


def _reading_sql(monitor: Monitor, db) -> tuple[Optional[str], Optional[str]]:
    """``(sql, dialect)`` a single-value check reads — the threshold, any-change and trend-reversal monitors.

    A monitor over a metric whose dates are set reads the metric for the newest settled period of the metric's
    grain — month unless a person set another, as the metric editor shows it — with the data's edge and an ended
    dataset taken as the Briefing takes them (`explorer.watch.settled_period`), compiled by the metric's own
    measurement (`metric_time.measure_sql`). Before, it read the metric's statement as written, over all history: the
    Olist study's "Monthly GMV floor" read 13,494,400.74 against a monthly 900,000 line, and could never fire while
    August 2018 sat at 848,860.10. A period with no rows is no figure, as in the Briefing.

    A monitor's own SQL is read as written; a metric with no dates is read over all history and says so."""
    if (monitor.custom_sql or "").strip() or not monitor.metric_name:
        return _resolve_sql(monitor, db), "duckdb"
    metric = _metric_of(monitor)
    if metric is None:
        return None, "duckdb"
    from aughor.semantic import metric_time as mt
    label = getattr(metric, "label", None) or metric.name
    if not mt.declared(metric):
        _covered(f"all history — {label} has no date set, so no period of it can be read")
        return _resolve_sql(monitor, db), "duckdb"
    from aughor.briefing.ranges import phrases
    from aughor.explorer.watch import settled_period
    grain = mt.reported_grain(metric)
    spec = settled_period(monitor.conn_id, grain, today=datetime.now(timezone.utc).date(),
                          schema=getattr(metric, "schema_name", None) or None)
    if spec is None:
        raise PeriodUnreadable(f"no settled {grain} of {label} could be read")
    dialect = getattr(db, "dialect", None) or "duckdb"
    sql, why = mt.measure_sql(metric, [mt.Window("current", spec.start, spec.end, as_of=spec.as_of)],
                              dialect=dialect)
    if sql is None:
        raise PeriodUnreadable(f"{label} could not be measured for a {grain}: {why}")
    _covered(phrases(spec)["covers"])
    # Compiled for this engine, so it declares no dialect: the door translates only platform SQL ("duckdb") and
    # refuses any other name, which made every dated-metric check raise on BigQuery, Postgres or Snowflake.
    return f"SELECT _v FROM ({sql}) AS _period WHERE _n > 0", None


def plain_figure(v: float) -> str:
    """A reading as a person reads one — "848,860.1", never "8.489e+05"."""
    return f"{int(v):,}" if float(v) == int(v) else f"{v:,.2f}".rstrip("0").rstrip(".")


def reading_words(monitor: Monitor, run: "MonitorRun") -> str:
    """What a check read, what it covers, and the line it is judged against: "read 848,860.1 for August 2018
    (warning below 900,000)"; "" when the check read no single value (a drift or an anomaly reads a series, and says
    so in its alert). A period with no rows says it read none."""
    over = run.covered
    if run.reading is None:
        return f"read no value for {over}: it holds no rows" if over and not over.startswith("all history") else ""
    lines = [f"{label} {monitor.threshold_direction} {plain_figure(t)}"
             for label, t in (("warning", monitor.warning_threshold), ("critical", monitor.critical_threshold))
             if t is not None and monitor.alert_on == "threshold_cross"]
    return (f"read {plain_figure(run.reading)}" + (f" over {over}" if over.startswith("all history") else
                                                   f" for {over}" if over else "")
            + (f" ({'; '.join(lines)})" if lines else ""))


#: The kinds of the two alerts about whether a monitor can run — never a reading of its metric.
QUERY_FAILING = "query_failing"
QUERY_RUNS_AGAIN = "query_runs_again"
_HEALTH = (QUERY_FAILING, QUERY_RUNS_AGAIN)
#: How far back a lookup reads past the alerts it skips.
_SCAN = 50


def _metric_alerts(monitor_id: str, limit: int) -> list[MonitorAlert]:
    """This monitor's most recent persisted alerts about its METRIC, newest first — an alert about whether the
    monitor could run is no reading, so it never becomes a baseline, a trend point or the debounce's last alert."""
    from aughor.monitors.store import get_alerts
    return [a for a in get_alerts(monitor_id=monitor_id, limit=limit + _SCAN) if a.alert_on not in _HEALTH][:limit]


def _last_alert(monitor_id: str) -> Optional[MonitorAlert]:
    """The most recent persisted metric alert for this monitor (None if none / store error)."""
    try:
        alerts = _metric_alerts(monitor_id, 1)
        return alerts[0] if alerts else None
    except Exception:
        return None


def _last_alert_value(monitor_id: str) -> Optional[float]:
    """Return the current_value from the most recent alert for this monitor."""
    last = _last_alert(monitor_id)
    return last.current_value if last else None


# ── Anti-flap (debounce) ──────────────────────────────────────────────────────
# Without this, a sustained breach re-fires on EVERY cron tick (72 alerts over a
# 3-day hourly outage), and a metric oscillating around a threshold flaps. The
# debounce suppresses a repeat alert of the same-or-lower severity within the
# monitor's grace window; first-ever alerts and severity escalations always fire.
# State is derived from the existing alert store — no new persistence.

_SEVERITY_RANK = {"info": 1, "warning": 2, "critical": 3}


def _age_hours(iso_str: str) -> Optional[float]:
    """Hours since an ISO-8601 timestamp (tz-aware or naive-UTC). None if unparseable."""
    try:
        dt = datetime.fromisoformat((iso_str or "").replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0
    except Exception:
        return None


def _suppressed_by_grace(monitor: Monitor, alert: MonitorAlert) -> bool:
    """True ⇒ debounce this alert: a same-or-lower-severity alert already fired within
    the grace window. First-ever alerts and escalations are never suppressed."""
    grace = getattr(monitor, "grace_period_hours", 0.0) or 0.0
    if grace <= 0:
        return False
    last = _last_alert(monitor.id)
    if last is None:
        return False  # first alert always fires
    if _SEVERITY_RANK.get(alert.severity, 0) > _SEVERITY_RANK.get(last.severity, 0):
        return False  # escalation fires immediately
    age = _age_hours(last.triggered_at)
    return age is not None and age < grace


def _guard_caveats(monitor: Monitor, db) -> Optional[str]:
    """WP-1b (unconditional since 2026-08-06) — deterministic correctness probes on the SQL a
    monitor evaluates: id-arithmetic (pure AST) and parent fan-out / dim-ratio chasm
    (schema-based). A wrong-grain SUM in a monitor silently mis-values the metric and
    then alerts on it — this attaches the reason to the alert instead of asserting the
    number clean. Caveat-and-deliver: NEVER rewrites the monitor's SQL, never blocks
    the alert; every probe is fail-open. Returns a short caveat string or None."""
    sql = _resolve_sql(monitor, db)
    if not sql or " from " not in f" {sql.lower()} ":
        return None  # bare scalar expression — nothing the AST probes can see
    notes: list[str] = []
    dialect = getattr(db, "dialect", "duckdb")
    try:
        from aughor.sql.fanout import measure_times_key_arithmetic
        w = measure_times_key_arithmetic(sql, dialect=dialect)
        if w:
            notes.append(f"id-arithmetic guard: {w}")
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "monitor id-arithmetic probe is advisory; alert proceeds",
                 counter="monitors.guard_idmath")
    try:
        from aughor.sql.fanout import detect_fanout, dimension_ratio_chasm
        from aughor.db.schema_render import parse_schema_tables
        tc = {t: (list(c.keys()) if isinstance(c, dict) else c)
              for t, c in parse_schema_tables(db.get_schema()).items()}
        if detect_fanout(sql, tc, dialect=dialect) or \
                dimension_ratio_chasm(sql, tc, dialect=dialect):
            notes.append(
                "fan-out guard: an aggregate over a one-to-many join may over- or "
                "under-count — verify the metric's grain before acting on this value")
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "monitor fan-out probe is advisory; alert proceeds",
                 counter="monitors.guard_fanout")
    return "; ".join(notes) or None


def _make_alert(
    monitor: Monitor,
    severity: str,
    message: str,
    current_value: Optional[float] = None,
    previous_value: Optional[float] = None,
    threshold: Optional[float] = None,
    alert_on: Optional[str] = None,
) -> MonitorAlert:
    return MonitorAlert(
        monitor_id=monitor.id,
        monitor_name=monitor.name,
        conn_id=monitor.conn_id,
        metric_name=monitor.metric_name,
        triggered_at=_now_iso(),
        alert_on=alert_on or monitor.alert_on,
        severity=severity,
        current_value=current_value,
        previous_value=previous_value,
        threshold=threshold,
        message=message,
    )


# ── M20a: Threshold / change monitors ─────────────────────────────────────────

def run_threshold_monitor(monitor: Monitor, db) -> Optional[MonitorAlert]:
    """Fire if the current metric value — for its period, when it names a dated metric — crosses warning_threshold or
    critical_threshold."""
    sql, dialect = _reading_sql(monitor, db)
    if not sql:
        logger.warning("Monitor %s (%s): no SQL resolved — skipping", monitor.id, monitor.name)
        return None

    current = _scalar(db, sql, dialect)
    if current is None:
        return None

    previous = _last_alert_value(monitor.id)
    direction = monitor.threshold_direction  # "below" or "above"

    # ONE rule, shared with the backtest (`monitors/rules.py`): critical first, then warning.
    from aughor.monitors.rules import threshold_verdict
    verdict = threshold_verdict(current, direction=direction, warning=monitor.warning_threshold,
                                critical=monitor.critical_threshold)
    if not verdict.fired or verdict.threshold is None:
        return None
    over = covered_words()
    period = f" for {over}" if over and not over.startswith("all history") else ""
    return _make_alert(
        monitor, verdict.severity,
        f"{monitor.name}: {plain_figure(current)}{period} {'below' if direction == 'below' else 'above'} "
        f"{verdict.severity} threshold {plain_figure(verdict.threshold)}",
        current_value=current, previous_value=previous,
        threshold=verdict.threshold,
    )


def run_any_change_monitor(monitor: Monitor, db) -> Optional[MonitorAlert]:
    """Fire whenever the metric value changes from its last recorded value."""
    sql, dialect = _reading_sql(monitor, db)
    if not sql:
        return None

    current = _scalar(db, sql, dialect)
    if current is None:
        return None

    previous = _last_alert_value(monitor.id)
    if previous is None:
        # First run — record baseline, no alert
        return _make_alert(
            monitor, "info",
            f"{monitor.name}: baseline recorded as {current:.4g}",
            current_value=current,
        )

    if abs(current - previous) < 1e-9:
        return None

    pct = ((current - previous) / previous * 100) if previous != 0 else float("inf")
    sign = "↑" if current > previous else "↓"
    return _make_alert(
        monitor, "info",
        f"{monitor.name}: {sign} {abs(pct):.1f}% change ({previous:.4g} → {current:.4g})",
        current_value=current, previous_value=previous,
    )


def run_trend_reversal_monitor(monitor: Monitor, db) -> Optional[MonitorAlert]:
    """Fire when the rolling direction of the metric flips (up→down or down→up)."""
    sql, dialect = _reading_sql(monitor, db)
    if not sql:
        return None

    current = _scalar(db, sql, dialect)
    if current is None:
        return None

    try:
        recent = _metric_alerts(monitor.id, 3)
    except Exception:
        return None

    if len(recent) < 2:
        return None

    # Direction of last two moves
    vals = [a.current_value for a in recent if a.current_value is not None]
    if len(vals) < 2:
        return None

    last_direction = vals[0] - vals[1]          # positive = was going up
    new_direction  = current - vals[0]           # positive = now going up

    if last_direction * new_direction < 0:       # sign flip
        trend = "upward" if new_direction > 0 else "downward"
        return _make_alert(
            monitor, "warning",
            f"{monitor.name}: trend reversed — now {trend} ({vals[0]:.4g} → {current:.4g})",
            current_value=current, previous_value=vals[0],
        )
    return None


# ── M20b: Anomaly monitor (z-score) ───────────────────────────────────────────

def _as_day(value):
    """A series row's first column as a date, or None when it is not one."""
    from datetime import date as _date, datetime as _dt
    if isinstance(value, _dt):
        return value.date()
    if isinstance(value, _date):
        return value
    try:
        return _date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _drop_unsettled(points: list, conn_id: str, *, today=None) -> list:
    """Idea 4 — the series without the days this source is still restating: every point
    younger than the connection's learned settling lag. Undated points are kept (nothing
    can say how old they are), and a connection with no learned lag keeps every point."""
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    try:
        from aughor.settling import learned_lag_days
        lag = learned_lag_days(conn_id or "")
    except Exception:
        lag = None
    if not lag:
        return points
    cutoff = (today or _dt.now(_tz.utc).date()) - _td(days=lag)
    return [(d, v) for d, v in points if d is None or d <= cutoff]


def run_anomaly_monitor(monitor: Monitor, db) -> Optional[MonitorAlert]:
    """Z-score anomaly detection on rolling history_days of daily metric values.

    Requires a time-series SQL: the monitor's SQL must return rows with columns
    (date, value).  Falls back to scalar z-score using stored alert history.
    """
    sql = _resolve_sql(monitor, db)
    if not sql:
        return None

    # Try to get a time-series (two-column result: date, value)
    history_values: list[float] = []
    current: Optional[float] = None

    try:
        rows = _query(db, sql)
        if rows and len(rows[0]) == 2:
            # Two-column time series
            points: list[tuple] = []
            for row in rows:
                vals = list(row.values()) if isinstance(row, dict) else list(row)
                if vals[0] is None:
                    continue                    # a row with no date has no place in the series
                day = _as_day(vals[0])
                if day is None:
                    raise SeriesUndated(
                        f"its query's first column is not a date (it read {str(vals[0])[:40]!r}); an anomaly "
                        f"check scores a daily series of (date, value) rows")
                try:
                    points.append((day, float(vals[1])))
                except (TypeError, ValueError):
                    pass
            points.sort(key=lambda p: p[0])     # the newest day is scored, whatever order the rows came in
            # Idea 4 — score the newest SETTLED day. A source that restates its recent days
            # (theLook: the youngest day reads ~8× what it settles at) would otherwise raise
            # an anomaly every morning on a day that has not finished arriving. Points younger
            # than the learned lag are dropped; with no learned lag the series reads as before.
            pairs = [v for _, v in _drop_unsettled(points, monitor.conn_id)]
            if pairs:
                history_values = pairs[:-1]
                current = pairs[-1]
        elif rows:
            # Scalar SQL — build history from stored alerts
            row = rows[0]
            val = list(row.values())[0] if isinstance(row, dict) else row[0]
            current = float(val) if val is not None else None
            try:
                past = _metric_alerts(monitor.id, monitor.history_days)
                history_values = [
                    a.current_value for a in past if a.current_value is not None
                ]
            except Exception:
                pass
    except QueryRefused:
        raise
    except Exception as exc:
        logger.debug("Anomaly monitor query failed: %s", exc)
        return None

    if current is None or len(history_values) < 5:
        # Not enough data — record as baseline
        if current is not None:
            return _make_alert(
                monitor, "info",
                f"{monitor.name}: anomaly baseline building ({len(history_values)} samples so far)",
                current_value=current,
            )
        return None

    # ONE rule, shared with the backtest and the Watcher's replay (`monitors/rules.py`):
    # a replay that scored days differently from this line would promise nothing.
    from aughor.monitors.rules import anomaly_verdict
    verdict = anomaly_verdict(history_values, current, monitor.sigma_threshold)
    if verdict.std < 1e-9:
        return None  # No variance — nothing to detect
    if verdict.fired:
        return _make_alert(
            monitor, verdict.severity,
            f"{monitor.name}: anomaly detected — {current:.4g} is {verdict.z:.1f}σ "
            f"{verdict.direction} rolling mean ({verdict.mean:.4g})",
            current_value=current, previous_value=verdict.mean,
        )
    return None


# ── M20b: Segment drift monitor (Chi-squared) ─────────────────────────────────

def run_drift_monitor(monitor: Monitor, db) -> Optional[MonitorAlert]:
    """Chi-squared test for distribution shift across monitor.dimension_column.

    The monitor SQL must return rows of (dimension_value, metric_value).
    We compare the current distribution against the distribution in stored
    alerts (baseline).  Fires when p-value < drift_p_threshold.
    """
    if not monitor.dimension_column:
        return None

    sql = _resolve_sql(monitor, db)
    if not sql:
        return None

    try:
        import numpy as np
    except ImportError:
        logger.warning("numpy not available — drift monitor skipped")
        return None

    try:
        rows = _query(db, sql)
    except QueryRefused:
        raise
    except Exception as exc:
        logger.debug("Drift monitor query failed: %s", exc)
        return None

    if not rows or len(rows[0]) < 2:
        return None

    # Build current distribution dict: {dimension_val: metric_total}
    current_dist: dict[str, float] = {}
    for row in rows:
        vals = list(row.values()) if isinstance(row, dict) else list(row)
        try:
            key = str(vals[0])
            val = float(vals[1]) if vals[1] is not None else 0.0
            current_dist[key] = current_dist.get(key, 0.0) + val
        except (TypeError, ValueError, IndexError):
            pass

    if len(current_dist) < 2:
        return None

    # Retrieve baseline from last alert that stored extra segment data
    # For simplicity: we record the current distribution as a baseline if none exists
    # and only fire from the second run onward.
    try:
        past = _metric_alerts(monitor.id, 1)
    except Exception:
        return None

    if not past:
        # First run — record baseline message, no alert
        return _make_alert(
            monitor, "info",
            f"{monitor.name}: segment baseline recorded for {monitor.dimension_column} "
            f"({len(current_dist)} segments)",
            current_value=float(sum(current_dist.values())),
        )

    # Build baseline distribution from last alert's message (simple heuristic)
    # For a proper implementation, we'd store segment snapshots separately.
    # Here we compare current vs. uniform distribution as a stand-in.
    segments = list(current_dist.keys())
    observed = np.array([current_dist[s] for s in segments], dtype=float)
    expected = np.full(len(segments), observed.mean())

    if expected.sum() < 1e-9:
        return None

    try:
        # One-sample chi-squared goodness-of-fit vs. uniform
        from scipy.stats import chisquare
        result = chisquare(f_obs=observed, f_exp=expected)
        p_value = float(result.pvalue)
    except Exception:
        return None

    if p_value < monitor.drift_p_threshold:
        top_segment = max(current_dist, key=lambda k: abs(current_dist[k] - observed.mean()))
        return _make_alert(
            monitor, "warning",
            f"{monitor.name}: segment drift detected across {monitor.dimension_column} "
            f"(p={p_value:.4f} < {monitor.drift_p_threshold}). "
            f"Top shifted segment: {top_segment} = {current_dist[top_segment]:.4g}",
            current_value=p_value,
        )
    return None


# ── M20b: Data freshness monitor ──────────────────────────────────────────────

def run_freshness_monitor(monitor: Monitor, db) -> Optional[MonitorAlert]:
    """Alert when MAX(updated_at) on freshness_table hasn't advanced within SLA."""
    if not monitor.freshness_table:
        return None

    col = monitor.freshness_column
    table = monitor.freshness_table
    sql = f"SELECT MAX({col}) AS latest_ts FROM {table}"

    try:
        rows = _query(db, sql)
        if not rows:
            return None
        row = rows[0]
        val = list(row.values())[0] if isinstance(row, dict) else row[0]
        if val is None:
            return _make_alert(
                monitor, "warning",
                f"{monitor.name}: {table}.{col} is NULL — table may be empty or not updating.",
            )
        # Parse timestamp
        if isinstance(val, str):
            latest_dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
        elif isinstance(val, datetime):
            latest_dt = val
        else:
            from datetime import date
            if isinstance(val, date):
                latest_dt = datetime(val.year, val.month, val.day, tzinfo=timezone.utc)
            else:
                return None

        if latest_dt.tzinfo is None:
            latest_dt = latest_dt.replace(tzinfo=timezone.utc)

        staleness_hours = (datetime.now(timezone.utc) - latest_dt).total_seconds() / 3600
        sla = monitor.freshness_sla_hours

        if staleness_hours > sla:
            severity = "critical" if staleness_hours > sla * 2 else "warning"
            return _make_alert(
                monitor, severity,
                f"{monitor.name}: {table} is stale — last update {staleness_hours:.1f}h ago "
                f"(SLA: {sla:.0f}h). Latest {col}: {val}",
                current_value=staleness_hours,
                threshold=sla,
            )
    except QueryRefused:
        raise
    except Exception as exc:
        logger.debug("Freshness monitor failed: %s", exc)

    return None


# ── Dispatcher ────────────────────────────────────────────────────────────────

@dataclass
class MonitorRun:
    """One check of a monitor: the alert it raised, or — when its query could not run — why."""
    alert: Optional[MonitorAlert] = None
    failed: str = ""      # the warehouse's refusal; "" when the query ran
    #: The value the check read (its first single value), raised or not; None when it read none.
    reading: Optional[float] = None
    #: What that reading covers, in words — its period, or "all history" and why; "" when nothing said it.
    covered: str = ""


def run_monitor(monitor: Monitor, db, suppress: bool = True) -> Optional[MonitorAlert]:
    """The alert a check raised, or None — including when its query could not run; `check_monitor` says
    which (GM-4). Kept for the callers that only deliver an alert (the drill, the receipts)."""
    return check_monitor(monitor, db, suppress).alert


def check_monitor(monitor: Monitor, db, suppress: bool = True) -> MonitorRun:
    """See ``_check_monitor``; this keeps the value the check read on the run it returns (Gap 36)."""
    token, over = _READINGS.set([]), _COVERED.set([])
    try:
        run = _check_monitor(monitor, db, suppress)
        read = _READINGS.get() or []
        if read and run.reading is None:
            run.reading = read[0]
        run.covered = run.covered or covered_words()
        return run
    finally:
        _READINGS.reset(token)
        _COVERED.reset(over)


def _check_monitor(monitor: Monitor, db, suppress: bool = True) -> MonitorRun:
    """Dispatch to the correct runner based on monitor.alert_on.

    Always safe — exceptions are caught and surfaced as info alerts so the
    scheduler never crashes. `suppress` applies the anti-flap debounce (default
    True for the cron path); the manual "test now" endpoint passes False so it
    always shows the raw verdict. A query the warehouse refused is a failed run,
    not an alert and not "no alert" (GM-4).
    """
    try:
        dispatch = {
            "threshold_cross": run_threshold_monitor,
            "any_change":      run_any_change_monitor,
            "trend_reversal":  run_trend_reversal_monitor,
            "anomaly":         run_anomaly_monitor,
            "segment_drift":   run_drift_monitor,
            "data_freshness":  run_freshness_monitor,
        }
        fn = dispatch.get(monitor.alert_on)
        if fn is None:
            logger.warning("Unknown alert_on '%s' for monitor %s", monitor.alert_on, monitor.id)
            return MonitorRun()
        alert = fn(monitor, db)
    except QueryRefused as exc:
        logger.warning("Monitor %s (%s): its query could not run: %s", monitor.id, monitor.name, exc)
        return MonitorRun(failed=str(exc) or "the warehouse refused the query")
    except Exception as exc:
        logger.error("Monitor %s (%s) runner crashed: %s", monitor.id, monitor.name, exc)
        alert = _make_alert(monitor, "info", f"{monitor.name}: runner error — {exc}")

    # WP-1b — guarded evaluation (unconditional since 2026-08-06, when the `monitors.guarded`
    # flag left the registry): attach any deterministic correctness finding on the monitor's
    # SQL to the fired alert.
    if alert is not None:
        try:
            _cav = _guard_caveats(monitor, db)
            if _cav:
                alert.caveat = _cav
        except Exception:
            logger.debug("monitor guard probes are best-effort; skipped", exc_info=True)

    # Anti-flap: debounce a repeat alert of the same-or-lower severity within the grace window.
    if suppress and alert is not None and _suppressed_by_grace(monitor, alert):
        logger.debug("Monitor %s (%s): %s alert suppressed (grace window)", monitor.id, monitor.name, alert.severity)
        return MonitorRun()
    return MonitorRun(alert=alert)


def failure_alert(monitor: Monitor, failed: str) -> MonitorAlert:
    """The alert that says a monitor's query could not run — and so that it is not watching."""
    return _make_alert(monitor, "warning",
                       f"{monitor.name}: its query could not run, so it is not being checked — {failed[:300]}",
                       alert_on=QUERY_FAILING)


def health_alert(monitor: Monitor, run: MonitorRun) -> Optional[MonitorAlert]:
    """The one alert a change in whether a monitor can run deserves (the user's call, 2026-09-29): when its query
    starts failing, and when it runs again — never one per failing tick. The alert store is the record: the newest
    of this monitor's alerts about running says which state it was last in."""
    from aughor.monitors.store import get_alerts
    try:
        last = next((a for a in get_alerts(monitor_id=monitor.id, limit=_SCAN) if a.alert_on in _HEALTH), None)
    except Exception:
        last = None
    was_failing = last is not None and last.alert_on == QUERY_FAILING
    if run.failed and not was_failing:
        return failure_alert(monitor, run.failed)
    if not run.failed and was_failing:
        return _make_alert(monitor, "info", f"{monitor.name}: its query runs again; checking has resumed.",
                           alert_on=QUERY_RUNS_AGAIN)
    return None
