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
import threading
import time as _time
import uuid as _uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from aughor.automations.dataflow import (
    BRANCH_SKIP, FAN_EMPTY_SKIP, GUARD_SKIP, ITEM_ALIAS, MAX_FAN_OUT, FanRefused,
    UnresolvedBinding,
    alias_for, effect_refs, else_target, evaluate_guard_verdict, fan_items, fan_source,
    guard_clauses, is_binding, item_context, item_refs, parse_ref, render_clause, resolve,
)
from aughor.automations.models import (
    Automation,
    AutomationRun,
    Condition,
    Effect,
    EffectOutcome,
)
from aughor.automations.store import append_run, last_run, update_run
from aughor.util.time import now_iso_z

logger = logging.getLogger(__name__)

ConditionProbe = Callable[[Condition, Automation], "tuple[bool, str]"]
Dispatch = Callable[[Effect, Automation], EffectOutcome]

#: DS-9 — how deep chains may nest. Cycles are refused at SAVE, so this is not the cycle
#: guard; it is the guard for the shape a cycle check cannot see — a legal 40-deep tree
#: that a person built one honest edge at a time. Each level holds a scheduler thread and
#: runs a whole chain, so the cost is not linear in a way anyone would notice until it is.
MAX_SUBCHAIN_DEPTH = 5


@dataclass(frozen=True)
class _ChainContext:
    """DS-9 — what a nested run inherits from the run that invoked it.

    A ContextVar rather than a parameter on ``Dispatch``, because ``Dispatch`` is
    ``(effect, automation)`` and six dispatchers would otherwise grow three arguments five
    of them ignore — the argument `_execute_step` already makes about `AWAIT_KEY`. It also
    reaches the right place on its own under DS-7: the parallel driver submits through
    `ContextThreadPoolExecutor`, which copies the context into each worker, so a subchain
    inside a parallel step inherits exactly what a sequential one does.

    ``trace_id`` is the PARENT's, so a nested chain's steps land in one waterfall instead of
    two unrelated ones (the run id is still the trace id for a top-level run — VA-4d — and
    this only ever overrides it downward). ``dispatch`` rides along because the child must
    dispatch the way its parent does: a test that injected a double into the parent and got
    the real Slack client in the child would be proving nothing about the chain it wrote.
    """
    trace_id: str = ""
    depth: int = 0
    dispatch: Optional[Dispatch] = None
    sleeper: Optional[Callable[[float], None]] = None
    rng: Optional[Callable[[], float]] = None


_CHAIN: ContextVar[_ChainContext] = ContextVar("automation_chain", default=_ChainContext())


#: Total wall-clock a single tick may spend sleeping between retries. A background tick holds a
#: scheduler thread while it waits, so the retry budget is bounded regardless of what an operator
#: configures per automation.
MAX_RETRY_SLEEP_SECONDS = 120.0

#: DS-7 — the most steps a `scheduling="parallel"` automation runs at once. These steps
#: post messages, call LLMs and query warehouses; the point of the frontier is that two
#: independent investigations OVERLAP, not that fifty steps stampede whatever rate limit
#: is behind them. A cap on concurrency, never on completion: every ready step still
#: runs, some simply wait for a slot.
MAX_PARALLEL_STEPS = 4


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

def _stage_approval(effect: Effect, automation: Automation, *, alias: str, run_id: str,
                    message: str) -> str:
    """DS-8 — turn a step's ``approval_required`` verdict into a durable inbox proposal.

    Before this, a governed write inside an automation reached the executor, was refused for
    want of an approval, and the refusal was recorded on the run as a status nobody could act
    on: the run finished, the chain's later steps ran without it, and the only trace was a row
    in `needs human` whose "resolve" link went to the automation rather than to anything that
    could actually approve the write. There was no artefact to approve.

    The proposal IS that artefact, and it is deliberately the same one the agent and the HTTP
    surface stage — one inbox, one resolve-once UPDATE, one expiry, one audit trail. Nothing
    here is a second approval mechanism; DS-8's whole claim is that the governance plane
    already existed and the automation plane simply never reached it.

    Idempotent by ``(run_id, call_id)``, which is what makes the pause safe to re-enter: the
    scheduler may run this tick again after a crash between the dispatch and the run write, and
    the second stage returns the row the first one made rather than asking a human to approve
    the same write twice. ``call_id`` is the STEP LABEL, not the step index — a fanned step
    stages one proposal per item (`send[2/3]`), and an index would have collapsed them.

    Returns the proposal id, or "" if staging failed. A failure here must not take the run
    down: the outcome is already recorded, and a run that parked without a proposal is
    recoverable (the next tick stages it), while a run that crashed mid-chain is not.
    """
    try:
        from aughor.actions.inbox import StagedProposal, stage_proposal
        # DS-11's completion — the two shapes a governed write can have. `connection_id`
        # stays the AUTOMATION's warehouse connection in both, because that is what the
        # inbox filters, groups and purges by: putting a vault grant there would have
        # hidden every integration proposal from the queue that exists to show them.
        integration = effect.kind == "integration_call"
        staged = stage_proposal(StagedProposal(
            connection_id=automation.conn_id,
            schema_name=effect.config.get("schema_name") or "",
            kind="integration" if integration else "declared_action",
            grant_id=(str(effect.config.get("connection_id", "")) if integration else ""),
            action_id=(str(effect.config.get("operation", "")) if integration
                       else effect.action_id),
            # The RESOLVED params — what this step would actually have written. A proposal
            # freezes its params at stage time (RC-3), and freezing `{"$from": "step1.total"}`
            # would freeze a reference whose meaning moves, not a value a human can weigh.
            params=effect.params,
            reasoning=message,
            proposer=acting_agent_ref(effect, automation) or "automation",
            # `automation:<id>` — the label `inbox._owner_of` already parses, so a grant minted
            # from this accept is owned by the automation and revoked with it.
            source=f"automation:{automation.id}",
            run_id=run_id, call_id=alias,
        ))
        return staged.id
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "staging an approval proposal is best-effort; the run parks either way "
                      "and the next tick re-stages it",
                 counter="automations.engine.stage_approval")
        return ""


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
    # DS-7 — `parallel_refused` is R5's verdict (this action is not declared
    # parallel-safe, and the run is inside a declared fan-out), first reachable from an
    # automation now that steps can run concurrently. A verdict, not a fault: the same
    # inputs refuse identically next attempt, so it maps to the terminal
    # `dispatch_error` rather than the retriable `failed` — retrying a refusal is the
    # #200 lesson — and the message names the region verbatim.
    if result.status == "parallel_refused":
        return EffectOutcome(kind=effect.kind, target=effect.action_id,
                             status="dispatch_error", message=result.message)
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
                         #
                         # `summary` is the report's executive summary, same absent-when-
                         # empty rule. It exists because the headline is a title: the
                         # nightly briefing chain was posting 71 characters of "Revenue
                         # Analysis: …" while the trust warning and the numbers stayed in
                         # a report Slack never saw.
                         data={k: v for k, v in (("investigation_id", _inv),
                                                 ("answer", run.headline),
                                                 ("summary", run.summary)) if v})


# ── DS-9 · a chain as a step ──────────────────────────────────────────────────

def _dispatch_subchain(effect: Effect, automation: Automation) -> EffectOutcome:
    """Run another automation as one step.

    Composition is the point: "post it, and if that fails tell on-call" is one shape that
    every chain in the library wants, and before this the only way to have it twice was to
    author it twice — which is also how it comes to be authored differently in each place.

    The child runs as if someone pressed **Run now**: its own conditions are not re-asked.
    A chain that invokes another is stating WHEN it should happen, and a child whose trigger
    is "every Monday 09:00" would answer "not due" to every caller on every other day —
    a shared subchain that works only on Mondays is not a shared subchain. Its lifecycle
    gates still apply, though, and deliberately: `enabled=False` and an expiry are a person
    saying "this must not run", and a caller is not an exemption from that.

    The child keeps its OWN run row — it belongs in its own history, and a shared subchain's
    history is the one place you can see every caller that used it — but writes its steps
    under the PARENT's trace, so a nested chain reads as one waterfall.
    """
    from aughor.automations.store import get_automation

    ctx = _CHAIN.get()
    child_id = effect.automation_id
    if child_id == automation.id:
        # Belt to the save-time cycle check's braces. A self-reference is the one cycle that
        # needs no second automation to construct, so it is the one most likely to arrive
        # through a path that never saw the validator (a fixture, a direct store write).
        return EffectOutcome(kind=effect.kind, target=child_id, status="dispatch_error",
                             message="a chain cannot run itself")
    if ctx.depth >= MAX_SUBCHAIN_DEPTH:
        return EffectOutcome(
            kind=effect.kind, target=child_id, status="dispatch_error",
            message=(f"subchains nested deeper than {MAX_SUBCHAIN_DEPTH} — refusing to go "
                     f"further. This is not a cycle (those are refused when you save); it is "
                     f"a legal tree that got too deep to run as one tick."))
    child = get_automation(child_id)
    if child is None:
        return EffectOutcome(kind=effect.kind, target=child_id, status="dispatch_error",
                             message=f"no automation '{child_id}' — it may have been deleted")

    token = _CHAIN.set(_ChainContext(trace_id=ctx.trace_id, depth=ctx.depth + 1,
                                     dispatch=ctx.dispatch, sleeper=ctx.sleeper, rng=ctx.rng))
    try:
        run = run_automation(child, manual=True, persist=True)
    finally:
        _CHAIN.reset(token)

    return subchain_outcome(effect.kind, child_id, child.name, run)


def subchain_outcome(kind: str, child_id: str, child_name: str,
                     run: AutomationRun) -> EffectOutcome:
    """What a subchain step reports, given what the child run actually did.

    ONE mapping, called from the dispatcher and again from the resume — because a parent
    parked on a child rewrites this step from the child's FINAL outcome, and two copies of
    "what does a gated child mean" is how the live path and the resumed path come to
    disagree about whether a chain succeeded.
    """
    executed = sum(1 for o in run.effects if o.status == "executed")
    published = {"run_id": run.id, "outcome": run.outcome, "executed": executed}
    if run.outcome == "paused":
        # DS-8 met DS-9. The child stopped mid-chain for a human, so the parent has NOT
        # finished this step — and a parent that walked on would run the steps after a
        # governed write that has not happened yet, which is the exact failure a mid-chain
        # approval exists to prevent, one level up. `approval_required` is the status the
        # parent's driver parks on, and `child_run_id` is what the resume waits for.
        return EffectOutcome(
            kind=kind, target=child_id, status="approval_required",
            message=f"'{child_name}' is waiting on a human: {run.reason}",
            data={**published, "child_run_id": run.id})
    if run.outcome in ("gated", "not_fired"):
        # Not a failure of this step: the child declined to run, and `skipped` is this
        # engine's word for exactly that. Folding it into `failed` would let a disabled
        # subchain fire the parent's fallback and page on-call about a switch someone
        # deliberately flipped.
        return EffectOutcome(kind=kind, target=child_id, status="skipped",
                             message=f"'{child_name}' did not run: {run.reason}",
                             data=published)
    if run.outcome == "error":
        return EffectOutcome(kind=kind, target=child_id, status="failed",
                             message=f"'{child_name}' failed: {run.error or run.reason}",
                             data=published)
    return EffectOutcome(
        kind=kind, target=child_id, status="executed",
        message=f"'{child_name}' ran {executed} step{'' if executed == 1 else 's'}",
        data=published)


#: DS-11 — the call seam's verdicts, mapped onto the outcome vocabulary this plane has
#: always had. Written as a table rather than a chain of ifs because the mapping IS the
#: contract between two planes, and the interesting half is which verdicts are terminal:
#:
#: * ``refused`` → ``dispatch_error``. A verdict, not a fault: an unknown operation, a
#:   revoked grant, a missing scope and an un-allowlisted write all refuse identically
#:   next attempt, so retrying is the #200 lesson repeated.
#: * ``blocked`` → ``failed``. A usage cap sent nothing, so the same call is legitimate
#:   once the window rolls over — which is what `failed` licenses and `dispatch_error`
#:   does not. The same mapping `slack_post` already makes for a capped post.
#: * ``uncertain`` → ``uncertain``. A write whose transport broke may have arrived, and
#:   retrying a maybe-delivered write is the duplicate that status exists to prevent.
#: * ``needs_approval`` → ``approval_required``. The one verdict here that is a QUESTION
#:   rather than a fact: a person can answer it, so the call site stages a proposal and
#:   the run PARKS on them (DS-8's machinery, reached through the inbox's second proposal
#:   kind). Every other refusal describes a world no amount of looking at it changes.
_CALL_STATUS: dict[str, str] = {
    "executed": "executed", "refused": "dispatch_error", "blocked": "failed",
    "failed": "failed", "uncertain": "uncertain",
    "needs_approval": "approval_required",
}


def _dispatch_integration(effect: Effect, automation: Automation) -> EffectOutcome:
    """DS-11 — one step run under a user's own grant, through the one governed door.

    Everything that makes this governed happens in `integrations.call.call_operation`:
    the grant's verdicts, the scope check, the approval gate for a write, the outbound
    cap and span, the `EXTERNAL_CALL` event and the audit line. This function is the
    translation layer and nothing else — deliberately, because the same call has to be
    makeable from a route and from an agent later without either re-deriving the order
    those gates run in.

    ``target`` is ``<connection>:<operation>``, and BOTH halves are load-bearing. DS-8's
    live run found the general shape of this mistake the hard way: a dispatcher that
    names its target after the thing it dispatched publishes the step's context where no
    binding can reach it. The operation alone would also make two steps spending two
    different grants look identical in a run history, which is the one question this
    kind's history exists to answer.
    """
    from aughor.integrations.call import call_operation

    conn_id = str(effect.config.get("connection_id", ""))
    operation = str(effect.config.get("operation", ""))
    target = f"{conn_id}:{operation}"
    result = call_operation(conn_id, operation, effect.params,
                            actor=acting_agent_ref(effect, automation))
    status = _CALL_STATUS.get(result.status, "failed")
    return EffectOutcome(
        kind=effect.kind, target=target, status=status,
        # The provider's own sentence, verbatim — the same contract the authored
        # criterion message has. A paraphrase of "channel_not_found" helps nobody.
        message=result.message,
        # Published on SUCCESS only. A failed call's body is the provider's error, not
        # this operation's declared keys, and publishing it would let a later step bind
        # to a value that means something else entirely.
        data=dict(result.data) if status == "executed" else {})


@contextmanager
def _warehouse(automation: Automation):
    """The automation's own data connection, closed on every path.

    The org is NOT bound here: `scheduler.py` binds it around the whole run (DATA-06,
    because a background tick carries no request context), and a second binder inside one
    step would be a second authority on which tenant the run belongs to.
    """
    from aughor.db.connection import open_connection_for

    db = open_connection_for(automation.conn_id)
    try:
        yield db
    finally:
        try:
            db.close()
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "closing an automation step's db handle is best-effort; the "
                          "result is already computed", counter="automation.db_close")


def _dispatch_metric_value(effect: Effect, automation: Automation) -> EffectOutcome:
    """DS-12 — read a GOVERNED metric, by the name someone approved.

    The step carries a name, never SQL. That is the moat this wave is named for: the
    number a chain acts on is the one the metric registry defines — filters, caveats and
    all — rather than one an LLM re-derived or an author typed into a config field. A
    chain that guards on `revenue.value` is guarding on Finance's revenue.

    The value comes from `semantic.metrics.compute_value`, which is the ONE place that
    knows how to turn a definition into a query. Before DS-12 there were two, they
    disagreed, and — measured live — neither had ever run.
    """
    from aughor.semantic.metrics import compute_value, get_metric

    name = effect.metric
    # SCOPED to the automation's connection, because a connection-scoped definition
    # SHADOWS the global one of the same name (the one rule `list_metrics` states). An
    # unscoped read here would compute the global "revenue" on a connection that has
    # deliberately redefined it — the exact class of silently-wrong number a governed
    # metric registry exists to prevent.
    metric = get_metric(name, connection_id=automation.conn_id)
    if metric is None:
        return EffectOutcome(kind=effect.kind, target=name, status="dispatch_error",
                             message=f"unknown metric: {name}")
    try:
        with _warehouse(automation) as db:
            computed = compute_value(metric, db)
    except KeyError:
        return EffectOutcome(kind=effect.kind, target=name, status="dispatch_error",
                             message=f"unknown connection: {automation.conn_id}")
    if computed.error:
        return EffectOutcome(kind=effect.kind, target=name, status="failed",
                             message=f"{metric.label} could not be computed: {computed.error}")
    unit = metric.unit or ""
    shown = "no value" if computed.value is None else f"{computed.value:g}{unit}"
    return EffectOutcome(
        kind=effect.kind, target=name, status="executed",
        message=f"{metric.label} = {shown}",
        # `value` may be None — a metric whose filters matched nothing has an answer,
        # and a guard reading it with `falsy` is the honest way to ask "did we get one".
        data={"value": computed.value, "unit": unit, "label": metric.label})


def _dispatch_trusted_query(effect: Effect, automation: Automation) -> EffectOutcome:
    """DS-12 — run a VETTED query and publish its rows: the plane's first declared list.

    §3.2 carried "nothing in this plane publishes a list" as an honest limit, so a
    `for_each` could only fan over a literal. This is the step that closes it, and it
    closes it with the safe half of the problem: the SQL is stored, reviewed and named by
    id, so gaining row-lists costs the plane no expression surface at all.

    The row cap REFUSES rather than truncates, which is W2's law one plane over: a chain
    that fans over the first 50 of 4,000 rows sends fifty messages and reads as though it
    sent all of them. The label is NOT the internal dunder form `compute_value` uses —
    these are ROWS, and the PII/audit post-pass must stay armed for them.
    """
    from aughor.semantic.trusted_queries import list_trusted

    query_id = effect.query_id
    match = next((q for q in list_trusted(automation.conn_id) if q.id == query_id), None)
    if match is None:
        # Scoped to THIS automation's connection: a trusted query is verified against the
        # schema it was written for, and running one against another connection is how a
        # vetted query stops being vetted.
        return EffectOutcome(kind=effect.kind, target=query_id, status="dispatch_error",
                             message=f"no trusted query '{query_id}' on this connection")

    cap = MAX_FAN_OUT
    try:
        with _warehouse(automation) as db:
            # cap + 1, so "there were more" is a fact rather than an inference from a
            # result that happens to be exactly full.
            result = db.execute_bounded(
                f"automation:{automation.id}:{effect.alias or effect.kind}",
                match.sql, cap + 1)
    except KeyError:
        return EffectOutcome(kind=effect.kind, target=query_id, status="dispatch_error",
                             message=f"unknown connection: {automation.conn_id}")
    if getattr(result, "error", None):
        return EffectOutcome(kind=effect.kind, target=query_id, status="failed",
                             message=f"'{match.question}' failed: {result.error}")

    columns = list(getattr(result, "columns", None) or [])
    raw = list(getattr(result, "rows", None) or [])
    if len(raw) > cap:
        return EffectOutcome(
            kind=effect.kind, target=query_id, status="failed",
            message=(f"'{match.question}' returned more than {cap} rows — refused rather "
                     f"than truncated, because acting on the first {cap} reads as acting "
                     f"on all of them; narrow the query or add a LIMIT to it"))

    rows = [dict(zip(columns, r)) if isinstance(r, (list, tuple)) else dict(r) for r in raw]
    return EffectOutcome(
        kind=effect.kind, target=query_id, status="executed",
        message=f"'{match.question}' — {len(rows)} row{'' if len(rows) == 1 else 's'}",
        data={"rows": rows, "columns": columns, "count": len(rows)})


_DISPATCHERS: dict[str, Callable[[Effect, Automation], EffectOutcome]] = {
    "kinetic_action": _dispatch_kinetic,
    "notify": _dispatch_notify,
    "brief": _dispatch_brief,
    "investigate": _dispatch_investigate,
    "monitor": _dispatch_monitor,
    "agent_alert": _dispatch_agent_alert,
    "slack_post": _dispatch_slack_post,
    "subchain": _dispatch_subchain,
    "integration_call": _dispatch_integration,
    "metric_value": _dispatch_metric_value,
    "trusted_query": _dispatch_trusted_query,
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
    # DS-11 — `published_keys(effect)`, not the kind table: an integration step's keys
    # are its operation's, so a preview of a Gmail-list step must sample `items`/`count`
    # and one of a read-a-message step must sample `snippet`. Reading the kind would have
    # sampled the same (empty) set for both and reported every chained integration step
    # as unavailable — the exact failure B2's own pre-check found in the eval harness.
    from aughor.automations.dataflow import published_keys
    keys = set(published_keys(effect) or ())
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


def _walk_automation(
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
    resume: Optional[dict] = None,
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

    def _finish(run: AutomationRun, *, finished: bool = True) -> AutomationRun:
        elapsed_ms = int((_time.monotonic() - t0) * 1000) + int(
            (resume or {}).get("prior_duration_ms") or 0)
        stamp = (now + timedelta(milliseconds=elapsed_ms)).isoformat().replace("+00:00", "Z")
        run = run.model_copy(update={
            # DS-8 — a PAUSED run has no `finished_at`, because it has not finished. Stamping
            # one would make every duration reader (the waterfall header, the run list, the
            # slow-step view) report the length of the machine's half as though it were the
            # length of the run, and a run that waited two days on a human would read as 40ms.
            # `duration_ms` is still the work actually done so far, and the resume adds to it.
            "finished_at": stamp if finished else None,
            "duration_ms": elapsed_ms,
        })
        if not persist:
            return run
        # A resumed run UPDATES the row it parked in — one run, one trace id, a human in
        # its middle. `append_run` is INSERT OR IGNORE, so it would silently do nothing.
        return update_run(run) if resume else append_run(run)

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
    # DS-9 — the trace this run's steps are written under. For a top-level run it IS the run
    # id, unchanged since VA-4d ("clicking a run in Activity lands on exactly this run, with
    # no second correlation key"). For a NESTED one it is the parent's, so an automation that
    # invokes an automation reads as one waterfall with the child's steps inside it instead of
    # two unrelated traces nobody can join. The run ROW keeps its own id either way — a child
    # belongs in its own history too.
    trace_id = _CHAIN.get().trace_id or run_id
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
    if gate_reason is not None and not dry_run and not resume:
        # DS-8 — a RESUME is not gated. The gates ask "should this automation start work
        # now"; a resumed run started its work before the gate ever closed, and the human
        # who approved its pending write is owed the rest of the chain. Pausing or expiring
        # an automation must not strand a governed write a person already said yes to —
        # that is a half-executed chain, which is worse than either finishing or not
        # starting. Disabling still stops the NEXT tick, which is what disabling is for.
        return _finish(AutomationRun(**base, outcome="gated", reason=gate_reason))

    # 2 — conditions
    if resume:
        # Already evaluated, in the tick that parked. Re-probing here would ask a warehouse
        # the same question a second time and — worse — could answer it differently, so a
        # run whose conditions had since stopped holding would abandon a chain mid-way with
        # an approved write already committed.
        fired = True
        details = list((resume.get("conditions_fired") or []))
        reason = str(resume.get("reason") or "")
    elif dry_run:
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
    if persist and not resume and has_outward_effect(automation):
        # Not on a resume: the tick that parked already claimed this period, and a second
        # claim for the same period is exactly the double-send 4.1a exists to stop.
        claim_delivery(automation.id, started)
    sleep_budget = [MAX_RETRY_SLEEP_SECONDS]


    # VA-4a — a CHAIN, not a list comprehension. Each effect sees the accumulated output
    # of every prior step (merged-data, à la `andThen`), which is what makes "post the
    # answer from step 1 into the thread step 2 opened" expressible at all. Before this,
    # every effect received only (effect, automation, dispatch): there was no dataflow,
    # so a designed workflow could draw arrows the engine would not have followed.
    # DS-8 — on a resume these two start from the checkpoint, not empty. They are the
    # whole of what "accumulated context" means: everything the parked steps published for
    # later steps to bind to, and the guard verdicts the routes read. Rebuilt from the run
    # row rather than recomputed, because recomputing would mean re-running the steps that
    # produced them — the one thing a durable pause exists to avoid.
    context: dict[str, dict] = dict((resume or {}).get("checkpoint", {}).get("context") or {})
    outcomes: list[EffectOutcome] = []
    # DS-6 — each unfanned step's guard VERDICT: True (held, the step went on), False
    # (did not hold), or None/absent (never decided — upstream missing, or a comparison
    # that could not be made). The route reads exactly this, so it adds no second
    # dataflow: the guard's own references are already validated, awaited and drawn.
    verdicts: dict[str, Optional[bool]] = dict(
        (resume or {}).get("checkpoint", {}).get("verdicts") or {})

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

    # DS-7 — a PREVIEW always walks in declared order, even on a parallel automation.
    # The inert dispatcher is instant, so there is nothing to overlap; what parallelism
    # would add to a dry run is only nondeterministic sample ordering — a preview that
    # reads differently on every press answers no question anyone asked.
    scheduling_parallel = (
        getattr(automation, "scheduling", "ordered") == "parallel" and not dry_run)

    def _execute_step(i: int, effect: Effect, *, context: dict, verdicts: dict,
                      sleep_budget: list[float]) -> tuple[
                          "list[EffectOutcome]", Optional[dict], bool, Optional[bool]]:
        """One step, against a VIEW of the chain state — the whole per-step body,
        extracted so the ordered walk and DS-7's frontier drive the SAME code.

        Two drivers over a second copy of this body is how the guard, the route, the
        await, the span and the timing each get to be subtly wrong in exactly one of
        them (the fan-out made the same argument about a second dispatch path, one
        level down). Returns ``(outcomes, context entry to publish or None,
        verdict recorded?, verdict)`` — the DRIVER merges, because under the frontier
        the merge needs a lock and this body must not know that.
        """
        alias = alias_for(effect, i)
        step_outcomes: list[EffectOutcome] = []
        # DS-6 — the route, decided before anything else about this step: whether an
        # OTHERWISE arm is taken depends only on the deciding step's guard verdict, so
        # an untaken arm costs nothing — not even a fan-source resolve. Only a verdict
        # of False takes the arm: True means the other path went, and None means the
        # decision was never made (upstream missing, or a comparison that could not be
        # made) — routing on a guess is the one thing a route must never do, so an
        # undecided branch takes NEITHER arm and the join downstream skips honestly.
        # B2 — in a preview the route is REPORTED, never decided (guards are samples);
        # the arm's message says whose otherwise it is, below.
        route_from = else_target(effect)
        if route_from and not dry_run:
            verdict = verdicts.get(route_from)
            if verdict is not False:
                step_outcomes.append(EffectOutcome(
                    kind=effect.kind, target=alias, status="skipped",
                    agent_id=acting_agent(effect, automation),
                    message=(f"{BRANCH_SKIP}: '{route_from}' met its condition"
                             if verdict is True else
                             f"{BRANCH_SKIP}: '{route_from}' was not decided")))
                return step_outcomes, None, False, None
        # W2 — the list this step runs once per item of, or None for the single dispatch
        # every automation written before W2 performs, byte for byte. Resolved BEFORE the
        # params because an unresolvable SOURCE and an unresolvable param mean the same
        # thing — the upstream this step needs is not there — and must read the same way
        # in the run history rather than as two different failures.
        try:
            items = fan_items(effect, context,
                              dry_item=dry_fan_item(effect) if dry_run else None)
        except UnresolvedBinding as exc:
            step_outcomes.append(EffectOutcome(
                kind=effect.kind, target=alias, status="skipped",
                agent_id=acting_agent(effect, automation),
                message=f"upstream data unavailable: {exc}"))
            return step_outcomes, None, False, None
        except FanRefused as exc:
            # Not an upstream absence — the step's OWN source is unusable — so it reads
            # as `invalid_params`, the status a dispatcher already returns for a config
            # it cannot use, rather than as a skip nobody investigates.
            step_outcomes.append(EffectOutcome(
                kind=effect.kind, target=alias, status="invalid_params",
                agent_id=acting_agent(effect, automation), message=str(exc)))
            return step_outcomes, None, False, None
        if items is not None and not items:
            # An empty list is a SKIP, never a failure: "post per region that moved" on a
            # morning when nothing moved is the automation working. `skipped` also keeps
            # it out of `attempted` below, so a quiet morning cannot fire the fallback —
            # W1's lesson, which cost an on-call page to learn.
            step_outcomes.append(EffectOutcome(
                kind=effect.kind, target=alias, status="skipped",
                agent_id=acting_agent(effect, automation), message=FAN_EMPTY_SKIP))
            return step_outcomes, None, False, None
        # One iteration for an ordinary step, N for a fanned one — the SAME body either
        # way. A fan-out that ran down a second dispatch path would be a second place for
        # the guard, the await, the span and the timing to each be subtly wrong.
        fan_count = 0 if items is None else len(items)
        iterations = [({}, 0)] if items is None else [
            (item_context(item), n + 1) for n, item in enumerate(items)]
        executed = 0
        published: dict = {}
        verdict_known = False
        step_verdict: Optional[bool] = None
        for item_ctx, fan_index in iterations:
            # The item is one more entry in the accumulated context, under a reserved
            # alias — not a second resolution mechanism. `{"$from": "item.channel"}` is
            # resolved by the same function, validated by the same checker and drawn by
            # the same canvas as `{"$from": "step1.ts"}`.
            step_context = context if not item_ctx else {**context, ITEM_ALIAS: item_ctx}
            label = alias if not fan_index else f"{alias}[{fan_index}/{fan_count}]"
            fan = {"fan_index": fan_index, "fan_count": fan_count}
            try:
                # W1 — the guard is evaluated in the SAME try as the params, because an
                # unresolvable reference means the same thing on either side: the upstream
                # this step depends on is not there. Evaluated BEFORE the dispatch, so a
                # guarded-off step costs nothing — no request, no token, no send — and,
                # since DS-6, before the params resolve too: the guard reads only the
                # chain context, a held step must not pay for a resolve it will not use,
                # and the route needs the VERDICT even on a step whose own params are
                # broken (the decision is the guard's; the arm's health is the arm's).
                # W2 — and evaluated PER ITEM, which is the whole point of a guard on a
                # fanned step: "post the regions that moved" is a filter over the list,
                # and a guard checked once would make it all-or-nothing.
                # B2 — in a preview a guard is REPORTED, never decided. A sample cannot
                # answer "will tomorrow's number clear this threshold", and a dry run that
                # guessed would show a sound design as mostly held — the exact reading that
                # would send someone rewriting a chain that was fine.
                verdict, why_not = ((True, "") if dry_run
                                    else evaluate_guard_verdict(effect, step_context))
                # DS-6 — the verdict, recorded for the route. Unfanned steps only: a
                # fanned step's guard is N per-item verdicts, which is why the model
                # refuses `else_of` onto one at save. Unevaluable (None) is recorded as
                # exactly that — an OTHERWISE arm must not read "cannot compare" as
                # "did not hold".
                if items is None:
                    verdict_known, step_verdict = True, verdict
                should_run = verdict is True
                bound = resolve(effect.config, step_context) if should_run else {}
            except UnresolvedBinding as exc:
                # SKIPPED, never run-with-a-hole. These steps send messages and write to
                # systems; a missing channel or a missing thread id is not a value to
                # default, and `skipped` already exists precisely for "did not run, and
                # that is not a failure of this step".
                step_outcomes.append(EffectOutcome(
                    kind=effect.kind, target=label, status="skipped", **fan,
                    agent_id=acting_agent(effect, automation),
                    message=f"upstream data unavailable: {exc}"))
                continue
            if not should_run:
                # `skipped`, whose own definition is "did not run, and that is not a failure
                # of this step" — which is precisely a guard holding. The MESSAGE carries the
                # difference between a design working and an upstream breaking, and it is the
                # one thing a reader needs at 09:00.
                step_outcomes.append(EffectOutcome(
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
                with _step_span(effect, automation, label, trace_id):
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
            # DS-8 — a governed write that needs a human becomes a durable proposal, and the
            # proposal id rides on the outcome so the parked step on the run canvas links
            # straight to the thing that resolves it. Staged HERE, at the call site, for the
            # same reason the agent and the duration are stamped here: the dispatcher does not
            # know the run id, and the run id is half of the idempotency key.
            # DS-9 — but NOT when this step is only RELAYING a child's wait. A subchain step
            # reports `approval_required` because the chain it invoked parked; the human is
            # being asked by the child, which staged the proposal, and the parent is waiting
            # for the child. Staging a second proposal here would put a phantom approval in
            # the queue (for a step with no action to approve) and — worse — leave it pending
            # forever, because nothing resolves it and `resume_run` refuses to continue a run
            # with a pending proposal. The parent would never restart.
            relayed = bool((outcome.data or {}).get("child_run_id"))
            if outcome.status == "approval_required" and not dry_run and not relayed:
                pid = _stage_approval(bound_effect, automation, alias=label, run_id=run_id,
                                      message=outcome.message)
                if pid:
                    outcome = outcome.model_copy(
                        update={"data": {**(outcome.data or {}), "proposal_id": pid}})
            if dry_run:
                guard = guard_clauses(effect)
                fanned_note = (" · once per item at run time"
                               if fan_index and is_binding(fan_source(effect)) else "")
                # DS-6 — the route, named as a decision that has not been made yet: a
                # preview walks BOTH arms (a sample cannot say which way tomorrow's
                # guard goes), and an arm shown without its "otherwise" would read as a
                # step that always runs.
                route_note = (f" · otherwise of {else_target(effect)} — decided when "
                              "it runs" if else_target(effect) else "")
                outcome = outcome.model_copy(update={
                    # What a later step will be able to read — declared keys plus whatever
                    # the later steps actually ask for, so the open set works too.
                    "data": dry_sample(alias, effect, automation.effects[i + 1:]),
                    # The guard, named as a question that has not been asked yet.
                    "message": outcome.message + fanned_note + route_note + (
                        f" · only if {' and '.join(render_clause(c) for c in guard)}"
                        " — checked when it runs" if guard else ""),
                })
            step_outcomes.append(outcome)
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
        entry = ({"count": executed} if fan_count else published) if executed else None
        return step_outcomes, entry, verdict_known, step_verdict

    # ── the drivers — one body, two orders ────────────────────────────────────────
    #
    # DS-7. `ordered` is the strictly sequential walk every automation written before
    # this performs, byte for byte: each step sees everything before it. `parallel` is
    # the frontier: a step waits for the steps its ARROWS name — every reference in its
    # params, guard and fan source, plus its `else_of` target — and for nothing else.
    # The dependency set comes from the one `effect_refs` that validation, the await
    # and both canvases already read, so "may these overlap" and "is an edge drawn
    # between them" can never disagree. Forward references are refused at save, so the
    # graph is a DAG by construction and the frontier always progresses.
    # DS-8 — the step that parked this run on a human, once one has. Set by whichever
    # driver is walking; read once, below, to decide whether this tick FINISHED or merely
    # stopped. `None` is the overwhelmingly common case and the only one before DS-8.
    paused_at: Optional[tuple[int, str]] = None
    done_snapshot: list[str] = []
    # DS-8 — how many outcomes each step contributed. A fanned step contributes N, a
    # skipped one contributes 1, an unreached one contributes none, so the flat `effects`
    # list cannot be re-attributed to steps by position alone. Recorded on the checkpoint
    # so a RESUME can slice the parked run's effects back into per-step buckets and
    # reassemble the whole run in declared order — the property DS-7 established and that
    # every reader of a run's effects (`group_outcomes`, both canvases) depends on.
    step_counts: dict[int, int] = {}
    cp: dict = (resume or {}).get("checkpoint") or {}
    prior_by_index: dict[int, list] = (resume or {}).get("prior_by_index") or {}
    start_index: int = int(cp.get("next_index") or 0) if resume else 0

    if scheduling_parallel:
        from concurrent.futures import FIRST_COMPLETED
        from concurrent.futures import wait as _fut_wait

        from aughor.kernel.concurrency import ContextThreadPoolExecutor
        from aughor.kernel.parallel_safety import fanout_region as _fanout_region

        known_aliases = {alias_for(e, n) for n, e in enumerate(walked)}
        deps: dict[int, set[str]] = {}
        for n, e in enumerate(walked):
            refs = {parse_ref(r)[0] for r in effect_refs(e)}
            target = else_target(e)
            if target:
                refs.add(target)
            deps[n] = refs & known_aliases

        merge_lock = threading.Lock()
        done_aliases: set[str] = set()
        results: dict[int, list[EffectOutcome]] = {}
        scheduled: set[int] = set()
        pending: dict = {}
        if resume:
            # DS-8 — the frontier picks up where it parked. A step the earlier tick
            # completed is seeded as done, with its ORIGINAL outcomes in its slot, so the
            # assembly below still emits one run in declared order; its published values
            # are already in `context`, which is how the steps waiting on it can resolve
            # without it running twice.
            done_aliases |= {str(a) for a in (cp.get("done_aliases") or [])}
            for n, e in enumerate(walked):
                if alias_for(e, n) in done_aliases:
                    scheduled.add(n)
                    results[n] = list(prior_by_index.get(n) or [])
        # R5's declared-fan-out plane, entered BEFORE the pool so every submit copies
        # the label into its worker: a declared-action step dispatched inside this
        # region is checked by `assert_dispatchable` in the one governed executor, and
        # an action not declared parallel-safe is REFUSED with the region named — "two
        # refunds with no error anywhere" is the exact failure Wave R5 exists to stop,
        # and DS-7 is the first thing that makes it reachable from an automation.
        with _fanout_region("automations.parallel_steps"), ContextThreadPoolExecutor(
                max_workers=min(MAX_PARALLEL_STEPS, max(1, len(walked))),
                thread_name_prefix="automation-step") as pool:
            while len(results) < len(walked):
                with merge_lock:
                    # DS-8 — once a step has parked, schedule NOTHING further. Steps already
                    # in flight are allowed to land (they are dispatched; abandoning their
                    # outcomes would lose writes that really happened), but the frontier
                    # stops advancing: a step downstream of the parked one must not run
                    # before the human it is waiting on has answered.
                    ready = [] if paused_at else [
                        n for n in range(len(walked))
                        if n not in scheduled and deps[n] <= done_aliases]
                    # A SNAPSHOT per scheduling round, not the live dicts: a ready
                    # step's dependencies are complete, so everything it may read is
                    # already in the copy — while the live dict may gain entries from
                    # a worker mid-`{**context, ...}` merge, and a dict that changes
                    # size under iteration is a crash on an unrelated step.
                    ctx_snap = dict(context)
                    ver_snap = dict(verdicts)
                for n in ready:
                    scheduled.add(n)
                    # Each parallel step gets its OWN retry-sleep budget. The shared
                    # budget bounds how long a TICK sleeps, and parallel sleeps
                    # overlap — so per-step budgets keep the same wall-clock bound
                    # without two workers racing one float.
                    fut = pool.submit(_execute_step, n, walked[n],
                                      context=ctx_snap, verdicts=ver_snap,
                                      sleep_budget=[MAX_RETRY_SLEEP_SECONDS])
                    pending[fut] = n
                if not pending:
                    if paused_at:
                        # Parked, and everything that was in flight has landed. The steps
                        # with no entry in `results` have not run — which is the honest
                        # record: they have not happened YET.
                        break
                    # Unreachable by construction (forward refs are refused at save,
                    # so some incomplete step always has every dependency complete) —
                    # but a silent spin would be worse than a loud stop.
                    raise RuntimeError("automation frontier stalled with steps left")
                finished, _ = _fut_wait(list(pending), return_when=FIRST_COMPLETED)
                for fut in finished:
                    n = pending.pop(fut)
                    step_outcomes, entry, known, v = fut.result()
                    step_alias = alias_for(walked[n], n)
                    with merge_lock:
                        results[n] = step_outcomes
                        if known:
                            verdicts[step_alias] = v
                        if entry is not None:
                            context[step_alias] = entry
                        done_aliases.add(step_alias)
                        # DS-8 — the FIRST park wins. Two steps can reach an approval in the
                        # same round; each stages its own proposal (both are real writes
                        # awaiting a real human), and the run resumes when the last of them
                        # resolves, so which one is named as the parking step is only a
                        # label. Keeping the first keeps it deterministic.
                        if paused_at is None and any(
                                o.status == "approval_required" for o in step_outcomes):
                            paused_at = (n, step_alias)
        # Outcomes are assembled in DECLARED order whatever order the work finished
        # in: `group_outcomes` and every reader of a run's effects matches positions,
        # and a run history shuffled by scheduling luck would decorate the wrong cards.
        done_snapshot = sorted(done_aliases)
        for n in range(len(walked)):
            step_counts[n] = len(results.get(n) or [])
            # `.get` — a parked run leaves the steps beyond the frontier with no outcome
            # at all, which is exactly right: they have not run.
            outcomes.extend(results.get(n) or [])
    else:
        for i, effect in enumerate(walked):
            if i < start_index:
                # DS-8 — already run, in the tick that parked. Its outcomes are replayed into
                # position (never re-dispatched: "prior steps never re-run" is the wave's
                # whole claim) and its published context came back with the checkpoint.
                outcomes.extend(prior_by_index.get(i) or [])
                continue
            step_outcomes, entry, known, v = _execute_step(
                i, effect, context=context, verdicts=verdicts, sleep_budget=sleep_budget)
            outcomes.extend(step_outcomes)
            step_counts[i] = len(step_outcomes)
            alias = alias_for(effect, i)
            if known:
                verdicts[alias] = v
            if entry is not None:
                context[alias] = entry
            # DS-8 — park. The remaining steps are not skipped and not failed; they are
            # simply not yet run, so the walk STOPS rather than recording verdicts for
            # work that has not happened.
            if any(o.status == "approval_required" for o in step_outcomes):
                paused_at = (i, alias)
                break

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
    # DS-8 — nor can a PAUSED walk. `approval_required` is not `executed`, so a chain whose
    # only outward step is a governed write would satisfy "everything attempted failed" the
    # instant it parked — and fire the fallback to announce a disaster that is actually a
    # human being asked a question. Exactly W1's lesson (a quiet morning is not an outage)
    # one wave later, and the fallback still gets its chance: the resumed run runs this same
    # block with the pause resolved.
    if (automation.fallback_effect is not None and attempted and not partial
            and paused_at is None
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

    if paused_at is not None:
        # DS-8 — the run stopped, it did not finish. Baselines above were committed anyway
        # and deliberately: this tick DID fire, and leaving the source change unconsumed
        # would have the next heartbeat fire a second run for the same change and park a
        # second proposal in front of the same human.
        step_index, step_alias = paused_at
        waiting = [o for o in outcomes if o.status == "approval_required"]
        return _finish(AutomationRun(
            **base, outcome="paused",
            reason=(f"waiting on approval at '{step_alias}'"
                    + (f" ({len(waiting)} writes)" if len(waiting) > 1 else "")),
            conditions_fired=details, effects=outcomes, fallback_used=fallback_used,
            checkpoint={
                "next_index": step_index + 1,
                "step_index": step_index, "step_alias": step_alias,
                # The accumulated chain state, verbatim — the half of the checkpoint that
                # lives only in this function's locals and would otherwise die with the tick.
                "context": context, "verdicts": verdicts,
                # The frontier's completed set, for a parallel resume. Empty on an ordered
                # run, which reads `next_index` instead.
                "done_aliases": done_snapshot,
                "scheduling": "parallel" if scheduling_parallel else "ordered",
                # Only the REAL ones. A subchain step waits without staging anything, so an
                # unfiltered list would carry an empty string standing for a proposal that
                # does not exist — and the next reader would have to know that.
                "proposal_ids": [pid for pid in
                                 (str((o.data or {}).get("proposal_id") or "") for o in waiting)
                                 if pid],
                # DS-9 — the nested runs this one is parked behind. A subchain step parks
                # its parent without staging a proposal of its own: the human is being
                # asked by the CHILD, and the parent is waiting for the child, not for the
                # person. Two different things to wait on, so two lists.
                "child_runs": [str((o.data or {}).get("child_run_id") or "")
                               for o in waiting if (o.data or {}).get("child_run_id")],
                "outcome_counts": [[n, c] for n, c in sorted(step_counts.items())],
            }), finished=False)

    return _finish(AutomationRun(**base, outcome="fired", reason=reason,
                                 conditions_fired=details, effects=outcomes,
                                 fallback_used=fallback_used))


def run_automation(
    automation: Automation,
    *,
    now: Optional[datetime] = None,
    probe: Optional[ConditionProbe] = None,
    dispatch: Optional[Dispatch] = None,
    sleeper: Optional[Callable[[float], None]] = None,
    rng: Optional[Callable[[], float]] = None,
    persist: bool = True,
    dry_run: bool = False,
    manual: bool = False,
    run_id: Optional[str] = None,
    until_alias: Optional[str] = None,
    resume: Optional[dict] = None,
) -> AutomationRun:
    """Run one automation. The public door; :func:`_walk_automation` is the chain itself.

    All this adds is the NESTED-CHAIN context (DS-9): the trace a run writes under, how deep
    it already is, and the dispatcher and clocks a child should inherit. It lives out here
    rather than inside the walk for one reason — the walk returns from six places, and a
    context that must be released on every one of them is a context that leaks from the
    seventh. One ``try/finally`` around the whole thing cannot.

    The run id is minted HERE so the context can name the trace before the walk begins;
    everything else is passed through untouched. ``sleeper`` and ``rng`` default to ``None``
    rather than to the real clock so an unset one can INHERIT from the invoking chain — a
    child that reached for `time.sleep` while its parent was running under a test's stub
    would put a real retry backoff inside a unit test.
    """
    parent = _CHAIN.get()
    run_id = run_id or str(_uuid.uuid4())
    dispatch = dispatch or parent.dispatch
    sleeper = sleeper or parent.sleeper or _time.sleep
    rng = rng or parent.rng or random.random
    token = _CHAIN.set(_ChainContext(
        # A top-level run's trace IS its run id (VA-4d); a nested one keeps its parent's.
        trace_id=parent.trace_id or run_id,
        depth=parent.depth, dispatch=dispatch, sleeper=sleeper, rng=rng))
    try:
        return _walk_automation(
            automation, now=now, probe=probe, dispatch=dispatch, sleeper=sleeper, rng=rng,
            persist=persist, dry_run=dry_run, manual=manual, run_id=run_id,
            until_alias=until_alias, resume=resume)
    finally:
        _CHAIN.reset(token)


# ── DS-8 · the other half of the pause ────────────────────────────────────────
#
# A durable pause is only half a feature: parking is easy, and a run that parks and never
# comes back is strictly worse than one that never paused, because it holds a governed
# write hostage with no way to release it. This is the release.

#: What a resolved proposal does to the step that was waiting on it. Rejected and expired
#: both land on ``skipped`` — the engine's own definition of that status is "did not run,
#: and that is not a failure of this step", which is exactly what a human declining a write
#: is. Recording a refusal as ``failed`` would page whoever watches failures to tell them a
#: person did their job.
_PROPOSAL_TO_STATUS = {
    "executed": "executed", "accepted": "executed",
    "rejected": "skipped", "expired": "skipped",
    "failed": "failed", "criterion_failed": "criterion_failed",
    "invalid_params": "invalid_params", "dispatch_error": "dispatch_error",
    # DS-11's completion — a write a human approved whose transport then broke MAY have
    # arrived. Letting it fall through to the `failed` default would license the retry
    # that turns one approved post into two, which is the whole reason this status exists.
    "uncertain": "uncertain",
}


def _slice_prior(effects: list[EffectOutcome], counts: list) -> dict[int, list[EffectOutcome]]:
    """Re-attribute a parked run's flat ``effects`` list to the steps that produced it.

    The list is assembled in declared order, and each step contributed a known number of
    outcomes (one, N for a fan-out, none if it never ran), so the counts recorded on the
    checkpoint slice it back apart exactly. Position alone could not: a fanned step and
    three ordinary ones are both "four outcomes"."""
    out: dict[int, list[EffectOutcome]] = {}
    at = 0
    for pair in counts or []:
        # Checked rather than caught: this reads a JSON blob off a row that a previous
        # release wrote, so a malformed entry is a real possibility — and swallowing it
        # silently would drop a step's outcomes from the reassembled run without saying so.
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            logger.warning("run checkpoint: skipping malformed outcome count %r", pair)
            continue
        n, c = pair
        if not isinstance(n, int) or not isinstance(c, int) or c < 0:
            logger.warning("run checkpoint: skipping non-integer outcome count %r", pair)
            continue
        out[n] = effects[at:at + c]
        at += c
    return out


#: How long a just-accepted proposal is treated as still executing rather than as finished.
#: BOUNDED on purpose: the same shape — `accepted` with nothing recorded — is also what a
#: process that died mid-write leaves behind, and holding on that forever would strand a run
#: in `paused`, which is the one state this wave must never produce. Generous against a
#: provider call and its retries, and short against a human's next look at the queue.
ACCEPT_SETTLE_SECONDS = 120.0


def _settling(proposal) -> bool:
    """Is this proposal's write still in flight — resolved, but not yet reported?

    Reads through `age_hours`, which returns a large sentinel for an unparseable value, so a
    corrupt timestamp reads as OLD and the run proceeds. That is the safe direction here and
    the opposite of the expiry check's: withholding a resume withholds the completion of work
    a human already authorised, where withholding an accept withholds a write.
    """
    from aughor.util.time import age_hours
    return (getattr(proposal, "status", "") == "accepted"
            and not getattr(proposal, "outcome", None)
            and not getattr(proposal, "status_message", "")
            and age_hours(getattr(proposal, "resolved_at", "") or "") * 3600.0
            < ACCEPT_SETTLE_SECONDS)


def resume_run(run_id: str, *, dispatch: Optional[Dispatch] = None,
               sleeper: Callable[[float], None] = _time.sleep,
               rng: Callable[[], float] = random.random) -> Optional[AutomationRun]:
    """Continue a run that parked on an approval, in the SAME run row. Returns the finished
    run, or ``None`` when this run is not resumable yet (or at all).

    Called on every resolution of an automation-sourced proposal — accept, reject and expiry
    alike — because all three END the wait, and only the wait is what the run was blocked on.
    A rejected write does not abort the chain: it makes its step ``skipped``, which is a state
    the engine has always had and every downstream step already handles (a step binding to a
    skipped step's output resolves nothing and skips in turn, exactly as under a W1 guard).
    Aborting instead would be a second, weaker semantics for the same shape.

    **Nothing here re-runs a prior step.** The parked step's outcome is rewritten from the
    proposal the human actually resolved — the inbox's accept already performed the write,
    with ``approved=True``, through the one governed executor — and every step before it is
    replayed into position from the run row. The chain restarts at ``next_index`` with the
    checkpoint's context, so the only dispatches this makes are the ones that never happened.

    ``dispatch`` is the same injection seam ``run_automation`` has always had, and the resume
    needs it for the same reason the first half did: the second half of a chain dispatches
    real sends, and a test that could not substitute for them could only prove the parking.
    Production wakes (``_wake_parked_run``) pass nothing and get the real dispatcher.

    Idempotent under a race by construction: two accepts landing together both call this, and
    ``update_run``'s ``WHERE outcome = 'paused'`` lets exactly one of them move the row. The
    loser's dispatches are the concern, not its write — so the *pending* check below is what
    actually protects the second caller, and the UPDATE guard is the backstop underneath it.
    """
    from aughor.actions.inbox import proposals_for_run
    from aughor.automations.store import get_automation, get_run

    run = get_run(run_id)
    if run is None or run.outcome != "paused":
        return None

    proposals = proposals_for_run(run_id)
    # Still waiting on a person. A chain can park on more than one write in the same round
    # (two parallel steps, or one fanned step over three channels); resuming after the first
    # answer would run the rest of the chain while a second governed write is still pending.
    if any(p.status == "pending" and not p.expired for p in proposals):
        return None
    # …or on a write a person has ALREADY authorised and which is happening right now.
    #
    # Found by a live run, and the green suite had agreed with it. `accept_proposal` resolves
    # the row to `accepted`, THEN performs the write, THEN records its outcome — three
    # statements with a real network call in the middle. The router's own resume runs after
    # all three, but the heartbeat's sweep visits every parked run once a minute and does not:
    # landing inside that window it saw `accepted`, mapped it to `executed` (which it is) and
    # rewrote the step with an EMPTY outcome. The chain then continued, and every later step
    # binding to the approved write's output resolved nothing — a governed write that
    # happened, reported as one that produced nothing, which is precisely the failure the
    # pause exists to prevent, one layer in.
    if any(_settling(p) for p in proposals):
        return None
    # DS-9 — and on any nested run this one parked behind. A subchain step parks its parent
    # WITHOUT a proposal of its own: the human is being asked by the child, and the parent is
    # waiting for the child. Resuming on the proposals alone would restart a parent whose
    # nested chain is still stopped in the middle.
    for child_id in ((run.checkpoint or {}).get("child_runs") or []):
        child = get_run(str(child_id))
        if child is not None and child.outcome == "paused":
            return None
    # Keyed by proposal id ONLY. A `call_id` lookup would look like a sensible fallback and
    # could never fire: `call_id` is the step LABEL, while `outcome.target` is whatever the
    # dispatcher named — the ACTION ID for a governed write. The id is on the outcome whenever
    # staging succeeded, and when it did not there is no proposal to find by any key.
    by_id = {p.id: p for p in proposals}

    cp = run.checkpoint or {}
    automation = get_automation(run.automation_id)
    if automation is None:
        # Deleted while parked. The run cannot continue — but it must not stay `paused`
        # forever either, because `paused` is a claim that someone can still act on it.
        return update_run(run.model_copy(update={
            "outcome": "error", "finished_at": now_iso_z(),
            "reason": "automation was deleted while this run waited for approval",
            "error": "automation not found", "checkpoint": {}}))

    # 1 — rewrite the parked steps from what the human (or the clock) decided.
    rewritten: list[EffectOutcome] = []
    for o in run.effects:
        if o.status != "approval_required":
            rewritten.append(o)
            continue
        # DS-9 — a subchain step waits on a RUN, not on a proposal, so it is resolved from
        # the child's final outcome through the very same mapping the live dispatch used.
        child_run_id = str((o.data or {}).get("child_run_id") or "")
        if child_run_id:
            child_run = get_run(child_run_id)
            if child_run is None:
                rewritten.append(o.model_copy(update={
                    "status": "skipped",
                    "message": f"{o.message} — the nested run is no longer on record"}))
            else:
                rewritten.append(subchain_outcome(
                    o.kind, o.target, child_run.automation_name or o.target, child_run))
            continue
        p = by_id.get(str((o.data or {}).get("proposal_id") or ""))
        if p is None:
            # Staging failed at park time (best-effort, by design) or the row was purged.
            # The write never got a human, so it did not happen: `skipped`, said plainly.
            rewritten.append(o.model_copy(update={
                "status": "skipped",
                "message": f"{o.message} — no proposal was staged for this step, so it "
                           f"was never presented for approval"}))
            continue
        status = _PROPOSAL_TO_STATUS.get(p.status, "failed")
        rewritten.append(o.model_copy(update={
            "status": status,
            "message": p.status_message or p.status,
            "data": dict(p.outcome or {}) if status == "executed" else dict(o.data or {}),
        }))

    counts = cp.get("outcome_counts") or []
    prior_by_index = _slice_prior(rewritten, counts)
    # The ORIGINAL slices too, because "was this step waiting on a human" has to be asked of
    # the run as it parked. The rewrite above replaces a resolved step's `data` with the
    # executor's result, which drops the `proposal_id` that marked it — so asking the
    # rewritten copy answers no for every step, including the one that just resumed.
    orig_by_index = _slice_prior(list(run.effects), counts)

    # 2 — publish the resolved step into the context the rest of the chain reads.
    #
    # Keyed by the step's ALIAS, taken from its position — never from `outcome.target`. A
    # dispatcher sets `target` to whatever names the thing it dispatched, and for a governed
    # write that is the ACTION ID: the step aliased `flag` records a target of
    # `flag_order_for_review`. Publishing under the target put the approved step's result
    # beyond the reach of `{"$from": "flag.id"}`, and the step waiting on it skipped with
    # "upstream data unavailable" — a chain that had just been approved, reported as a chain
    # missing its input. Found by running it, not by a test: the fixture dispatcher set
    # `target` to the alias, so every assertion agreed with the bug.
    #
    # A fanned step publishes its COUNT and nothing else, exactly as `_execute_step` does:
    # there are N per-item values and a `{"$from": "step2.ts"}` could only mean one of them.
    context = dict(cp.get("context") or {})
    for n, outs in prior_by_index.items():
        if not (0 <= n < len(automation.effects)):
            continue
        # Only the steps that were WAITING get republished. Every other step's context entry
        # came back with the checkpoint exactly as it published it, and rewriting one here
        # from its recorded outcome would let this function's idea of "what a step publishes"
        # drift from `_execute_step`'s, which is the one that has to stay authoritative.
        if not any(o.status == "approval_required" for o in (orig_by_index.get(n) or [])):
            continue
        executed = [o for o in outs if o.status == "executed"]
        if not executed:
            continue
        alias = alias_for(automation.effects[n], n)
        context[alias] = ({"count": len(executed)} if outs[0].fan_count
                          else dict(executed[-1].data or {}))
    step_alias = str(cp.get("step_alias") or "")
    cp = {**cp, "context": context}

    logger.info("automation %s resuming run %s at step '%s'",
                automation.id, run_id, step_alias)
    finished = run_automation(
        automation, run_id=run_id, persist=True,
        dispatch=dispatch, sleeper=sleeper, rng=rng,
        resume={
            "checkpoint": cp,
            "prior_by_index": prior_by_index,
            "conditions_fired": list(run.conditions_fired),
            "reason": run.reason,
            "prior_duration_ms": run.duration_ms,
        },
    )
    # DS-9 — and now whatever was parked behind THIS run. A parent waiting on a nested chain
    # has no proposal of its own, so nothing else would ever wake it on the resolving click;
    # it would sit until the heartbeat swept it up. Recursion is bounded by nesting depth
    # (`MAX_SUBCHAIN_DEPTH`), and cycles are refused at save.
    if finished is not None and finished.outcome != "paused":
        _wake_parents(run_id, dispatch=dispatch, sleeper=sleeper, rng=rng)
    return finished


def _wake_parents(child_run_id: str, *, dispatch: Optional[Dispatch] = None,
                  sleeper: Callable[[float], None] = _time.sleep,
                  rng: Callable[[], float] = random.random) -> None:
    """Resume every run parked behind ``child_run_id`` (DS-9). Best-effort, like every other
    wake: the child's own work is already committed, and a parent that fails to wake stays
    `paused` for the heartbeat's sweep to find."""
    from aughor.automations.store import paused_runs

    for parent in paused_runs(limit=200):
        if child_run_id in ((parent.checkpoint or {}).get("child_runs") or []):
            try:
                resume_run(parent.id, dispatch=dispatch, sleeper=sleeper, rng=rng)
            except Exception:
                logger.warning("automation %s: resuming parent run %s failed",
                               parent.automation_id, parent.id, exc_info=True)


def resume_parked_runs(conn_id: Optional[str] = None, limit: int = 100) -> int:
    """Resume every parked run whose approvals have all been answered. Returns how many moved.

    The completeness net under DS-8, and the reason the pause is safe to rely on. The routers
    that resolve a proposal call :func:`resume_run` directly, so the common path is immediate
    — but "the surface that resolved it remembered to wake the run" is a promise that gets
    broken by the ordinary things: a process that dies between the resolve and the resume, a
    proposal that lapses with nobody clicking anything, a new resolution surface added later
    by someone who has never read this module.

    A run left `paused` by any of those is the worst state this wave can produce: a chain
    holding a governed write a human already approved, with nothing scheduled to finish it.
    So the heartbeat that already visits every automation once a minute checks for them too.
    That makes the router calls an optimisation rather than the mechanism — which is the only
    arrangement in which "it resumed" is a property of the system rather than of a code path.

    One run's failure never stops the rest, exactly as in `tick_once`: a chain whose second
    half cannot dispatch must not hold up a different chain's approved write.
    """
    from aughor.automations.store import paused_runs

    moved = 0
    # DS-9 — passes, not one walk. Finishing a nested chain can make its PARENT resumable,
    # and the parent may already have been visited (and correctly skipped) earlier in the
    # same list. One pass per level of nesting resolves a whole tower on the tick that
    # unblocked its leaf; the cap is the nesting cap, so this cannot spin.
    for _ in range(MAX_SUBCHAIN_DEPTH + 1):
        this_pass = 0
        for run in paused_runs(conn_id=conn_id, limit=limit):
            try:
                if resume_run(run.id) is not None:
                    this_pass += 1
            except Exception:
                logger.warning("automation %s: resuming parked run %s failed",
                               run.automation_id, run.id, exc_info=True)
        moved += this_pass
        if not this_pass:
            break
    return moved
