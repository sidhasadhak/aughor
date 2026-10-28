"""Alerts that close — Arc TC, TC-4 (ROADMAP §3.59).

Before this, an alert opened and never closed: the only way out of "open" was a person's Acknowledge, so a metric that
came back the next hour read as a live alert for as long as nobody clicked, and nothing recorded that it came back.

**What closes.** An alert is *open* until a later check of its monitor reads the metric back within its limit. That
check writes ONE alert of kind ``recovered``: it names the alert it closes (its severity, when it fired and what it
read) and carries the value that came back. Every alert of that monitor before the recovery is closed by it, so an
alert that escalated from warning to critical and then recovered reads as one closed episode. A second check within
its limit writes nothing more (the newest alert is the recovery, so nothing is open). The next alert after a recovery
opens a new episode, and the grace period does not hold it back, because the alert it was folding repeats of is closed.

**What counts.** Only an alert whose rule has a limit — a threshold, an anomaly, a drift, a freshness — at warning or
critical. A change monitor and a trend monitor fire on an event, not a state, so nothing comes back for them; an
information alert (a baseline, a runner error) and the two alerts about whether a monitor can run are never closed.

**Where the record is.** A recovery is a row in ``monitor_alerts`` like any alert — no new store and no new column. Which
alert a recovery closes is read back by one rule (:func:`links`) over the rows in time order, and its id is derived
from the alert it closes, so two checks racing to close one alert write one row (``INSERT OR IGNORE`` on the id).

**Not sent.** A recovery goes nowhere but this platform. Sending it "only where the alert went out" would need to know
where a given alert went, and neither record of a send can say: the send log keys it by monitor
(``investigation_id = monitor:<id>``) and the departure record by its source, the monitor — never by alert.
:func:`aughor.monitors.notify.dispatch_alert` therefore records a recovery and sends nothing — and opens no inquiry,
since nothing moved that needs asking about — and the run says so. An alert summary, which goes through
the departure gate as a whole, lists a recovery beside the alerts it closes and never counts it as one.
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Iterable, Optional

if TYPE_CHECKING:                                  # pragma: no cover
    from aughor.monitors.models import Monitor, MonitorAlert
    from aughor.monitors.runner import MonitorRun

#: The kind (``alert_on``) of the alert a recovery writes.
RECOVERED = "recovered"
#: The rules with a limit a reading can come back within.
LIMIT_KINDS = frozenset({"threshold_cross", "anomaly", "segment_drift", "data_freshness"})
_OPENING = frozenset({"warning", "critical"})
#: How far back the open alert is looked for.
_SCAN = 200
_NAMESPACE = uuid.UUID("6f0c4d0e-1c4a-4f0e-9a51-7c2b2d5e7a14")


def _opens(alert_on: str, severity: str) -> bool:
    return alert_on in LIMIT_KINDS and severity in _OPENING


def opens(alert: "MonitorAlert") -> bool:
    """Whether ``alert`` is one a recovery closes: a warning or critical from a rule with a limit — never an
    information alert, a change or trend alert, or an alert about whether the monitor could run."""
    return _opens(alert.alert_on, alert.severity)


def _history(monitor_id: str) -> list["MonitorAlert"]:
    """This monitor's alerts, newest first."""
    from aughor.monitors.store import get_alerts
    return get_alerts(monitor_id=monitor_id, limit=_SCAN)


def open_alert(monitor_id: str) -> Optional["MonitorAlert"]:
    """The newest alert of this monitor no recovery has closed, or None — what the next check within its limit closes."""
    for a in _history(monitor_id):
        if a.alert_on == RECOVERED:
            return None
        if opens(a):
            return a
    return None


def recovered_after(monitor_id: str, alert: "MonitorAlert") -> bool:
    """Whether a recovery of this monitor is newer than ``alert``."""
    return any(a.alert_on == RECOVERED and a.triggered_at > alert.triggered_at for a in _history(monitor_id))


def recovery_id(closed: "MonitorAlert") -> str:
    """The one id a recovery of ``closed`` can have — so a second write of it is the same row, not a second recovery."""
    return str(uuid.uuid5(_NAMESPACE, closed.id))


def closes_words(closed: "MonitorAlert") -> str:
    """"closes the warning alert of 2026-10-25 09:00 UTC, which read 848,860.1" — the alert a recovery closes, named."""
    from aughor.monitors.runner import plain_figure
    when = f"{closed.triggered_at[:16].replace('T', ' ')} UTC" if closed.triggered_at else "an earlier check"
    was = f", which read {plain_figure(closed.current_value)}" if closed.current_value is not None else ""
    return f"closes the {closed.severity} alert of {when}{was}"


def recovery_alert(monitor: "Monitor", run: "MonitorRun") -> Optional[tuple["MonitorAlert", "MonitorAlert"]]:
    """``(recovery, the alert it closes)`` — the one alert a check back within its limit writes when an alert of its
    monitor is open — or None: a check not within its limit, or nothing open."""
    from aughor.monitors.models import MonitorAlert
    from aughor.monitors.runner import WITHIN, plain_figure, reading_words
    from aughor.util.time import now_iso
    if run.outcome != WITHIN:      # only a rule with a limit judges a value within it
        return None
    closed = open_alert(monitor.id)
    if closed is None:
        return None
    value = run.judged if run.judged is not None else run.reading
    read = (reading_words(monitor, run) or run.judged_words
            or (f"read {plain_figure(value)}" if value is not None else "read a value within it"))
    closes = closes_words(closed)
    return MonitorAlert(
        id=recovery_id(closed), monitor_id=monitor.id, monitor_name=monitor.name, conn_id=monitor.conn_id,
        metric_name=monitor.metric_name, triggered_at=now_iso(), alert_on=RECOVERED, severity="info",
        current_value=value, previous_value=closed.current_value, threshold=closed.threshold,
        message=f"{monitor.name}: back within its limit — {read}. {closes[:1].upper()}{closes[1:]}.",
    ), closed


def links(monitor_ids: Iterable[str]) -> tuple[dict[str, tuple[str, str]], dict[str, str]]:
    """Which alerts each recovery of these monitors closed, by the one rule: a recovery closes every alert of its
    monitor that opened since the previous recovery. ``(closed_by, closes)``: an alert's id → ``(recovery id, when)``,
    and a recovery's id → the newest alert it closed (the one its message names)."""
    from aughor.monitors.store import alert_timeline
    closed_by: dict[str, tuple[str, str]] = {}
    closes: dict[str, str] = {}
    pending: dict[str, list[str]] = {}
    for row in alert_timeline(sorted(set(monitor_ids))):
        mid = row["monitor_id"]
        if row["alert_on"] == RECOVERED:
            waiting = pending.pop(mid, [])
            for aid in waiting:
                closed_by[aid] = (row["id"], row["triggered_at"])
            if waiting:
                closes[row["id"]] = waiting[-1]
        elif _opens(row["alert_on"], row["severity"]):
            pending.setdefault(mid, []).append(row["id"])
    return closed_by, closes


def annotate(alerts: list[dict]) -> list[dict]:
    """The alert rows a route returns, each closed alert carrying ``closed_by`` and ``closed_at`` and each recovery
    ``closes``."""
    if not alerts:
        return alerts
    closed_by, closes = links(a.get("monitor_id", "") for a in alerts)
    out = []
    for a in alerts:
        if a.get("id") in closed_by:
            rid, at = closed_by[a["id"]]
            a = {**a, "closed_by": rid, "closed_at": at}
        elif a.get("id") in closes:
            a = {**a, "closes": closes[a["id"]]}
        out.append(a)
    return out


def still_open(unacknowledged: list["MonitorAlert"]) -> list["MonitorAlert"]:
    """Of alerts no person has acknowledged, the ones still waiting on one: never a recovery, and never an alert a
    recovery closed."""
    waiting = [a for a in unacknowledged if getattr(a, "alert_on", "") != RECOVERED]
    if not waiting:
        return waiting
    closed_by, _ = links(getattr(a, "monitor_id", "") for a in waiting)
    return [a for a in waiting if getattr(a, "id", None) not in closed_by]
