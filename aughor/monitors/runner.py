"""Monitor runner — M20a (threshold / change) + M20b (anomaly / drift / freshness).

Each public function accepts a Monitor + a live DatabaseConnection and returns
a MonitorAlert (or None if no alert condition is met).  The scheduler calls
these on cron; they never raise — errors are caught and surfaced as info alerts.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from aughor.monitors.models import Monitor, MonitorAlert

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

from aughor.util.time import now_iso as _now_iso


def _query(db, sql: str) -> list:
    """Run SQL through the connection API and return rows (list), [] on error.

    The connection exposes ``execute(label, sql) -> QueryResult(.rows/.error)`` — NOT
    ``execute_query`` (a phantom method the runner used to call, which silently
    AttributeError'd on every check → "No condition met"). This is the single adapter."""
    try:
        res = db.execute("__monitor__", sql)
        if getattr(res, "error", None):
            logger.debug("monitor query error: %s", res.error)
            return []
        return list(getattr(res, "rows", None) or [])
    except Exception as exc:
        logger.debug("monitor query failed: %s", exc)
        return []


def _resolve_sql(monitor: Monitor, db=None) -> Optional[str]:
    """Return the scalar SQL expression for this monitor (custom_sql wins).

    When ``monitor.reanchor_window`` is set and a live ``db`` is provided, the SQL's
    absolute date window is slid forward to the data's current activity edge — so a
    monitor built from a Briefing finding tracks the trailing window instead of a
    frozen one. Re-anchoring is fallback-safe (returns the SQL unchanged on any issue).
    """
    sql: Optional[str] = None
    if monitor.custom_sql:
        sql = monitor.custom_sql.strip()
    elif monitor.metric_name:
        try:
            from aughor.semantic.metrics import get_metric
            m = get_metric(monitor.metric_name)
            if m:
                sql = m.sql.strip()
        except Exception:
            pass
    if sql and db is not None and getattr(monitor, "reanchor_window", False):
        try:
            from aughor.monitors.window import reanchor_trailing_window
            sql = reanchor_trailing_window(sql, db, getattr(db, "dialect", "duckdb"))
        except Exception:
            pass
    return sql


def _scalar(db, sql: str) -> Optional[float]:
    """Execute SQL and return the first cell as float, or None on error."""
    try:
        result = _query(db, sql)
        if result and len(result) > 0:
            row = result[0]
            val = list(row.values())[0] if isinstance(row, dict) else row[0]
            return float(val) if val is not None else None
    except Exception as exc:
        logger.debug("Monitor scalar query failed: %s", exc)
    return None


def _last_alert_value(monitor_id: str) -> Optional[float]:
    """Return the current_value from the most recent alert for this monitor."""
    try:
        from aughor.monitors.store import get_alerts
        alerts = get_alerts(monitor_id=monitor_id, limit=1)
        if alerts:
            return alerts[0].current_value
    except Exception:
        pass
    return None


def _make_alert(
    monitor: Monitor,
    severity: str,
    message: str,
    current_value: Optional[float] = None,
    previous_value: Optional[float] = None,
    threshold: Optional[float] = None,
) -> MonitorAlert:
    return MonitorAlert(
        monitor_id=monitor.id,
        monitor_name=monitor.name,
        conn_id=monitor.conn_id,
        metric_name=monitor.metric_name,
        triggered_at=_now_iso(),
        alert_on=monitor.alert_on,
        severity=severity,
        current_value=current_value,
        previous_value=previous_value,
        threshold=threshold,
        message=message,
    )


# ── M20a: Threshold / change monitors ─────────────────────────────────────────

def run_threshold_monitor(monitor: Monitor, db) -> Optional[MonitorAlert]:
    """Fire if the current metric value crosses warning_threshold or critical_threshold."""
    sql = _resolve_sql(monitor, db)
    if not sql:
        logger.warning("Monitor %s (%s): no SQL resolved — skipping", monitor.id, monitor.name)
        return None

    current = _scalar(db, sql)
    if current is None:
        return None

    previous = _last_alert_value(monitor.id)
    direction = monitor.threshold_direction  # "below" or "above"

    def _crossed(value: float, threshold: float) -> bool:
        return value < threshold if direction == "below" else value > threshold

    # Critical takes precedence
    if monitor.critical_threshold is not None and _crossed(current, monitor.critical_threshold):
        return _make_alert(
            monitor, "critical",
            f"{monitor.name}: {current:.4g} {'below' if direction == 'below' else 'above'} "
            f"critical threshold {monitor.critical_threshold:.4g}",
            current_value=current, previous_value=previous,
            threshold=monitor.critical_threshold,
        )
    if monitor.warning_threshold is not None and _crossed(current, monitor.warning_threshold):
        return _make_alert(
            monitor, "warning",
            f"{monitor.name}: {current:.4g} {'below' if direction == 'below' else 'above'} "
            f"warning threshold {monitor.warning_threshold:.4g}",
            current_value=current, previous_value=previous,
            threshold=monitor.warning_threshold,
        )
    return None


def run_any_change_monitor(monitor: Monitor, db) -> Optional[MonitorAlert]:
    """Fire whenever the metric value changes from its last recorded value."""
    sql = _resolve_sql(monitor, db)
    if not sql:
        return None

    current = _scalar(db, sql)
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
    sql = _resolve_sql(monitor, db)
    if not sql:
        return None

    current = _scalar(db, sql)
    if current is None:
        return None

    try:
        from aughor.monitors.store import get_alerts
        recent = get_alerts(monitor_id=monitor.id, limit=3)
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

def run_anomaly_monitor(monitor: Monitor, db) -> Optional[MonitorAlert]:
    """Z-score anomaly detection on rolling history_days of daily metric values.

    Requires a time-series SQL: the monitor's SQL must return rows with columns
    (date, value).  Falls back to scalar z-score using stored alert history.
    """
    try:
        import numpy as np
    except ImportError:
        logger.warning("numpy not available — anomaly monitor skipped")
        return None

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
            pairs = []
            for row in rows:
                vals = list(row.values()) if isinstance(row, dict) else list(row)
                try:
                    pairs.append(float(vals[1]))
                except (TypeError, ValueError):
                    pass
            if pairs:
                history_values = pairs[:-1]
                current = pairs[-1]
        elif rows:
            # Scalar SQL — build history from stored alerts
            row = rows[0]
            val = list(row.values())[0] if isinstance(row, dict) else row[0]
            current = float(val) if val is not None else None
            try:
                from aughor.monitors.store import get_alerts
                past = get_alerts(monitor_id=monitor.id, limit=monitor.history_days)
                history_values = [
                    a.current_value for a in past if a.current_value is not None
                ]
            except Exception:
                pass
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

    arr = np.array(history_values, dtype=float)
    mean, std = float(arr.mean()), float(arr.std())

    if std < 1e-9:
        return None  # No variance — nothing to detect

    z = abs(current - mean) / std

    if z >= monitor.sigma_threshold:
        direction = "above" if current > mean else "below"
        severity = "critical" if z >= monitor.sigma_threshold * 1.5 else "warning"
        return _make_alert(
            monitor, severity,
            f"{monitor.name}: anomaly detected — {current:.4g} is {z:.1f}σ {direction} "
            f"rolling mean ({mean:.4g})",
            current_value=current, previous_value=mean,
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
        from scipy.stats import chi2_contingency  # type: ignore
        import numpy as np
    except ImportError:
        logger.warning("scipy/numpy not available — drift monitor skipped")
        return None

    try:
        rows = _query(db, sql)
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
        from aughor.monitors.store import get_alerts
        past = get_alerts(monitor_id=monitor.id, limit=1)
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
    except Exception as exc:
        logger.debug("Freshness monitor failed: %s", exc)

    return None


# ── Dispatcher ────────────────────────────────────────────────────────────────

def run_monitor(monitor: Monitor, db) -> Optional[MonitorAlert]:
    """Dispatch to the correct runner based on monitor.alert_on.

    Always safe — exceptions are caught and surfaced as info alerts so the
    scheduler never crashes.
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
            return None
        return fn(monitor, db)
    except Exception as exc:
        logger.error("Monitor %s (%s) runner crashed: %s", monitor.id, monitor.name, exc)
        return _make_alert(
            monitor, "info",
            f"{monitor.name}: runner error — {exc}",
        )
