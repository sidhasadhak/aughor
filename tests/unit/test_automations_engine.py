"""Wave A2 — the one condition→effect engine.

Locks the gate contract: enabled → not expired → not paused → conditions → effects → jittered
retry → fallback → record. Two properties carry most of the weight:

* **The lifecycle gates run BEFORE any condition is evaluated**, so a muted automation never
  reaches the warehouse. Asserted by counting probe calls, not by reading the code.
* **No effect fires on a gated or condition-negative tick**, and a criterion failure comes back
  with the AUTHORED message verbatim — the Wave-K property, inherited rather than re-implemented.

Hermetic: both seams (probe, dispatch) are injected; the kinetic test fakes the ontology load so
the real :func:`~aughor.kinetic.executor.execute_kinetic_action` runs unmocked.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aughor.automations.engine import (
    ProbeUnavailable,
    evaluate_conditions,
    run_automation,
)
from aughor.automations.models import Automation, Condition, Effect, EffectOutcome
from aughor.automations.store import get_runs, upsert_automation

NOW = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)


def _automation(**kw) -> Automation:
    base = dict(
        conn_id="conn-eng", name="A",
        conditions=[Condition(kind="metric", config={"monitor_id": "m1"})],
        effects=[Effect(kind="notify", config={"trigger_id": "t1"})],
        max_retries=0, retry_backoff_seconds=0.0,
    )
    base.update(kw)
    return Automation(**base)


def _probe(fires=True, *, calls=None):
    def probe(cond, automation):
        if calls is not None:
            calls.append(cond.kind)
        return fires, f"{cond.kind}: {'fired' if fires else 'quiet'}"
    return probe


def _dispatch(status="executed", *, calls=None, message=""):
    def dispatch(effect, automation):
        if calls is not None:
            calls.append(effect.kind)
        return EffectOutcome(kind=effect.kind, target=effect.target(),
                             status=status, message=message)
    return dispatch


# ── the lifecycle gates run first, and cost nothing ──────────────────────────────

@pytest.mark.parametrize("kw,expected", [
    ({"enabled": False}, "disabled"),
    ({"expires_at": "2026-07-01T00:00:00Z"}, "expired"),
    ({"paused_until": "2026-08-01T00:00:00Z"}, "muted"),
])
def test_gated_automation_never_probes_and_never_dispatches(kw, expected):
    """The A2 decision gate. A gated tick must not reach the warehouse OR fire an effect —
    and must still explain itself in the run history."""
    probe_calls, dispatch_calls = [], []
    run = run_automation(_automation(**kw), now=NOW,
                         probe=_probe(True, calls=probe_calls),
                         dispatch=_dispatch(calls=dispatch_calls), persist=False)
    assert run.outcome == "gated"
    assert expected in run.reason
    assert probe_calls == [], "a gated automation evaluated a condition — the gate order is wrong"
    assert dispatch_calls == [], "a gated automation fired an effect"


def test_an_expired_pause_no_longer_gates():
    run = run_automation(_automation(paused_until="2026-07-23T11:00:00Z"), now=NOW,
                         probe=_probe(True), dispatch=_dispatch(), persist=False)
    assert run.outcome == "fired"


def test_expiry_at_exactly_now_is_expired():
    run = run_automation(_automation(expires_at=NOW.isoformat().replace("+00:00", "Z")),
                         now=NOW, probe=_probe(True), dispatch=_dispatch(), persist=False)
    assert run.outcome == "gated"


# ── conditions ───────────────────────────────────────────────────────────────────

def test_condition_logic_all_requires_every_condition():
    a = _automation(conditions=[
        Condition(kind="metric", config={"monitor_id": "m1"}),
        Condition(kind="source_change", config={"table": "orders"}),
    ], condition_logic="all")

    def mixed(cond, automation):
        return cond.kind == "metric", f"{cond.kind}"

    dispatch_calls = []
    run = run_automation(a, now=NOW, probe=mixed,
                         dispatch=_dispatch(calls=dispatch_calls), persist=False)
    assert run.outcome == "not_fired"
    assert dispatch_calls == []


def test_condition_logic_any_fires_on_one():
    a = _automation(conditions=[
        Condition(kind="metric", config={"monitor_id": "m1"}),
        Condition(kind="source_change", config={"table": "orders"}),
    ], condition_logic="any")

    def mixed(cond, automation):
        return cond.kind == "metric", f"{cond.kind}"

    run = run_automation(a, now=NOW, probe=mixed, dispatch=_dispatch(), persist=False)
    assert run.outcome == "fired"
    assert run.conditions_fired == ["metric"]


def test_every_condition_is_evaluated_even_when_one_already_decided_it():
    """No short-circuit: the run history is meant to explain the tick, and 'we stopped looking
    after the first false' makes a two-condition automation unanswerable."""
    calls = []
    a = _automation(conditions=[
        Condition(kind="metric", config={"monitor_id": "m1"}),
        Condition(kind="source_change", config={"table": "orders"}),
    ], condition_logic="all")
    run_automation(a, now=NOW, probe=_probe(False, calls=calls),
                   dispatch=_dispatch(), persist=False)
    assert calls == ["metric", "source_change"]


def test_an_unevaluable_condition_is_an_error_not_a_quiet_no_fire():
    """A probe that cannot answer must be loud. Reporting 'did not fire' would make a broken
    automation indistinguishable from a calm one."""
    def broken(cond, automation):
        raise ProbeUnavailable("no probe for source_change yet")

    a = _automation(conditions=[Condition(kind="source_change", config={"table": "orders"})])
    dispatch_calls = []
    run = run_automation(a, now=NOW, probe=broken,
                         dispatch=_dispatch(calls=dispatch_calls), persist=False)
    assert run.outcome == "error"
    assert "ProbeUnavailable" in run.error
    assert dispatch_calls == []


def test_schedule_condition_fires_once_then_waits_for_the_next_cron_match():
    """Evaluated in-engine against the LAST RUN, not against 'is it the cron minute now' — so a
    late tick still fires exactly once, and an immediate re-tick does not."""
    a = upsert_automation(_automation(
        conn_id="conn-sched",
        conditions=[Condition(kind="schedule", config={"cron": "0 8 * * *"})]))

    first = run_automation(a, now=NOW, dispatch=_dispatch())
    assert first.outcome == "fired" and "first run" in first.reason

    second = run_automation(a, now=NOW + timedelta(minutes=1), dispatch=_dispatch())
    assert second.outcome == "not_fired"

    # Past the next 08:00 → due again.
    third = run_automation(a, now=NOW + timedelta(days=1), dispatch=_dispatch())
    assert third.outcome == "fired"


def test_evaluate_conditions_reports_the_quiet_ones_as_the_reason():
    a = _automation()
    fired, details, reason = evaluate_conditions(a, now=NOW, probe=_probe(False))
    assert fired is False and details == []
    assert "quiet" in reason


# ── effects, retries, fallback ───────────────────────────────────────────────────

def test_effects_dispatch_in_declared_order():
    calls = []
    a = _automation(effects=[
        Effect(kind="notify", config={"trigger_id": "t1"}),
        Effect(kind="brief", config={"subscription_id": "s1"}),
        Effect(kind="investigate", config={"question": "why?"}),
    ])
    run = run_automation(a, now=NOW, probe=_probe(True),
                         dispatch=_dispatch(calls=calls), persist=False)
    assert calls == ["notify", "brief", "investigate"]
    assert [e.kind for e in run.effects] == ["notify", "brief", "investigate"]


@pytest.mark.parametrize("status", [
    "criterion_failed", "approval_required", "invalid_params", "dispatch_error",
])
def test_a_verdict_is_not_retried(status):
    """A criterion failure, an approval requirement or a structural dispatch error is a VERDICT,
    not a fault: the inputs are identical next attempt, so a retry is pure waste against whatever
    refused it. ``dispatch_error`` is on this list because the first live run spent 48 seconds of
    a held scheduler thread retrying an action id the connection does not declare."""
    attempts = []

    def dispatch(effect, automation):
        attempts.append(1)
        return EffectOutcome(kind=effect.kind, status=status, message="nope")

    run = run_automation(_automation(max_retries=3), now=NOW,
                         probe=_probe(True), dispatch=dispatch,
                         sleeper=lambda s: None, rng=lambda: 0.0, persist=False)
    assert len(attempts) == 1
    assert run.effects[0].attempts == 1


def test_a_transient_failure_is_retried_up_to_max_retries():
    attempts = []

    def dispatch(effect, automation):
        attempts.append(1)
        return EffectOutcome(kind=effect.kind, status="failed", message="boom")

    run = run_automation(_automation(max_retries=2, retry_backoff_seconds=1.0), now=NOW,
                         probe=_probe(True), dispatch=dispatch,
                         sleeper=lambda s: None, rng=lambda: 0.0, persist=False)
    assert len(attempts) == 3          # first attempt + 2 retries
    assert run.effects[0].attempts == 3


def test_a_raising_dispatcher_becomes_a_failed_outcome_not_a_crashed_tick():
    def dispatch(effect, automation):
        raise RuntimeError("webhook exploded")

    run = run_automation(_automation(), now=NOW, probe=_probe(True), dispatch=dispatch,
                         sleeper=lambda s: None, rng=lambda: 0.0, persist=False)
    assert run.outcome == "fired"
    assert run.effects[0].status == "failed"
    assert "webhook exploded" in run.effects[0].message


def test_retry_backoff_is_jittered():
    """N automations failing together must not retry in lockstep, so the configured backoff is
    scaled by a random factor rather than used verbatim."""
    slept: list[float] = []
    run_automation(_automation(max_retries=2, retry_backoff_seconds=10.0), now=NOW,
                   probe=_probe(True), dispatch=_dispatch(status="failed"),
                   sleeper=slept.append, rng=lambda: 0.5, persist=False)
    assert slept == [pytest.approx(15.0), pytest.approx(15.0)]   # 10 * (1 + 0.5)


def test_retry_sleep_is_bounded_however_it_is_configured():
    """One tick holds a scheduler thread while it waits, so the retry budget is capped
    regardless of what an operator sets per automation."""
    slept: list[float] = []
    run_automation(_automation(max_retries=5, retry_backoff_seconds=1000.0), now=NOW,
                   probe=_probe(True), dispatch=_dispatch(status="failed"),
                   sleeper=slept.append, rng=lambda: 0.5, persist=False)
    assert sum(slept) <= 120.0 + 1e-6


def test_fallback_runs_only_when_every_effect_failed():
    calls = []
    a = _automation(
        effects=[Effect(kind="notify", config={"trigger_id": "t1"})],
        fallback_effect=Effect(kind="notify", config={"trigger_id": "oncall"}),
    )
    run = run_automation(a, now=NOW, probe=_probe(True),
                         dispatch=_dispatch(status="failed", calls=calls),
                         sleeper=lambda s: None, rng=lambda: 0.0, persist=False)
    assert run.fallback_used is True
    assert len(calls) == 2

    calls.clear()
    ok = run_automation(a, now=NOW, probe=_probe(True),
                        dispatch=_dispatch(status="executed", calls=calls), persist=False)
    assert ok.fallback_used is False
    assert len(calls) == 1


def test_fallback_is_skipped_when_any_effect_executed():
    a = _automation(
        effects=[Effect(kind="notify", config={"trigger_id": "t1"}),
                 Effect(kind="brief", config={"subscription_id": "s1"})],
        fallback_effect=Effect(kind="notify", config={"trigger_id": "oncall"}),
    )

    def half(effect, automation):
        status = "executed" if effect.kind == "notify" else "failed"
        return EffectOutcome(kind=effect.kind, status=status)

    run = run_automation(a, now=NOW, probe=_probe(True), dispatch=half,
                         sleeper=lambda s: None, rng=lambda: 0.0, persist=False)
    assert run.fallback_used is False


# ── persistence ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("kw,probe_fires,expected", [
    ({"enabled": False}, True, "gated"),
    ({}, False, "not_fired"),
    ({}, True, "fired"),
])
def test_every_tick_persists_exactly_one_run(kw, probe_fires, expected):
    a = upsert_automation(_automation(conn_id=f"conn-persist-{expected}", **kw))
    run_automation(a, now=NOW, probe=_probe(probe_fires), dispatch=_dispatch())
    runs = get_runs(automation_id=a.id)
    assert len(runs) == 1
    assert runs[0].outcome == expected
    assert runs[0].duration_ms >= 0


# ── the Wave-K joint: a write effect goes through the governed executor ──────────

def _graph_with(action):
    class _G:
        kinetic_actions = {action.id: action}
    return _G()


def _refund_action(**kw):
    from aughor.ontology.models import ActionParameter, KineticAction, SubmissionCriterion
    base = dict(
        id="refund", kind="side_effect",
        params=[ActionParameter(name="amount", data_type="NUMERIC", required=True)],
        submission_criteria=[SubmissionCriterion(
            expr="amount <= 10000",
            message="Refunds over €10,000 need finance sign-off — route to approvals instead.")],
        side_effects=[],
        risk="low",
    )
    base.update(kw)
    return KineticAction(**base)


def test_kinetic_effect_criterion_failure_returns_the_authored_message_verbatim(monkeypatch):
    """The A↔K joint. The real executor runs; its authored message must reach the run history
    unparaphrased, and NOTHING may dispatch."""
    action = _refund_action()
    monkeypatch.setattr("aughor.ontology.store.load_latest_ontology",
                        lambda conn_id, schema=None: _graph_with(action))
    dispatched = []
    monkeypatch.setattr("aughor.kinetic.executor.default_dispatch",
                        lambda a, p, s="": dispatched.append(a.id))

    a = _automation(effects=[Effect(kind="kinetic_action",
                                    config={"action_id": "refund",
                                            "params": {"amount": 25000}})])
    run = run_automation(a, now=NOW, probe=_probe(True), persist=False)

    assert run.effects[0].status == "criterion_failed"
    assert run.effects[0].message == \
        "Refunds over €10,000 need finance sign-off — route to approvals instead."
    assert dispatched == [], "a criterion-failed action dispatched a side effect"


def test_kinetic_effect_executes_when_the_criteria_hold(monkeypatch):
    action = _refund_action()
    monkeypatch.setattr("aughor.ontology.store.load_latest_ontology",
                        lambda conn_id, schema=None: _graph_with(action))
    seen = []

    def fake_dispatch(act, params, scope=""):
        seen.append((act.id, params, scope))
        return {"ok": True}

    monkeypatch.setattr("aughor.kinetic.executor.default_dispatch", fake_dispatch)

    a = _automation(conn_id="conn-kin",
                    effects=[Effect(kind="kinetic_action",
                                    config={"action_id": "refund",
                                            "params": {"amount": 500}})])
    run = run_automation(a, now=NOW, probe=_probe(True), persist=False)

    assert run.effects[0].status == "executed"
    # The coerced params and the connection scope reach the executor unchanged.
    assert seen == [("refund", {"amount": 500.0}, "conn-kin")]


def test_kinetic_effect_naming_an_undeclared_action_is_a_terminal_dispatch_error(monkeypatch):
    """An unknown action id will never become known by waiting — so it must not consume the
    retry budget (the live run burned 48s of a scheduler thread doing exactly that)."""
    slept: list[float] = []
    monkeypatch.setattr("aughor.ontology.store.load_latest_ontology",
                        lambda conn_id, schema=None: _graph_with(_refund_action()))
    a = _automation(max_retries=3, retry_backoff_seconds=30.0,
                    effects=[Effect(kind="kinetic_action", config={"action_id": "ghost"})])
    run = run_automation(a, now=NOW, probe=_probe(True),
                         sleeper=slept.append, rng=lambda: 0.0, persist=False)
    assert run.effects[0].status == "dispatch_error"
    assert "not a declared action" in run.effects[0].message
    assert run.effects[0].attempts == 1
    assert slept == []


def test_a_missing_schema_ontology_says_so_instead_of_blaming_the_declaration(monkeypatch):
    """The live-run diagnosis trap: a schema that was never built falls back to another schema's
    graph, and 'not a declared action' points the reader at the wrong thing."""
    def fake_load(conn_id, schema=None):
        if schema == "default":
            return None                       # never built
        g = _graph_with(_refund_action())
        g.schema_name = "main"
        return g

    monkeypatch.setattr("aughor.ontology.store.load_latest_ontology", fake_load)
    a = _automation(effects=[Effect(kind="kinetic_action",
                                    config={"action_id": "other", "schema_name": "default"})])
    run = run_automation(a, now=NOW, probe=_probe(True), persist=False)
    assert run.effects[0].status == "dispatch_error"
    assert "has no cached ontology" in run.effects[0].message
    assert "default" in run.effects[0].message and "main" in run.effects[0].message
