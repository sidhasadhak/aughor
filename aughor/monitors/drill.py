"""Idea 6, second half · fire drills: prove the alert path still works.

An alert that never fires looks exactly like a broken one. A drill feeds the monitor a
made-up series — thirty quiet days and a ten-σ outlier on the newest settled day — through
the runner it actually runs with, WITHOUT touching the warehouse (a stand-in connection
serves the rows), and then delivers the alert it produced through the real channel, marked
"[DRILL]" so nobody acts on it. What a drill proves: the rule fires, the departure gate
passes a monitor alert, the trigger is configured and reachable, the message lands. What
it does NOT prove: the monitor's own SQL — the stand-in never runs it. That is the
backtest's job, and the two together are the alert's proof.

The drill never files an alert (`append_alert`): a fake value in the alert history would
feed the anti-flap window, the any_change and trend baselines and the anomaly scalar
history — the exact corruption a drill exists to avoid. Its record is its own store,
keyed by monitor, read back as "last proven working".
"""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from aughor.monitors.models import Monitor, MonitorAlert

#: The quiet run-in before the outlier, and how far the outlier stands from it.
QUIET_DAYS = 30
OUTLIER_SIGMAS = 10.0
DRILL_PREFIX = "[DRILL]"


class DrillConnection:
    """A stand-in for the warehouse connection: the runner's reads answered from a synthetic
    series, every write refused. `rows` serves (day, value) pairs — quiet, then the outlier
    on the newest settled day; `scalar` serves the outlier alone, which is what a threshold
    monitor reads."""
    dialect = "duckdb"
    writes_native_sql = False

    def __init__(self, monitor: Monitor, *, today: Optional[date] = None, settle_days: int = 1) -> None:
        today = today or datetime.now(timezone.utc).date()
        last = today - timedelta(days=max(1, settle_days))
        base, noise = 100.0, 2.0
        self.series: list[tuple[str, float]] = []
        for i in range(QUIET_DAYS, 0, -1):
            d = last - timedelta(days=i)
            self.series.append((d.isoformat(), base + noise * ((i % 3) - 1)))
        outlier = base + OUTLIER_SIGMAS * noise * 2
        if monitor.alert_on == "threshold_cross":
            line = monitor.critical_threshold if monitor.critical_threshold is not None else monitor.warning_threshold
            if line is not None:
                outlier = line - 1.0 if monitor.threshold_direction == "below" else line + 1.0
        self.series.append((last.isoformat(), outlier))
        self.outlier = outlier
        self.queries: list[str] = []

    def rows(self, sql: str, label: str = "") -> list:
        self.queries.append(sql)
        return [tuple(p) for p in self.series]

    def scalar(self, sql: str, label: str = "", cast=float):
        self.queries.append(sql)
        return cast(self.outlier) if cast else self.outlier

    def get_schema(self):
        return {}

    def execute(self, *_a, **_k):
        raise RuntimeError("a drill never runs SQL against a warehouse")

    def close(self) -> None:
        return None


@dataclass
class Drill:
    monitor_id: str
    at: str
    fired: bool
    delivered: Optional[bool]        # None when delivery was not attempted
    detail: str
    severity: str = ""
    message: str = ""
    channel: str = ""
    delivery_log_id: str = ""

    @property
    def proven(self) -> bool:
        return self.fired and self.delivered is True


def _path() -> Path:
    from aughor.db.paths import state_dir
    return state_dir() / "monitor_drills.json"


def _store():
    from aughor.util.json_store import KeyedJsonStore
    return KeyedJsonStore(_path())


def last_drill(monitor_id: str) -> Optional[Drill]:
    raw = _store().get(monitor_id)
    if not isinstance(raw, dict):
        return None
    try:
        return Drill(**{k: raw.get(k) for k in Drill.__dataclass_fields__})
    except TypeError:
        return None


def drill_monitor(monitor: Monitor, *, deliver: bool = True, today: Optional[date] = None,
                  settle_days: Optional[int] = None) -> Drill:
    """Run the monitor on the synthetic series and, when asked, deliver the alert it
    produced through its real channel with the drill prefix. Records the result."""
    from aughor.monitors.runner import run_monitor
    if settle_days is None:
        try:
            from aughor.settling import learned_lag_days
            settle_days = learned_lag_days(monitor.conn_id) or 1
        except Exception:
            settle_days = 1
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    db = DrillConnection(monitor, today=today, settle_days=settle_days)
    alert = run_monitor(monitor, db, suppress=False)
    if alert is None or alert.severity == "info":
        drill = Drill(monitor.id, now, fired=False, delivered=None,
                      detail=(f"the rule did not fire on a synthetic {OUTLIER_SIGMAS:g}σ outlier"
                              + (f" ({alert.message})" if alert is not None else "")),
                      channel=monitor.notification_channel)
        _store().put(monitor.id, asdict(drill))
        return drill
    message = f"{DRILL_PREFIX} {alert.message} — a synthetic outlier proving the alert path; nothing in the data moved"
    alert = alert.model_copy(update={"id": f"drill-{uuid.uuid4().hex[:12]}", "message": message})
    channel = monitor.notification_channel or "in_app"
    if not deliver:
        drill = Drill(monitor.id, now, fired=True, delivered=None, severity=alert.severity,
                      message=message, channel=channel,
                      detail=f"the rule fired ({alert.severity}); delivery not attempted")
    elif channel == "in_app":
        drill = Drill(monitor.id, now, fired=True, delivered=None, severity=alert.severity,
                      message=message, channel=channel,
                      detail="the rule fired; this monitor alerts in-app only, so there is no transport to prove")
    else:
        from aughor.monitors.notify import dispatch_alert
        log = dispatch_alert(alert, monitor)
        if log is None:
            drill = Drill(monitor.id, now, fired=True, delivered=False, severity=alert.severity,
                          message=message, channel=channel,
                          detail=f"the rule fired but nothing was sent: trigger {channel!r} is unknown, "
                                 f"disabled, or the departure gate held the drill")
        else:
            status = str(getattr(log, "status", "") or "")
            drill = Drill(monitor.id, now, fired=True, delivered=(status == "ok"),
                          severity=alert.severity, message=message, channel=channel,
                          delivery_log_id=str(getattr(log, "id", "") or ""),
                          detail=(f"delivered through trigger {channel!r}" if status == "ok"
                                  else f"the send failed: {getattr(log, 'error', '') or status}"))
    _store().put(monitor.id, asdict(drill))
    return drill


def proof(monitor: Monitor) -> dict:
    """"Last proven working" for one monitor: the last drill, the last real delivery, and
    the sentence a card shows."""
    drill = last_drill(monitor.id)
    last_real = None
    try:
        from aughor.notifications.store import list_logs
        mine = [log for log in list_logs(limit=500) if log.get("investigation_id") == f"monitor:{monitor.id}"]
        oks = [log for log in mine if log.get("status") == "ok"]
        if oks:
            last_real = max(oks, key=lambda log: str(log.get("fired_at", "")))
    except Exception:
        last_real = None
    if drill is not None and drill.proven:
        sentence = f"last proven working {drill.at} (drill delivered through {drill.channel})"
    elif last_real is not None:
        sentence = f"last delivered a real alert {last_real.get('fired_at', '')}; never drilled"
    elif drill is not None and drill.fired:
        sentence = f"the rule fired in a drill on {drill.at}; delivery {'not attempted' if drill.delivered is None else 'failed'}"
    elif drill is not None:
        sentence = f"drill on {drill.at} did not fire: {drill.detail}"
    else:
        sentence = "never proven — no drill, no delivered alert"
    return {"monitor_id": monitor.id, "sentence": sentence,
            "last_drill": asdict(drill) if drill is not None else None,
            "last_real_delivery": last_real}
