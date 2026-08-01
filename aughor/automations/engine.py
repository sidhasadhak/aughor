"""Wave A2 — the ONE engine for declared automations.

Every automation fires through :func:`run_automation`, and only through it. The gate order is
load-bearing and deliberately mirrors :mod:`aughor.actions.executor`: cheap, side-effect-free gates
first; the only step that can cause a side effect is last.

    enabled → not expired → not paused → conditions (all|any)
            → effects in declared order → jittered retry → fallback → record the run

Lifecycle gates run **before** condition evaluation, so a muted or expired automation never reaches
the warehouse — it costs nothing, and the run row still says why. That ordering is asserted by a
test, because "we check it somewhere" is how a mute becomes an expensive no-op.

**Every tick writes exactly one :class:`~aughor.automations.models.AutomationRun`** — including the
ticks that deliberately did nothing. That is the gap this engine exists to close: ``monitor_alerts``
persists only alerts that *fired*, so "did it run at 03:00, and why did nothing happen?" has no
answer today.

Both seams are injectable, as in K2:

* ``probe(condition, automation) -> (fired, detail)`` evaluates the conditions that need the
  warehouse. The default probe wires ``metric`` (delegating to an existing Monitor, so the six
  already-tested alert conditions are reused rather than reimplemented) and raises for
  ``source_change`` / ``entity_appears``, which land in A3 — a seam that raises, never one that
  silently reports "not fired".
* ``dispatch(effect, automation) -> EffectOutcome`` performs the effect. The default dispatcher
  routes ``kinetic_action`` through :func:`~aughor.actions.executor.execute_kinetic_action`, so a
  declared write inherits submission criteria, the graduated-approval gate and the audit trail
  unchanged. **Wave A adds no second write path**, which is why nothing above LOW risk can auto-fire
  from an automation either.
"""
from __future__ import annotations

import logging
import random
import time as _time
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from aughor.automations.models import (
    Automation,
    AutomationRun,
    Condition,
    Effect,
    EffectOutcome,
)
from aughor.automations.store import append_run, last_run
from aughor.util.time import now_iso_z

logger = logging.getLogger(__name__)

ConditionProbe = Callable[[Condition, Automation], "tuple[bool, str]"]
Dispatch = Callable[[Effect, Automation], EffectOutcome]

#: Total wall-clock a single tick may spend sleeping between retries. A background tick holds a
#: scheduler thread while it waits, so the retry budget is bounded regardless of what an operator
#: configures per automation.
MAX_RETRY_SLEEP_SECONDS = 120.0


class ProbeUnavailable(RuntimeError):
    """A condition kind has no probe wired yet (an A3 seam). Loud on purpose: a condition that
    cannot be evaluated must not be reported as 'did not fire'."""


# ── time helpers ─────────────────────────────────────────────────────────────────

def _parse(iso: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 stamp to an aware UTC datetime; None on empty/unparseable.

    Tolerates the ``Z`` suffix (:func:`now_iso_z`, what these stores persist) and naive strings,
    which are read as UTC — the same tolerance :func:`aughor.util.time.age_hours` applies.
    """
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


# ── condition evaluation ─────────────────────────────────────────────────────────

def _schedule_fired(cond: Condition, automation: Automation, now: datetime) -> tuple[bool, str]:
    """True when the cron matched at some point between the last run and ``now``.

    Evaluated in-engine (no warehouse). Asking "did the cron fire since we last ran?" rather than
    "is it exactly the cron minute now?" makes the condition robust to a late or coalesced tick —
    a missed 08:00 that ticks at 08:04 still fires, once.
    """
    from apscheduler.triggers.cron import CronTrigger

    try:
        trigger = CronTrigger.from_crontab(cond.cron, timezone="UTC")
    except (ValueError, KeyError) as exc:
        raise ProbeUnavailable(f"invalid cron '{cond.cron}': {exc}") from exc

    prev_run = last_run(automation.id)
    prev = _parse(prev_run.started_at) if prev_run else None
    if prev is None:
        return True, f"schedule({cond.cron}): first run"

    # +1s so a tick that lands on the same instant as the previous run cannot re-fire it.
    nxt = trigger.get_next_fire_time(None, prev + timedelta(seconds=1))
    if nxt is not None and nxt <= now:
        return True, f"schedule({cond.cron}): due since {nxt.isoformat()}"
    return False, f"schedule({cond.cron}): next due {nxt.isoformat() if nxt else 'never'}"


def default_probe(cond: Condition, automation: Automation) -> tuple[bool, str]:
    """Evaluate a warehouse-backed condition.

    ``metric`` delegates to the named :class:`~aughor.monitors.models.Monitor`: the monitor's own
    runner decides whether it fires, so ``threshold_cross`` / ``anomaly`` / ``segment_drift`` and
    friends keep exactly one implementation. ``suppress=False`` — the monitor's anti-flap debounce
    is about not re-*alerting* a human; an automation's own muting is ``paused_until``, and letting
    a monitor's grace window silently swallow an automation's trigger would be two mute concepts
    fighting over one tick.
    """
    if cond.kind == "metric":
        from aughor.db.connection import open_connection_for
        from aughor.monitors.runner import run_monitor
        from aughor.monitors.store import get_monitor

        monitor = get_monitor(cond.monitor_id)
        if monitor is None:
            raise ProbeUnavailable(f"metric condition names an unknown monitor: {cond.monitor_id}")
        db = open_connection_for(monitor.conn_id)
        try:
            alert = run_monitor(monitor, db, suppress=False)
        finally:
            try:
                db.close()
            except Exception as exc:
                from aughor.kernel.errors import tolerate
                tolerate(exc, "closing the probe db handle is best-effort; the verdict is computed",
                         counter="automations.probe.db_close")
        if alert is None:
            return False, f"metric({monitor.name}): no alert"
        return True, f"metric({monitor.name}): {alert.severity} — {alert.message[:120]}"

    if cond.kind in ("source_change", "entity_appears"):
        # A3 — gated separately from the engine so an operator can run schedule/metric
        # automations without also enabling per-minute warehouse probes.
        from aughor.kernel.flags import flag_enabled
        if not flag_enabled("automations.source_probes"):
            raise ProbeUnavailable(
                f"condition kind '{cond.kind}' requires the automations.source_probes flag (off)")
        from aughor.automations.probes import evaluate_source_condition
        return evaluate_source_condition(cond, automation)

    raise ProbeUnavailable(f"condition kind '{cond.kind}' has no probe wired")


def evaluate_conditions(automation: Automation, *, now: datetime,
                        probe: Optional[ConditionProbe] = None) -> tuple[bool, list[str], str]:
    """Evaluate every condition under ``condition_logic``. Returns ``(fired, details, reason)``.

    Deliberately evaluates ALL conditions rather than short-circuiting: the run history is meant to
    explain the tick, and "we stopped looking after the first false" makes a two-condition automation
    unanswerable. Probes are cheap by construction (A3 bounds them); correctness of the record wins.
    """
    probe_fn = probe or default_probe
    results: list[tuple[bool, str]] = []
    for cond in automation.conditions:
        if cond.kind == "schedule":
            results.append(_schedule_fired(cond, automation, now))
        else:
            results.append(probe_fn(cond, automation))

    fired_details = [d for ok, d in results if ok]
    quiet_details = [d for ok, d in results if not ok]
    if automation.condition_logic == "any":
        fired = any(ok for ok, _ in results)
    else:
        fired = all(ok for ok, _ in results)

    if fired:
        reason = "; ".join(fired_details) or "conditions held"
    else:
        reason = "; ".join(quiet_details) or "conditions did not hold"
    return fired, fired_details, reason


# ── effect dispatch ──────────────────────────────────────────────────────────────

def _dispatch_kinetic(effect: Effect, automation: Automation) -> EffectOutcome:
    """The governed write — routed through the ONE Wave-K executor, never around it.

    A criterion failure comes back as the AUTHORED message, passed through verbatim into the run
    history exactly as K2 passes it to a human and K4 passes it to the model.
    """
    from aughor.actions.executor import execute_kinetic_action
    from aughor.ontology.store import load_latest_ontology

    # The public loader already overlays human overrides, so kinetic_actions are applied —
    # the same resolution `routers/kinetic.py::_resolve_graph` uses.
    schema_name = effect.config.get("schema_name") or None
    graph = load_latest_ontology(automation.conn_id, schema_name)
    # A named schema with no cached ontology is a DIFFERENT failure from an undeclared action, and
    # saying so cost real time once: the first live run pointed at a schema that had never been
    # built, fell back to another schema's graph, and reported "not a declared action" — which sent
    # the diagnosis at the declaration rather than at the missing ontology.
    fell_back = False
    if graph is None and schema_name:
        graph = load_latest_ontology(automation.conn_id, None)
        fell_back = graph is not None
    actions = getattr(graph, "kinetic_actions", None) or {}
    action = actions.get(effect.action_id)
    if action is None:
        if graph is None:
            detail = f"no ontology is cached for connection '{automation.conn_id}'"
        elif fell_back:
            detail = (f"schema '{schema_name}' has no cached ontology on connection "
                      f"'{automation.conn_id}' (fell back to '{getattr(graph, 'schema_name', '')}', "
                      f"which does not declare it)")
        else:
            detail = f"'{effect.action_id}' is not a declared action on this connection"
        return EffectOutcome(kind=effect.kind, target=effect.action_id,
                             status="dispatch_error", message=detail)

    result = execute_kinetic_action(
        action, effect.params,
        actor=f"automation:{automation.id}", scope=automation.conn_id,
    )
    status = result.status if result.status in {
        "executed", "criterion_failed", "approval_required", "invalid_params", "dispatch_error",
    } else "failed"
    return EffectOutcome(kind=effect.kind, target=effect.action_id, status=status,
                         message=result.message)


def _dispatch_notify(effect: Effect, automation: Automation) -> EffectOutcome:
    from aughor.notifications.executor import fire_action
    from aughor.notifications.models import ActionPayload
    from aughor.notifications.store import get_trigger

    trigger_id = str(effect.config.get("trigger_id", ""))
    trigger = get_trigger(trigger_id)
    if trigger is None:
        return EffectOutcome(kind=effect.kind, target=trigger_id, status="dispatch_error",
                             message=f"unknown Action Hub trigger: {trigger_id}")
    # ActionPayload has no defaults — every field is supplied. `investigation_id` carries the
    # automation id so a webhook receiver can trace the notification back to what sent it.
    log = fire_action(trigger, ActionPayload(
        investigation_id=f"automation:{automation.id}",
        rec_index=0,
        recommendation=str(effect.config.get("message")
                           or f"Automation '{automation.name}' fired"),
        metric_name=str(effect.config.get("metric_name", "")),
        headline=automation.name,
        trigger_id=trigger_id,
        triggered_at=now_iso_z(),
    ))
    ok = getattr(log, "status", "") == "ok"
    return EffectOutcome(kind=effect.kind, target=trigger_id,
                         status="executed" if ok else "failed",
                         message=getattr(log, "error", None) or "")


def _dispatch_brief(effect: Effect, automation: Automation) -> EffectOutcome:
    from aughor.briefing.delivery import deliver_subscription
    from aughor.briefing.store import get_subscription

    sub_id = str(effect.config.get("subscription_id", ""))
    sub = get_subscription(sub_id)
    if sub is None:
        return EffectOutcome(kind=effect.kind, target=sub_id, status="dispatch_error",
                             message=f"unknown brief subscription: {sub_id}")
    result = deliver_subscription(sub) or {}
    ok = result.get("status") == "ok"
    return EffectOutcome(kind=effect.kind, target=sub_id,
                         status="executed" if ok else "failed",
                         message=str(result.get("error") or result.get("status") or ""))


def _dispatch_monitor(effect: Effect, automation: Automation) -> EffectOutcome:
    """Wave A5 — run a Monitor's check and append its alert. A FAITHFUL replay of the legacy
    monitor job (``monitors/scheduler.py::_make_job_fn``): ``run_monitor(m, db, suppress=True)`` —
    keeping the anti-flap debounce — then ``append_alert`` when it fires. Same alert store, so the
    debounce state and the emitted ``monitor.alert`` event are byte-identical to the legacy path;
    the only thing that changed is which loop called it."""
    from aughor.db.connection import open_connection_for
    from aughor.monitors.runner import run_monitor
    from aughor.monitors.store import append_alert, get_monitor

    monitor_id = str(effect.config.get("monitor_id", ""))
    monitor = get_monitor(monitor_id)
    if monitor is None or not monitor.enabled:
        return EffectOutcome(kind=effect.kind, target=monitor_id, status="skipped",
                             message="monitor missing or disabled")
    db = open_connection_for(monitor.conn_id)
    try:
        alert = run_monitor(monitor, db, suppress=True)   # suppress=True — preserve the debounce
    finally:
        try:
            db.close()
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "closing the monitor-effect db handle is best-effort; the result is computed",
                     counter="automations.effect.monitor.db_close")
    if alert is None:
        return EffectOutcome(kind=effect.kind, target=monitor_id, status="executed",
                             message="no alert")
    append_alert(alert)
    return EffectOutcome(kind=effect.kind, target=monitor_id, status="executed",
                         message=f"{alert.severity}: {alert.message[:120]}")


def _dispatch_investigate(effect: Effect, automation: Automation) -> EffectOutcome:
    """Run a deep investigation on the automation's connection, optionally AS a user-agent.

    Since Wave H5 the running itself belongs to :mod:`aughor.runners.investigation`, a module
    neither this package nor :mod:`aughor.actions` owns, so a declared ``trigger_investigation``
    action reaches the same runner without K having to import A (it would be backwards: A already
    routes its ``kinetic_action`` effect through K's executor). What stays here is the part that
    is genuinely an automation's business — how the effect's config becomes a request, what makes
    two ticks the same work, and how the outcome reads in the run history.

    The runner drives the REAL answer path rather than a private copy, so when ``effect.agent_id``
    is set (Wave H1) the persona is applied by the one door — pinned instructions lead the prompt,
    retrieval is scoped to the agent's documents, its connection/schema bindings win. Scheduling an
    agent is a *parameter*, not a second way to answer. The binding is pre-checked before anything
    is submitted, because the ask path raises its refusals as HTTP errors and a submitted job would
    swallow them.
    """
    question = str(effect.config.get("question", ""))
    agent_id = effect.agent_id
    target = question[:200]
    ran_as = f" as agent {agent_id}" if agent_id else ""

    from aughor.runners import InvestigationRequest, run_investigation
    # The agent is part of the identity of the work: the same question asked as two different
    # personas is two different investigations, and must not deduplicate onto one.
    idem = f"automation:{automation.id}:investigate"
    if agent_id:
        idem = f"{idem}:{agent_id}"
    run = run_investigation(
        InvestigationRequest(question=question, connection_id=automation.conn_id,
                             schema_name=effect.config.get("schema_name"),
                             agent_id=agent_id or None),
        idempotency_key=idem, caller=f"automation:{automation.id}",
    )
    if run.status == "refused":
        return EffectOutcome(kind=effect.kind, target=target, status="dispatch_error",
                             message=run.message)
    if run.status == "failed":
        # Only the inline path can report this — it is the only one that waited. Before H5 the
        # drained error was computed and then discarded, so an inline run that errored was
        # recorded as `executed`: a tick that answered nothing, filed as a tick that worked.
        return EffectOutcome(kind=effect.kind, target=target, status="failed",
                             message=f"{run.message}{ran_as}")
    return EffectOutcome(kind=effect.kind, target=target, status="executed",
                         message=f"{run.message}{ran_as}")


_DISPATCHERS: dict[str, Callable[[Effect, Automation], EffectOutcome]] = {
    "kinetic_action": _dispatch_kinetic,
    "notify": _dispatch_notify,
    "brief": _dispatch_brief,
    "investigate": _dispatch_investigate,
    "monitor": _dispatch_monitor,
}


def default_dispatch(effect: Effect, automation: Automation) -> EffectOutcome:
    """The wired-in dispatcher. An unknown kind raises rather than no-ops, so a caller sees a
    clear signal — the same choice K2's ``default_dispatch`` makes."""
    fn = _DISPATCHERS.get(effect.kind)
    if fn is None:
        raise ProbeUnavailable(f"no dispatcher for effect kind: {effect.kind}")
    return fn(effect, automation)


# ── the engine ───────────────────────────────────────────────────────────────────

def _gated(automation: Automation, now: datetime) -> Optional[str]:
    """The lifecycle gates, cheapest first. Returns the reason it is gated, or None to proceed."""
    if not automation.enabled:
        return "disabled"
    expires = _parse(automation.expires_at)
    if expires is not None and expires <= now:
        return f"expired at {automation.expires_at}"
    paused = _parse(automation.paused_until)
    if paused is not None and paused > now:
        return f"muted until {automation.paused_until}"
    return None


def _run_effect(effect: Effect, automation: Automation, dispatch: Dispatch, *,
                sleeper: Callable[[float], None], rng: Callable[[], float],
                sleep_budget: list[float]) -> EffectOutcome:
    """Dispatch one effect, retrying only what a retry can fix.

    A criterion failure, an approval requirement or bad params are **verdicts, not faults** — the
    inputs are identical next attempt, so retrying is pure waste against whatever refused it (the
    #200 lesson: every retry is itself another request against whatever just refused).

    ``dispatch_error`` is terminal for the same reason, learned the expensive way: the first live
    run named an action the connection does not declare, and the engine spent **48 seconds** of a
    held scheduler thread retrying an id that could never resolve. A structural error — unknown
    action, unknown trigger, unknown subscription, an unwired seam — is a verdict too. Only
    ``failed`` (a genuinely transient dispatch outcome) retries in-tick; anything the next
    heartbeat could plausibly fix gets retried by the next heartbeat, 60s later, holding nothing.
    """
    attempts = 0
    outcome: EffectOutcome
    while True:
        attempts += 1
        try:
            outcome = dispatch(effect, automation)
        except Exception as exc:
            outcome = EffectOutcome(kind=effect.kind, target=effect.target(), status="failed",
                                    message=f"{type(exc).__name__}: {exc}")
        outcome = outcome.model_copy(update={"attempts": attempts})
        retriable = outcome.status == "failed"
        if not retriable or attempts > automation.max_retries:
            return outcome
        # Jittered backoff — N automations failing together must not retry in lockstep. The budget
        # is per-TICK and shared across this automation's effects. Exhausting it does not abort the
        # remaining attempts, it only stops them waiting: `max_retries` is capped at 5, so the worst
        # case is a handful of back-to-back dispatches, which is cheaper than dropping an effect
        # that the next attempt might have completed.
        delay = automation.retry_backoff_seconds * (1.0 + rng())
        delay = min(delay, max(0.0, sleep_budget[0]))
        if delay > 0:
            sleeper(delay)
            sleep_budget[0] -= delay


def run_automation(
    automation: Automation,
    *,
    now: Optional[datetime] = None,
    probe: Optional[ConditionProbe] = None,
    dispatch: Optional[Dispatch] = None,
    sleeper: Callable[[float], None] = _time.sleep,
    rng: Callable[[], float] = random.random,
    persist: bool = True,
) -> AutomationRun:
    """Run one automation through the full pipeline and return its :class:`AutomationRun`.

    Never raises for an expected outcome — gated, not-fired and effect failures are all *statuses*,
    recorded on the run. Only a genuinely unexpected error becomes ``outcome="error"``, and even
    that is persisted rather than lost.
    """
    now = now or datetime.now(timezone.utc)
    # Run timestamps derive from the TICK clock (``now``), not a second wall-clock read:
    # `_schedule_fired` compares the cron against the previous run's `started_at`, so mixing an
    # injected evaluation clock with wall-clock record stamps makes since-last-run arithmetic
    # incoherent the moment the two diverge (a test, a replay, a paused VM). In production the
    # default `now` IS the wall clock, so nothing changes there.
    started = now.isoformat().replace("+00:00", "Z")
    t0 = _time.monotonic()
    dispatch_fn = dispatch or default_dispatch

    def _finish(run: AutomationRun) -> AutomationRun:
        elapsed_ms = int((_time.monotonic() - t0) * 1000)
        finished = (now + timedelta(milliseconds=elapsed_ms)).isoformat().replace("+00:00", "Z")
        run = run.model_copy(update={
            "finished_at": finished,
            "duration_ms": elapsed_ms,
        })
        return append_run(run) if persist else run

    base = {
        "automation_id": automation.id,
        "automation_name": automation.name,
        "conn_id": automation.conn_id,
        "started_at": started,
    }

    # 1 — lifecycle gates (side-effect-free, no warehouse)
    gate_reason = _gated(automation, now)
    if gate_reason is not None:
        return _finish(AutomationRun(**base, outcome="gated", reason=gate_reason))

    # 2 — conditions
    try:
        fired, details, reason = evaluate_conditions(automation, now=now, probe=probe)
    except Exception as exc:
        logger.warning("automation %s condition evaluation failed: %s", automation.id, exc)
        return _finish(AutomationRun(**base, outcome="error",
                                     reason="condition evaluation failed",
                                     error=f"{type(exc).__name__}: {exc}"))
    if not fired:
        return _finish(AutomationRun(**base, outcome="not_fired", reason=reason))

    # 3 — effects, in declared order (the first step that can cause a side effect)
    sleep_budget = [MAX_RETRY_SLEEP_SECONDS]
    outcomes = [
        _run_effect(effect, automation, dispatch_fn,
                    sleeper=sleeper, rng=rng, sleep_budget=sleep_budget)
        for effect in automation.effects
    ]

    # 4 — fallback, only when EVERY effect failed to execute
    fallback_used = False
    if automation.fallback_effect is not None and all(o.status != "executed" for o in outcomes):
        fallback_used = True
        outcomes.append(_run_effect(automation.fallback_effect, automation, dispatch_fn,
                                    sleeper=sleeper, rng=rng, sleep_budget=sleep_budget))

    # 5 — the tick FIRED: commit source-version baselines now, and only now. Committing at
    # probe time would consume a change whenever the other condition of an `all` automation
    # was false — seen once, fired never (probes.py module docstring). Best-effort: an
    # uncommitted baseline re-fires the change next tick (at-least-once, never lost).
    try:
        from aughor.automations.probes import commit_fired_baselines
        commit_fired_baselines(automation)
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "baseline commit is best-effort; the fired run is already recorded",
                 counter="automations.engine.baseline_commit")

    return _finish(AutomationRun(**base, outcome="fired", reason=reason,
                                 conditions_fired=details, effects=outcomes,
                                 fallback_used=fallback_used))
