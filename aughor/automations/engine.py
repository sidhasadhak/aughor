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
import uuid as _uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from aughor.automations.dataflow import (
    FAN_EMPTY_SKIP, GUARD_SKIP, ITEM_ALIAS, FanRefused, UnresolvedBinding, alias_for,
    effect_refs, evaluate_guard, fan_items, fan_source, guard_clauses, is_binding,
    item_context, item_refs, parse_ref, render_clause, resolve,
)
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

# ── Delivery claims (Layer 4.1a) ──────────────────────────────────────────────
# An OUTWARD send — a brief in someone's inbox, a webhook at someone's endpoint —
# cannot be taken back, and the engine wrote its only durable record AFTER dispatching
# it. Anything that killed the process in between (a deploy, an OOM, a serverless
# timeout) left no evidence the send happened, so the next tick fired the same period
# again. The claim closes that window by writing the intent BEFORE the act, which is
# the same shape as the tombstone principle: reversing or repeating durable intent has
# to consult a durable record, and the record has to exist before the thing it guards.
#
# Deliberately the Ledger's transactional kv rather than `try_claim`: a claim is a
# LEASE, which expires — and an expiring guard on an irreversible send is a guard that
# eventually stops guarding.
_CLAIM_STORE = "automation_delivery_claims"

#: What an uncertain delivery means, in one sentence. Deliberately the same shape as
#: the kernel's UNCERTAIN_RESULT for interrupted jobs — "we do not know" is one fact
#: and should read the same wherever it surfaces.
UNCERTAIN_DELIVERY = "it may already have been delivered, so it was not retried"

#: Effect kinds that reach a person. Only these are claimed: a claim narrows when an
#: automation may run again, and paying that for a purely internal effect (a rebuild, a
#: governed write with its own idempotency) would restrict work that was never at risk.
#: ``agent_alert`` is here even though a rule with no channel stays in-app: the kind is
#: static and the channel is per-rule config, so the choice is between claiming a few
#: in-app rules that were never at risk and letting a channel-backed rule double-page when
#: two loops tick together. The rule's own debounce cannot close that race — both ticks read
#: `last_notified_at` before either writes it. A duplicate page is the worse failure.
OUTWARD_EFFECT_KINDS = frozenset({"notify", "brief", "agent_alert"})


def has_outward_effect(automation: Automation) -> bool:
    """Whether this automation can reach a person on a tick."""
    return any(e.kind in OUTWARD_EFFECT_KINDS for e in automation.effects)


def last_delivery_claim(automation_id: str) -> str:
    """When this automation last *attempted* an outward send, or ``""``.

    Read by due-ness alongside the run row. Best-effort: if the ledger cannot be
    reached the claim reads empty, which degrades to exactly the pre-4.1a behaviour
    rather than blocking every automation on a store hiccup.
    """
    try:
        from aughor.kernel.ledger import Ledger
        return str(Ledger.default().kv_get(_CLAIM_STORE, automation_id, "") or "")
    except Exception:
        logger.debug("automations: delivery claim unreadable", exc_info=True)
        return ""


def claim_delivery(automation_id: str, started_at: str) -> bool:
    """Record that an outward send is ABOUT to happen. Returns whether it stuck.

    A claim that fails to write is reported, never swallowed into a silent send: the
    caller decides, and it decides to deliver anyway. Refusing to send because the
    bookkeeping failed would trade a rare duplicate for a certain missed brief, and a
    brief that never arrives is the worse failure.
    """
    try:
        from aughor.kernel.ledger import Ledger
        Ledger.default().kv_put(_CLAIM_STORE, automation_id, started_at)
        return True
    except Exception:
        logger.warning("automations: could not claim delivery for %s — sending anyway, "
                       "so a crash in this window could duplicate it", automation_id,
                       exc_info=True)
        return False


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
    # A DELIVERY CLAIM counts as a previous run for due-ness (4.1a). The run row is
    # written after the effects; the claim is written before them. Reading only the run
    # row means a process that died between the send and the write looks like it never
    # ran, and the next tick re-sends the same period — to a real person. Whichever is
    # later wins, so a claim can only ever hold a period back, never push it forward.
    claimed = _parse(last_delivery_claim(automation.id) or "")
    if claimed is not None and (prev is None or claimed > prev):
        prev = claimed
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
        from aughor.automations.probes import evaluate_source_condition
        return evaluate_source_condition(cond, automation)

    raise ProbeUnavailable(f"condition kind '{cond.kind}' has no probe wired")


def evaluate_conditions(automation: Automation, *, now: datetime,
                        probe: Optional[ConditionProbe] = None,
                        manual: bool = False) -> tuple[bool, list[str], str]:
    """Evaluate every condition under ``condition_logic``. Returns ``(fired, details, reason)``.

    Deliberately evaluates ALL conditions rather than short-circuiting: the run history is meant to
    explain the tick, and "we stopped looking after the first false" makes a two-condition automation
    unanswerable. Probes are cheap by construction (A3 bounds them); correctness of the record wins.

    **``manual`` — a person pressed Run now.** A schedule answers ONE question: *is it
    time?* Someone clicking the button has already answered it, so consulting the cron
    could only ever contradict them — and did: "Run now" on a daily automation replied
    `not_fired — next due tomorrow` at every hour except one, which reads as a broken
    button, not as a considered refusal.

    Every OTHER condition kind is still evaluated, and that asymmetry is the whole point:
    a metric threshold, a source change or an entity appearing are claims about the state
    of the WORLD, and a human pressing a button has not changed any of them. Firing a
    "when revenue drops 20%" automation because someone was curious would deliver an
    alert about a drop that never happened.
    """
    probe_fn = probe or default_probe
    results: list[tuple[bool, str]] = []
    for cond in automation.conditions:
        if cond.kind == "schedule":
            results.append((True, f"schedule({cond.cron}): run now, by hand")
                           if manual else _schedule_fired(cond, automation, now))
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

    # VA-9b — a governed write is attributed to the AGENT that made it, not to the
    # mechanism that scheduled it. `automation:<id>` named a cron; `agent:<id>` names an
    # actor with a charter, instructions, bound documents and an owner. It also parses as
    # a principal ref (RC-4), so the identity plane can resolve it like any other.
    result = execute_kinetic_action(
        action, effect.params,
        actor=acting_agent_ref(effect, automation), scope=automation.conn_id,
    )
    status = result.status if result.status in {
        "executed", "criterion_failed", "approval_required", "invalid_params", "dispatch_error",
    } else "failed"
    return EffectOutcome(kind=effect.kind, target=effect.action_id, status=status,
                         message=result.message,
                         # The executor already returns a dispatch result; it was thrown
                         # away at this boundary.
                         data=dict(result.outcome or {}))


@contextmanager
def _step_span(effect: Effect, automation: Automation, alias: str, run_id: str = ""):
    """One TOOL span for one step. Best-effort — telemetry must never fail a run.

    Named `automation.<kind>` rather than the effect's target: the span name is what a
    waterfall row reads, and `slack_post` answers "what kind of work" where a channel id
    answers nothing.

    The span is CONSTRUCTED inside the try and ENTERED outside it. Wrapping the whole
    `with` instead would swallow the body's own exceptions into the telemetry fallback —
    and a fallback that yields a second time is a RuntimeError, not a graceful degrade.
    """
    span = None
    bound = None
    try:
        from aughor.telemetry import bind_trace, mlflow_tool_span
        # Bound per STEP rather than once around the loop: same trace id either way, and
        # this needs no re-indent of the chain, which is the part that must not churn.
        # `bind_trace` is independent of every observability flag — a trace id is a
        # correlation fact, not a sink, and making it conditional is how spans end up
        # orphaned with nothing able to group them.
        if run_id:
            bound = bind_trace(run_id)
            bound.__enter__()
        span = mlflow_tool_span(f"automation.{effect.kind}", {
            "automation_id": automation.id, "automation": automation.name,
            "step": alias, "agent_id": acting_agent(effect, automation),
        }, span_kind="tool",
            # DS-3 — the same two facts again, on `span_attrs` this time, because that is
            # the only channel that reaches the `session_events` payload (telemetry.py
            # says so in its own warning). As ordinary attributes they land in
            # `task_history`, which has no HTTP door — so a reader watching a run live
            # could see THAT a step ran and never which step it was.
            span_attrs={"automation_id": automation.id, "step": alias})
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "automation step span is best-effort", counter="automation.span")
    try:
        if span is None:
            yield
        else:
            with span:
                yield
    finally:
        if bound is not None:
            try:
                bound.__exit__(None, None, None)
            except Exception as exc:
                from aughor.kernel.errors import tolerate
                tolerate(exc, "trace unbind is best-effort", counter="automation.span")


#: Engine→dispatcher plumbing: set on a step's BOUND config when a later step binds to
#: its output. Never authored, never stored — the engine adds it after `resolve` and the
#: dispatcher reads it. Underscored so it cannot collide with a real config key, and
#: absent from every label allowlist so it cannot reach a reader.
AWAIT_KEY = "_await_result"


def _downstream_binds(alias: str, later: list[Effect]) -> bool:
    """Does any later step reference ``alias``?

    Reads the same `effect_refs` the graph derives its data edges from, so a step the
    canvas draws an arrow out of is exactly a step the engine waits for.

    W1 — `effect_refs`, so a step consumed ONLY by a downstream guard is waited for too.
    Missing that would be the subtlest bug in this wave: "post only if step 1 found
    something" would test the *job id* `investigate` returns when nobody waits — a
    non-empty string, so `truthy` would hold every single morning.
    """
    for nxt in later:
        for ref in effect_refs(nxt):
            if parse_ref(ref)[0] == alias:
                return True
    return False


def acting_agent(effect: Effect, automation: Automation) -> str:
    """The agent this step runs as: its own if it names one, else the automation's.

    A step may delegate one part of a chain to a different agent; leaving it empty is
    what makes an automation read as ONE agent's work rather than a bag of effects.
    """
    return effect.agent_id or getattr(automation, "agent_id", "") or ""


def acting_agent_ref(effect: Effect, automation: Automation) -> str:
    """The actor string for a governed record.

    `agent:<id>` when the automation operates as one — a principal ref RC-4's identity
    plane parses like any other. Falls back to `automation:<id>`, which is what every
    automation written before VA-9b records, so nothing already stored changes meaning.
    """
    agent = acting_agent(effect, automation)
    return f"agent:{agent}" if agent else f"automation:{automation.id}"


def _dispatch_slack_post(effect: Effect, automation: Automation) -> EffectOutcome:
    """RC-5.4 — post into a channel AS the bot, so the message can be replied to.

    The last hop the cron path was missing. `notify` fires an incoming webhook, which
    arrives under the WEBHOOK's identity with no thread anyone can reply into, so a
    scheduled run dead-ends on arrival. Posting with the bot's own token arrives as the
    bot: mentionable, threaded, and — because the transport already uses a thread's id as
    the Aughor `session_id` — a reply composes on the same conversation, with the same
    agent, over the same connection.
    """
    from aughor.slackbots.post import post_as_bot
    from aughor.slackbots.store import get_bot_decrypted

    bot_id = str(effect.config.get("bot_id", ""))
    channel = str(effect.config.get("channel", ""))
    bot = get_bot_decrypted(bot_id)
    if bot is None:
        return EffectOutcome(kind=effect.kind, target=bot_id, status="dispatch_error",
                             message=f"unknown Slack bot: {bot_id}")
    if not bot.enabled:
        # A verdict, not a fault: the platform's off switch was thrown deliberately, and
        # retrying would make that switch a lie.
        return EffectOutcome(kind=effect.kind, target=bot_id, status="dispatch_error",
                             message=f"Slack bot '{bot.name}' is disabled")

    ok, info = post_as_bot(
        bot.bot_token, channel,
        str(effect.config.get("message") or f"Automation '{automation.name}' fired"),
        thread_ts=str(effect.config.get("thread_ts") or "") or None,
    )
    if ok:
        return EffectOutcome(
            kind=effect.kind, target=f"{bot_id}:{channel}", status="executed",
            message=f"posted as {bot.name} (ts {info.get('ts', '')})",
            # VA-4a — the thread root, structured. A later step binds `{"$from":
            # "step1.ts"}` to reply INTO this thread, which is the whole shape of a
            # conversation an automation starts and then continues.
            data={"ts": info.get("ts", ""), "channel": info.get("channel", "") or channel,
                  "bot_id": bot_id})
    if info.get("uncertain"):
        # It may have arrived. Saying "failed" would license a retry, and a retried
        # maybe-delivered message is the duplicate this layer exists to prevent.
        return EffectOutcome(kind=effect.kind, target=f"{bot_id}:{channel}", status="uncertain",
                             message=f"post timed out — {UNCERTAIN_DELIVERY}")
    return EffectOutcome(kind=effect.kind, target=f"{bot_id}:{channel}", status="failed",
                         message=f"Slack refused the post: {info.get('error', 'unknown')}")


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
        # 4.1a — stable across every attempt of THIS delivery, so a receiver can drop
        # the duplicate our own inner HTTP retry may produce. Keyed by the automation
        # and the period, never by a fresh timestamp (which is what `triggered_at` is,
        # and why the receiver could not tell a retry from a new alert).
        delivery_key=f"{automation.id}:{last_delivery_claim(automation.id) or 'unclaimed'}",
    ))
    _status = getattr(log, "status", "")
    if _status == "timeout":
        # It may have arrived. Saying "failed" would license a retry, and a retried
        # maybe-delivered webhook is the duplicate this layer exists to prevent.
        return EffectOutcome(kind=effect.kind, target=trigger_id, status="uncertain",
                             message=f"delivery timed out — {UNCERTAIN_DELIVERY}")
    ok = _status == "ok"
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
    _status = result.get("status")
    if _status == "timeout":
        # Same reasoning as notify: an email whose send timed out may be in an inbox.
        return EffectOutcome(kind=effect.kind, target=sub_id, status="uncertain",
                             message=f"delivery timed out — {UNCERTAIN_DELIVERY}")
    ok = _status == "ok"
    return EffectOutcome(kind=effect.kind, target=sub_id,
                         status="executed" if ok else "failed",
                         message=str(result.get("error") or _status or ""))


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


def _dispatch_agent_alert(effect: Effect, automation: Automation) -> EffectOutcome:
    """VA-6 — evaluate an agent alert rule and deliver it if it crosses.

    ``suppress=True``, exactly as the monitor effect does: the rule's quiet period is about
    not re-paging a human, and a heartbeat that ignored it would turn one bad deploy into
    sixty messages. The outcome distinguishes the three things an operator needs told apart
    — the rule had no population to measure, it measured and did not cross, or it fired."""
    from aughor.obs.agent_alert_runner import run_rule_by_id

    rule_id = str(effect.config.get("rule_id", ""))
    verdict, event = run_rule_by_id(rule_id, suppress=True)
    if verdict is None:
        return EffectOutcome(kind=effect.kind, target=rule_id, status="skipped",
                             message="rule missing or disabled")
    if event is None:
        return EffectOutcome(kind=effect.kind, target=rule_id, status="executed",
                             message=verdict.reason[:200])
    delivered = "delivered" if event.delivered else f"recorded ({event.delivery_detail})"
    return EffectOutcome(kind=effect.kind, target=rule_id, status="executed",
                         message=f"{event.severity}: {verdict.reason[:160]} — {delivered}")


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
    # VA-13 — wait only when a later step binds to this one's answer (set by the chain
    # loop from `effect_refs`). An unconsumed investigate keeps submitting and returning,
    # which is what "run this nightly" wants and what every automation written before this
    # already does.
    await_result = bool(effect.config.get(AWAIT_KEY))
    # VA-9b — inherit the automation's agent when the step does not name its own, so
    # `investigate` stops being the one effect that knows who is acting.
    agent_id = acting_agent(effect, automation)
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
                             agent_id=agent_id or None, wait=await_result),
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
    _inv = str(getattr(run, "investigation_id", "") or getattr(run, "id", "") or "")
    return EffectOutcome(kind=effect.kind, target=target, status="executed",
                         message=f"{run.message}{ran_as}",
                         # VA-4c — the run this step produced. Its TOKENS live on the
                         # investigation, so carrying the id lets a node reach its own
                         # spend without this model growing a usage field the other five
                         # effect kinds could never fill.
                         investigation_id=_inv,
                         # VA-13 — what a later step can bind to. `answer` is the run's
                         # headline and is present only when this step was WAITED for; a
                         # submitted run has produced no sentence yet, and publishing an
                         # empty one would let `{"$from": "step1.answer"}` resolve to
                         # nothing and post a blank message. Absent instead, so the
                         # binding raises `UnresolvedBinding` and the downstream step is
                         # SKIPPED with a reason — which is the honest outcome.
                         data={k: v for k, v in (("investigation_id", _inv),
                                                 ("answer", run.headline)) if v})


_DISPATCHERS: dict[str, Callable[[Effect, Automation], EffectOutcome]] = {
    "kinetic_action": _dispatch_kinetic,
    "notify": _dispatch_notify,
    "brief": _dispatch_brief,
    "investigate": _dispatch_investigate,
    "monitor": _dispatch_monitor,
    "agent_alert": _dispatch_agent_alert,
    "slack_post": _dispatch_slack_post,
}


# ── B2: the dry run ──────────────────────────────────────────────────────────────
#
# A design could be inspected AFTER it ran and never tried BEFORE it was armed — so the
# only way to find out what an automation would do was to let it do it, to real people.
#
# Measured before writing this, because the plan said the harness already existed:
# `evals/equivalence.py`'s inert dispatch runs `persist=False` and publishes NOTHING, so
# every chained step after the first came back "upstream data unavailable". It would have
# reported a working chain as broken. Four more differences turned up in the same pass,
# each one a side effect a preview must not have — see `run_automation(dry_run=True)`.

#: What a dry-run step "publishes", per key. Marked so it can never be mistaken for a
#: measured value — and readable, because it turns a downstream step's resolved config
#: into a wiring diagram in words: "would post «numbers.answer» to #ops".
def _sample(alias: str, key: str) -> str:
    return f"«{alias}.{key}»"


def dry_sample(alias: str, effect: Effect, later: list[Effect]) -> dict:
    """The sample output one step publishes into a dry run's chain context.

    The declared keys (B1's `PUBLISHED_KEYS`) UNION every key a later step actually asks
    of this alias. The union is what makes the open set work: a declared-action step's
    outcome shape is unknowable — `validate_chain` accepts bindings onto it unchecked for
    exactly that reason — so a dry run reads the question from the steps that ask it,
    using the same `effect_refs` everything else in this seam derives from. Without it a
    preview would report "upstream data unavailable" for a binding the engine will
    satisfy perfectly well at 09:00.
    """
    from aughor.automations.dataflow import PUBLISHED_KEYS
    keys = set(PUBLISHED_KEYS.get(effect.kind) or ())
    for nxt in later:
        for ref in effect_refs(nxt):
            target, key = parse_ref(ref)
            if target == alias and key:
                keys.add(key)
    return {k: _sample(alias, k) for k in sorted(keys)}


def dry_fan_item(effect: Effect) -> dict:
    """The one representative item a preview walks when the fan-out source is a BINDING.

    Same shape as :func:`dry_sample` and for the same reason: a preview's context holds
    sample strings, not the list tomorrow will produce, so the keys come from what this
    step actually asks of its item (`{"$from": "item.channel"}` → `channel`). Without it
    a preview would resolve `item.channel` against nothing and report a sound fan-out as
    a step with unavailable upstream data.

    A LITERAL list needs none of this — its items are known now, and walking them for
    real is what makes a preview say "would post 3 messages: EMEA, NA, APAC".
    """
    keys = {parse_ref(ref)[1] for ref in item_refs(effect) if parse_ref(ref)[1]}
    return {k: _sample(ITEM_ALIAS, k) for k in sorted(keys)} or {
        "value": _sample(ITEM_ALIAS, "value")}


def dry_dispatch(effect: Effect, automation: Automation) -> EffectOutcome:
    """Dispatch nothing, report what WOULD have been dispatched.

    The label comes from `graph.effect_detail` — the allowlist that already exists
    because a step's config can carry a message body or a credential-shaped value, and
    this string is read on screen. Never the bound config wholesale.
    """
    from aughor.automations.graph import effect_detail
    target = effect_detail(effect)
    return EffectOutcome(kind=effect.kind, target=target or "—", status="executed",
                         message=f"would run{f' → {target}' if target else ''}")


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
    dry_run: bool = False,
    manual: bool = False,
    run_id: Optional[str] = None,
    until_alias: Optional[str] = None,
) -> AutomationRun:
    """Run one automation through the full pipeline and return its :class:`AutomationRun`.

    Never raises for an expected outcome — gated, not-fired and effect failures are all *statuses*,
    recorded on the run. Only a genuinely unexpected error becomes ``outcome="error"``, and even
    that is persisted rather than lost.

    **B2 · ``dry_run``** — walk the chain and dispatch nothing. It returns an ordinary
    ``AutomationRun``, which is the whole point: `Activity`'s run canvas already renders
    one, so a preview needed no second way of drawing a chain (the VA-4d lesson — check
    whether an existing view's substrate is unfed before building a new view).

    Five things separate it from ``persist=False`` with an inert dispatcher, and every
    one of them was MEASURED rather than assumed:

    1. **The lifecycle gate is reported, not enforced.** You dry-run precisely because
       the automation is not armed yet; gating on ``enabled`` would answer "disabled" to
       every question a preview exists to ask.
    2. **Conditions are described, not evaluated.** A daily cron says "not due" all day —
       three consecutive live run-nows returned ``not_fired`` while W1 was being proved.
       A preview answers "what would it do WHEN it fires".
    3. **Steps publish samples.** The existing inert dispatcher published nothing, so
       every step after the first read "upstream data unavailable" — a working chain
       reported as broken.
    4. **No baseline is committed.** ``commit_fired_baselines`` runs regardless of
       ``persist``: a preview would have CONSUMED a source change, and the real tick at
       09:00 would then not fire. A preview that alters the next real run is not one.
    5. **No span is emitted.** VA-4d made the run id the trace id, so a dry run would
       otherwise appear in ``Activity`` as a run that happened.

    Guards are **reported, never decided** (see the chain loop): a sample cannot answer
    "will tomorrow's number clear this threshold", and a preview that pretended to would
    be worse than one that says when the question gets asked.
    """
    now = now or datetime.now(timezone.utc)
    if dry_run:
        # A preview never writes: not the run row, not a delivery claim, not a baseline.
        # `dispatch` is OVERRIDDEN, not defaulted: a preview that can be handed a real
        # dispatcher is not a preview, and "the caller passed one" is not a reason to
        # send a message to a real channel.
        persist = False
        dispatch = dry_dispatch
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

    # VA-4d — allocated up front so the run id can BE the trace id: clicking a run in
    # `Activity → Runs` then lands on exactly this AutomationRun, with no second
    # correlation key to keep in sync.
    #
    # DS-3 — and a CALLER may supply it. Every step's span is written under this id while
    # the chain runs, so a surface that wants to watch a run needs the id BEFORE the run
    # finishes; minting it here only meant the one thing able to watch was the one thing
    # that had already stopped caring. Nothing else changes: an unsupplied id is still
    # minted here, and the id is still the trace id.
    run_id = run_id or str(_uuid.uuid4())
    base = {
        "id": run_id,
        "automation_id": automation.id,
        "automation_name": automation.name,
        "conn_id": automation.conn_id,
        # VA-9b — on EVERY run, including the gated and not-fired ones. A run that did
        # nothing still did nothing on someone's behalf, and an agent's history is
        # incomplete if it only contains the ticks that acted.
        "agent_id": getattr(automation, "agent_id", "") or "",
        "started_at": started,
    }

    # 1 — lifecycle gates (side-effect-free, no warehouse)
    gate_reason = _gated(automation, now)
    if gate_reason is not None and not dry_run:
        return _finish(AutomationRun(**base, outcome="gated", reason=gate_reason))

    # 2 — conditions
    if dry_run:
        # Described, not evaluated. The reason line carries BOTH facts a reader needs:
        # that nothing was sent, and what WOULD gate this today — so a preview of a
        # paused automation still says it is paused instead of quietly pretending.
        fired = True
        # graph.py's labeller, not a second one: the trigger node on the canvas and the
        # reason line on a preview must not word the same condition differently.
        from aughor.automations.graph import condition_label
        details = [condition_label(c) for c in automation.conditions]
        reason = "dry run — nothing was sent" + (f"; {gate_reason}" if gate_reason else "")
    else:
        try:
            fired, details, reason = evaluate_conditions(automation, now=now, probe=probe,
                                                         manual=manual)
        except Exception as exc:
            logger.warning("automation %s condition evaluation failed: %s",
                           automation.id, exc)
            return _finish(AutomationRun(**base, outcome="error",
                                         reason="condition evaluation failed",
                                         error=f"{type(exc).__name__}: {exc}"))
        if not fired:
            return _finish(AutomationRun(**base, outcome="not_fired", reason=reason))

    # 3 — effects, in declared order (the first step that can cause a side effect)
    #
    # 4.1a — claim BEFORE the irreversible part. From here on a crash leaves durable
    # evidence that this period was attempted, so the next tick holds rather than
    # re-sending. Only outward effects are claimed (see OUTWARD_EFFECT_KINDS).
    if persist and has_outward_effect(automation):
        claim_delivery(automation.id, started)
    sleep_budget = [MAX_RETRY_SLEEP_SECONDS]


    # VA-4a — a CHAIN, not a list comprehension. Each effect sees the accumulated output
    # of every prior step (merged-data, à la `andThen`), which is what makes "post the
    # answer from step 1 into the thread step 2 opened" expressible at all. Before this,
    # every effect received only (effect, automation, dispatch): there was no dataflow,
    # so a designed workflow could draw arrows the engine would not have followed.
    context: dict[str, dict] = {}
    outcomes: list[EffectOutcome] = []

    # DS-2 — "run to here": walk the chain only as far as one step.
    #
    # Truncating the list rather than breaking out of the loop, because a step can leave
    # the body early by half a dozen routes — held by its guard, an unresolved binding, a
    # refused fan-out, an empty list — and a `break` placed after any of them is a break
    # the target step can slip past. The list cannot.
    #
    # An unknown alias walks the WHOLE chain rather than none of it: a frontier nobody can
    # find is a caller's mistake, and answering it with an empty preview would look like a
    # chain that does nothing.
    walked = automation.effects
    if until_alias:
        cut = next((i for i, e in enumerate(walked) if alias_for(e, i) == until_alias), None)
        if cut is not None:
            walked = walked[:cut + 1]

    for i, effect in enumerate(walked):
        alias = alias_for(effect, i)
        # W2 — the list this step runs once per item of, or None for the single dispatch
        # every automation written before W2 performs, byte for byte. Resolved BEFORE the
        # params because an unresolvable SOURCE and an unresolvable param mean the same
        # thing — the upstream this step needs is not there — and must read the same way
        # in the run history rather than as two different failures.
        try:
            items = fan_items(effect, context,
                              dry_item=dry_fan_item(effect) if dry_run else None)
        except UnresolvedBinding as exc:
            outcomes.append(EffectOutcome(
                kind=effect.kind, target=alias, status="skipped",
                agent_id=acting_agent(effect, automation),
                message=f"upstream data unavailable: {exc}"))
            continue
        except FanRefused as exc:
            # Not an upstream absence — the step's OWN source is unusable — so it reads
            # as `invalid_params`, the status a dispatcher already returns for a config
            # it cannot use, rather than as a skip nobody investigates.
            outcomes.append(EffectOutcome(
                kind=effect.kind, target=alias, status="invalid_params",
                agent_id=acting_agent(effect, automation), message=str(exc)))
            continue
        if items is not None and not items:
            # An empty list is a SKIP, never a failure: "post per region that moved" on a
            # morning when nothing moved is the automation working. `skipped` also keeps
            # it out of `attempted` below, so a quiet morning cannot fire the fallback —
            # W1's lesson, which cost an on-call page to learn.
            outcomes.append(EffectOutcome(
                kind=effect.kind, target=alias, status="skipped",
                agent_id=acting_agent(effect, automation), message=FAN_EMPTY_SKIP))
            continue
        # One iteration for an ordinary step, N for a fanned one — the SAME body either
        # way. A fan-out that ran down a second dispatch path would be a second place for
        # the guard, the await, the span and the timing to each be subtly wrong.
        fan_count = 0 if items is None else len(items)
        iterations = [({}, 0)] if items is None else [
            (item_context(item), n + 1) for n, item in enumerate(items)]
        executed = 0
        published: dict = {}
        for item_ctx, fan_index in iterations:
            # The item is one more entry in the accumulated context, under a reserved
            # alias — not a second resolution mechanism. `{"$from": "item.channel"}` is
            # resolved by the same function, validated by the same checker and drawn by
            # the same canvas as `{"$from": "step1.ts"}`.
            step_context = context if not item_ctx else {**context, ITEM_ALIAS: item_ctx}
            label = alias if not fan_index else f"{alias}[{fan_index}/{fan_count}]"
            fan = {"fan_index": fan_index, "fan_count": fan_count}
            try:
                bound = resolve(effect.config, step_context)
                # W1 — the guard is evaluated in the SAME try as the params, because an
                # unresolvable reference means the same thing on either side: the upstream
                # this step depends on is not there. Evaluated BEFORE the dispatch, so a
                # guarded-off step costs nothing — no request, no token, no send.
                # W2 — and evaluated PER ITEM, which is the whole point of a guard on a
                # fanned step: "post the regions that moved" is a filter over the list,
                # and a guard checked once would make it all-or-nothing.
                # B2 — in a preview a guard is REPORTED, never decided. A sample cannot
                # answer "will tomorrow's number clear this threshold", and a dry run that
                # guessed would show a sound design as mostly held — the exact reading that
                # would send someone rewriting a chain that was fine.
                should_run, why_not = (True, "") if dry_run else evaluate_guard(effect, step_context)
            except UnresolvedBinding as exc:
                # SKIPPED, never run-with-a-hole. These steps send messages and write to
                # systems; a missing channel or a missing thread id is not a value to
                # default, and `skipped` already exists precisely for "did not run, and
                # that is not a failure of this step".
                outcomes.append(EffectOutcome(
                    kind=effect.kind, target=label, status="skipped", **fan,
                    agent_id=acting_agent(effect, automation),
                    message=f"upstream data unavailable: {exc}"))
                continue
            if not should_run:
                # `skipped`, whose own definition is "did not run, and that is not a failure
                # of this step" — which is precisely a guard holding. The MESSAGE carries the
                # difference between a design working and an upstream breaking, and it is the
                # one thing a reader needs at 09:00.
                outcomes.append(EffectOutcome(
                    kind=effect.kind, target=label, status="skipped", **fan,
                    agent_id=acting_agent(effect, automation),
                    message=f"{GUARD_SKIP}: {why_not}"))
                continue
            # VA-13 — does anything LATER bind to this step's output?
            #
            # Only a step somebody is waiting on should be waited FOR. `investigate` submits a
            # background job and returns a job id, which is the right shape for "run this
            # nightly" and useless for "post its answer into Slack": there is no answer yet
            # when the next step runs. So the engine tells the step, and only a step that is
            # actually consumed pays the latency.
            #
            # Derived from `effect_refs` — the same function the graph's data edges come from
            # — so "the canvas drew an edge here" and "the engine waited here" cannot disagree.
            # Carried on the bound config rather than in the dispatcher signature: six
            # dispatchers would otherwise grow a parameter five of them ignore.
            if _downstream_binds(alias, automation.effects[i + 1:]):
                bound = {**bound, AWAIT_KEY: True}
            step_started = now_iso_z()
            step_t0 = _time.monotonic()
            # VA-4d — one span per step, under the run's trace. `Activity → Runs` is "one
            # layer over one substrate (session_events)", and an automation emitted NOTHING
            # into it — which is why its runs were invisible there and needed a bespoke
            # canvas. A span per step makes an automation run a run like any other: waterfall,
            # events, logs, filters and cost, none of it designed twice.
            # W2 — one span per ITERATION, named for it. N sends that shared one span would
            # be one bar in the waterfall standing for work that happened N times, and the
            # trace canvas folds adjacent like-with-like into a stack on its own.
            bound_effect = effect.model_copy(update={"config": bound})
            if dry_run:
                # NO SPAN. VA-4d made the run id the trace id, so a dry run under a span
                # would appear in `Activity` as a run that happened — a preview must leave
                # the record exactly as it found it.
                outcome = _run_effect(bound_effect, automation, dispatch_fn, sleeper=sleeper,
                                      rng=rng, sleep_budget=sleep_budget)
            else:
                with _step_span(effect, automation, label, run_id):
                    outcome = _run_effect(bound_effect, automation, dispatch_fn,
                                          sleeper=sleeper, rng=rng, sleep_budget=sleep_budget)
            step_ms = (_time.monotonic() - step_t0) * 1000.0
            # Stamped HERE rather than in each dispatcher: six dispatchers each remembering to
            # set it is six chances to forget, and a step that silently ran as nobody is
            # exactly the gap this wave closes.
            outcome = outcome.model_copy(update={
                "agent_id": acting_agent(effect, automation),
                # Stamped at the call site for the same reason as the agent: six dispatchers
                # each remembering to time themselves is six chances to forget, and a step
                # with no duration is invisible in exactly the view built to find slow ones.
                "duration_ms": round(step_ms, 1), "started_at": step_started, **fan})
            if dry_run:
                guard = guard_clauses(effect)
                fanned_note = (" · once per item at run time"
                               if fan_index and is_binding(fan_source(effect)) else "")
                outcome = outcome.model_copy(update={
                    # What a later step will be able to read — declared keys plus whatever
                    # the later steps actually ask for, so the open set works too.
                    "data": dry_sample(alias, effect, automation.effects[i + 1:]),
                    # The guard, named as a question that has not been asked yet.
                    "message": outcome.message + fanned_note + (
                        f" · only if {' and '.join(render_clause(c) for c in guard)}"
                        " — checked when it runs" if guard else ""),
                })
            outcomes.append(outcome)
            if outcome.status == "executed":
                executed += 1
                published = dict(outcome.data or {})
        # Only a step that EXECUTED contributes. A failed step publishing an empty dict
        # would let a downstream binding resolve to nothing and run anyway — the exact
        # silent-hole this guards against.
        #
        # W2 — a fanned step publishes its COUNT and nothing else. There are N per-item
        # values and `{"$from": "step2.ts"}` could only mean one of them, so `validate_chain`
        # refuses that binding at save; what remains useful downstream is "did any of them
        # go out, and how many", which a guard can read.
        if not executed:
            continue
        context[alias] = {"count": executed} if fan_count else published

    # 4 — fallback, only when EVERY effect failed to execute
    fallback_used = False
    # W1 — a run whose every step was SKIPPED did not fail; before the guard existed a
    # step-1 skip was impossible, so `all(not executed)` and "everything failed" were the
    # same set. They no longer are: an automation guarded off on a quiet morning would
    # have paged on-call to say the automation itself was broken. The fallback needs a
    # step that actually TRIED and did not succeed.
    attempted = [o for o in outcomes if o.status != "skipped"]
    # DS-2 — a PARTIAL walk cannot conclude that everything failed. Firing the fallback
    # because the reader stopped early would report a disaster they caused by asking a
    # question, and it is the one part of a preview that reads as a verdict.
    partial = until_alias is not None and len(walked) < len(automation.effects)
    if (automation.fallback_effect is not None and attempted and not partial
            and all(o.status != "executed" for o in attempted)):
        fallback_used = True
        outcomes.append(_run_effect(automation.fallback_effect, automation, dispatch_fn,
                                    sleeper=sleeper, rng=rng, sleep_budget=sleep_budget))

    # 5 — the tick FIRED: commit source-version baselines now, and only now. Committing at
    # probe time would consume a change whenever the other condition of an `all` automation
    # was false — seen once, fired never (probes.py module docstring). Best-effort: an
    # uncommitted baseline re-fires the change next tick (at-least-once, never lost).
    try:
        from aughor.automations.probes import commit_fired_baselines
        # B2 — NOT in a preview. This runs regardless of `persist`, so a dry run would
        # consume a source change and the real tick would then find nothing new: a
        # preview that alters the next real run is not a preview.
        if not dry_run:
            commit_fired_baselines(automation)
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "baseline commit is best-effort; the fired run is already recorded",
                 counter="automations.engine.baseline_commit")

    return _finish(AutomationRun(**base, outcome="fired", reason=reason,
                                 conditions_fired=details, effects=outcomes,
                                 fallback_used=fallback_used))
