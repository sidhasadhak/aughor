"""VA-6 — alerts on what the AGENTS are doing, not on what the data says.

Monitors already watch the warehouse: a KPI moves, a threshold trips, something is
delivered outward through a trigger. Every part of that machinery is reusable and none of
it was ever pointed at the fleet, so an agent could fail sixty times an hour in silence.
This module is the missing half — the metrics, the rule, and the verdict. Delivery is the
monitors' existing path; nothing here re-implements a channel.

Three decisions that shape the whole file:

**Unknown is never zero.** A window with no runs in it does not have a 0% error rate; it
has no error rate. Returning 0.0 would make "nothing happened" indistinguishable from
"everything succeeded", and a quiet Sunday would silence an alert that should have fired
on Monday's first failure. A metric with no population returns ``None`` and the rule
declines to fire, saying so.

**A ratio's denominator holds only things that could have had the property.** Error rate
divides by runs that REACHED a terminal state — a run still in flight has not failed, and
counting it drags the rate down exactly when a slow failure is happening. This repo has
had a proxy substituted for a real measure five times; this is the shape it takes.

**Firing is not the same as notifying.** ``debounce_minutes`` is what stops one bad
deploy sending sixty messages. It is part of the RULE rather than the delivery layer,
because "alert me at most every 30 minutes" is a statement about the alert, and the
channel should not have to know it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field

#: What a rule can watch. Each is computed over one window from stores that already exist.
Metric = Literal[
    "error_rate",        # failed / terminal runs        (ratio 0..1)
    "failed_runs",       # absolute count
    "runs_started",      # absolute count — catches a fleet that has gone quiet
    "p95_duration_ms",   # latency
    "tokens",            # burn over the window
    "cost_usd",          # spend over the window
    "unmetered_runs",    # runs whose spend we cannot see — coverage, not cost
    "guardrail_blocks",     # absolute count of guardrail BLOCKS  (VA-8)
    "guardrail_block_rate", # blocked / evaluated                 (ratio 0..1)
]

Comparator = Literal["gt", "gte", "lt", "lte"]

#: States that mean a run is over. Only these belong in an error-rate denominator.
TERMINAL_STATES = frozenset({"SUCCEEDED", "FAILED", "INTERRUPTED", "CANCELLED"})
#: A restart-orphaned run is an infrastructure fact, not an agent error. Agent Ops already
#: splits these out of its error tile; an alert that conflated them would page a human at
#: 3am for a redeploy.
ORPHAN_STATES = frozenset({"INTERRUPTED"})


class AgentAlertRule(BaseModel):
    """One thing worth being told about."""

    id: str = ""
    name: str
    metric: Metric
    comparator: Comparator = "gt"
    threshold: float
    #: The window each evaluation looks back over.
    window_minutes: int = Field(default=15, ge=1, le=10_080)
    #: Never notify more often than this, however long the condition persists. The
    #: reference product calls it "wait at least"; it is the difference between an alert
    #: and a pager storm.
    debounce_minutes: int = Field(default=30, ge=0, le=1_440)
    #: Narrow to one agent/charter. Empty = the whole fleet.
    agent_id: str = ""
    charter_id: str = ""
    #: How often the rule is EVALUATED, as cron — distinct from ``window_minutes``, which is
    #: how far back each evaluation looks. Same field and default shape as ``Monitor.check_cron``,
    #: because a rule reaches the heartbeat the same way a monitor does: adopted as a virtual
    #: automation whose ``schedule`` condition reads this cron. There is one loop in this
    #: platform and this is how work joins it.
    check_cron: str = "*/5 * * * *"
    #: A notification trigger id (Action Hub). Empty = in-app only.
    channel: str = ""
    severity: Literal["info", "warning", "critical"] = "warning"
    enabled: bool = True
    #: Set when this rule last NOTIFIED (not merely matched) — the debounce clock.
    last_notified_at: Optional[str] = None


@dataclass
class Verdict:
    """The result of evaluating one rule once."""

    rule_id: str
    metric: str
    #: The measured value, or None when the window had no population to measure.
    value: Optional[float]
    #: True when the value crosses the threshold.
    matched: bool
    #: True when it matched AND the debounce allows a notification now.
    should_notify: bool
    #: Population the value came from — an alert that cannot say its denominator is a
    #: number nobody can check.
    population: int = 0
    reason: str = ""
    observed: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"rule_id": self.rule_id, "metric": self.metric, "value": self.value,
                "matched": self.matched, "should_notify": self.should_notify,
                "population": self.population, "reason": self.reason,
                "observed": self.observed}


class AgentAlertEvent(BaseModel):
    """A rule that fired, recorded. The row Attention reads and delivery quotes.

    Persisted BEFORE any send is attempted, and ``delivered`` is stamped afterwards, so a
    channel that is down leaves a visible alert rather than nothing at all — the same
    ordering monitor alerts use, for the same reason: the row is the source of truth and
    delivery is a best-effort consequence of it.

    ``value``/``threshold``/``population`` travel with the event instead of being looked up
    from the rule later. A rule is editable; an alert is a statement about a moment, and it
    has to keep meaning what it meant after somebody raises the threshold.
    """

    id: str = ""
    rule_id: str
    rule_name: str = ""
    metric: str = ""
    severity: str = "warning"
    fired_at: str = ""
    value: Optional[float] = None
    threshold: Optional[float] = None
    population: int = 0
    window_minutes: int = 0
    reason: str = ""
    observed: dict = Field(default_factory=dict)
    delivered: bool = False
    delivery_detail: str = ""
    acknowledged: bool = False
    acknowledged_at: Optional[str] = None
    org_id: str = ""


def event_from_verdict(rule: AgentAlertRule, verdict: Verdict, *, fired_at: str) -> AgentAlertEvent:
    """The verdict, frozen into the row that outlives it."""
    return AgentAlertEvent(
        rule_id=rule.id, rule_name=rule.name, metric=rule.metric, severity=rule.severity,
        fired_at=fired_at, value=verdict.value, threshold=rule.threshold,
        population=verdict.population, window_minutes=rule.window_minutes,
        reason=verdict.reason, observed=dict(verdict.observed))


def _pct(values: list[float], q: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))
    return round(ordered[idx], 3)


def measure(metric: Metric, jobs: list[dict], *, calls: Optional[list[dict]] = None,
            guardrails: Optional[list[dict]] = None
            ) -> tuple[Optional[float], int, dict]:
    """Compute one metric over a window's rows. Returns ``(value, population, observed)``.

    ``value is None`` means the window had nothing that could have carried this metric —
    which is different from the metric being zero, and the caller must not flatten them.
    """
    calls = calls or []
    guardrails = guardrails or []

    if metric in ("guardrail_blocks", "guardrail_block_rate"):
        # The population is EVALUATIONS, not runs. A guardrail that was never consulted
        # cannot have blocked anything, so counting it in the denominator would make an
        # unguarded fleet look compliant — the ratio rule this codebase keeps relearning:
        # a denominator may contain only things that could have had the property.
        blocked = [g for g in guardrails if g.get("blocked")]
        observed = {"evaluated": len(guardrails), "blocked": len(blocked)}
        if metric == "guardrail_blocks":
            return float(len(blocked)), len(guardrails), observed
        if not guardrails:
            # Nothing was evaluated. Not a 0% block rate — no block rate.
            return None, 0, observed
        return round(len(blocked) / len(guardrails), 4), len(guardrails), observed

    if metric == "runs_started":
        return float(len(jobs)), len(jobs), {"runs": len(jobs)}

    if metric in ("error_rate", "failed_runs"):
        terminal = [j for j in jobs if (j.get("state") or "") in TERMINAL_STATES]
        failed = [j for j in terminal
                  if (j.get("state") or "") == "FAILED"]
        orphaned = [j for j in terminal if (j.get("state") or "") in ORPHAN_STATES]
        observed = {"terminal": len(terminal), "failed": len(failed),
                    "orphaned_excluded": len(orphaned)}
        if metric == "failed_runs":
            return float(len(failed)), len(terminal), observed
        if not terminal:
            # No run finished in this window. Not a 0% error rate — no error rate.
            return None, 0, observed
        return round(len(failed) / len(terminal), 4), len(terminal), observed

    if metric == "p95_duration_ms":
        durations = [float(j["duration_ms"]) for j in jobs
                     if j.get("duration_ms") is not None]
        return _pct(durations, 0.95), len(durations), {"measured_runs": len(durations)}

    if metric == "unmetered_runs":
        terminal = [j for j in jobs if (j.get("state") or "") in TERMINAL_STATES]
        unmetered = [j for j in terminal
                     if not (isinstance(j.get("metrics"), dict)
                             and j["metrics"].get("total_tokens") is not None)]
        return float(len(unmetered)), len(terminal), {"terminal": len(terminal),
                                                      "unmetered": len(unmetered)}

    if metric == "tokens":
        total = 0
        seen = 0
        for j in jobs:
            m = j.get("metrics")
            if isinstance(m, dict) and m.get("total_tokens") is not None:
                total += int(m["total_tokens"] or 0)
                seen += 1
        if not seen:
            return None, 0, {"metered_runs": 0}
        return float(total), seen, {"metered_runs": seen}

    if metric == "cost_usd":
        total = 0.0
        priced = 0
        for c in calls:
            usd = c.get("cost_usd")
            if usd is not None:
                total += float(usd)
                priced += 1
        if not priced:
            # Every call unpriced is a COVERAGE fact, not a $0 bill. Saying zero here is
            # the "unknown is never zero" failure in its most expensive form.
            return None, 0, {"priced_calls": 0, "calls": len(calls)}
        return round(total, 6), priced, {"priced_calls": priced, "calls": len(calls)}

    raise ValueError(f"unknown metric: {metric}")


def _crosses(value: float, comparator: Comparator, threshold: float) -> bool:
    if comparator == "gt":
        return value > threshold
    if comparator == "gte":
        return value >= threshold
    if comparator == "lt":
        return value < threshold
    return value <= threshold


def _parse(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    s = str(ts).strip().replace(" ", "T")
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def debounce_allows(rule: AgentAlertRule, now: datetime) -> bool:
    """False while the rule is inside its quiet period."""
    if rule.debounce_minutes <= 0:
        return True
    last = _parse(rule.last_notified_at)
    if last is None:
        return True
    return now - last >= timedelta(minutes=rule.debounce_minutes)


def evaluate(rule: AgentAlertRule, jobs: list[dict], *,
             calls: Optional[list[dict]] = None,
             guardrails: Optional[list[dict]] = None,
             now: Optional[datetime] = None) -> Verdict:
    """Evaluate one rule against one window's rows."""
    now = now or datetime.now(timezone.utc)

    if not rule.enabled:
        return Verdict(rule.id, rule.metric, None, False, False,
                       reason="rule is disabled")

    scoped = jobs
    if rule.agent_id:
        scoped = [j for j in scoped if j.get("agent_id") == rule.agent_id]
    if rule.charter_id:
        scoped = [j for j in scoped
                  if (j.get("charter_id") or j.get("_charter")) == rule.charter_id]

    # Guardrail rows carry their own agent attribution and are not job rows, so the
    # rule's agent scope has to be applied to them here rather than inherited from
    # `scoped` — an agent-scoped rule reading every agent's blocks would fire on somebody
    # else's traffic.
    scoped_guardrails = guardrails
    if scoped_guardrails and rule.agent_id:
        scoped_guardrails = [g for g in scoped_guardrails
                             if g.get("agent_id") == rule.agent_id]

    value, population, observed = measure(rule.metric, scoped,
                                          calls=calls, guardrails=scoped_guardrails)

    if value is None:
        return Verdict(rule.id, rule.metric, None, False, False, population=0,
                       reason=(f"nothing in the last {rule.window_minutes}m could carry "
                               f"{rule.metric} — no population, so no verdict"),
                       observed=observed)

    matched = _crosses(value, rule.comparator, rule.threshold)
    if not matched:
        return Verdict(rule.id, rule.metric, value, False, False, population=population,
                       reason=f"{rule.metric}={value} does not cross {rule.comparator} "
                              f"{rule.threshold}", observed=observed)

    if not debounce_allows(rule, now):
        return Verdict(rule.id, rule.metric, value, True, False, population=population,
                       reason=(f"{rule.metric}={value} crosses {rule.comparator} "
                               f"{rule.threshold}, but this rule notified within its "
                               f"{rule.debounce_minutes}m quiet period"),
                       observed=observed)

    return Verdict(rule.id, rule.metric, value, True, True, population=population,
                   reason=f"{rule.metric}={value} crosses {rule.comparator} "
                          f"{rule.threshold} over {population} run(s) in "
                          f"{rule.window_minutes}m",
                   observed=observed)
