"""VA-6 — the alert plane, wired.

`aughor/obs/agent_alerts.py` shipped complete and inert: metrics, rules, verdicts, and one
importer in the whole repo — its own test. Nothing stored a rule, nothing evaluated one, and
nothing could deliver the result, so an agent could fail sixty times an hour in silence with a
green suite. This file is deliberately weighted towards the SEAMS rather than the arithmetic,
because the arithmetic was never the part that was missing.

The load-bearing test is `test_an_enabled_rule_reaches_the_one_loop`. A rule that is stored,
evaluable and deliverable is still inert unless the heartbeat can see it, and "can the
heartbeat see it" is exactly the question a unit test of `evaluate()` cannot ask.

The roadmap's receipt — three failures in a window produce ONE alert, not three — is
`test_three_failures_in_a_window_page_once`.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aughor.kernel.ledger import Ledger
from aughor.obs import agent_alert_store as store
from aughor.obs.agent_alert_runner import run_rule
from aughor.obs.agent_alerts import AgentAlertRule


@pytest.fixture(autouse=True)
def _clean_rules():
    """Each test starts with an empty plane — the store is a module-level singleton."""
    for r in store.list_rules():
        store.delete_rule(r.id)
    yield
    for r in store.list_rules():
        store.delete_rule(r.id)


def _rule(**kw) -> AgentAlertRule:
    base = dict(name="agent errors", metric="failed_runs", comparator="gte",
                threshold=3, window_minutes=60, debounce_minutes=30)
    base.update(kw)
    return store.upsert_rule(AgentAlertRule(**base))


def _insert_jobs(states: list[str], *, kind: str = "exploration",
                 at: datetime | None = None) -> None:
    at = at or datetime.now(timezone.utc)
    led = Ledger.default()
    for i, state in enumerate(states):
        iso = (at - timedelta(seconds=i)).isoformat()
        led.job_insert({"id": f"j-{state}-{i}-{iso}", "kind": kind, "conn_id": "c1",
                        "canvas_id": None, "state": state, "payload": None,
                        "idempotency_key": None, "attempt": 1, "created_at": iso,
                        "started_at": iso, "heartbeat_at": iso})


# ── the seam that makes the plane live ────────────────────────────────────────────

def test_an_enabled_rule_reaches_the_one_loop():
    """The whole wave in one assertion: the heartbeat can SEE the rule.

    Everything else here could pass with the plane still inert — this is the wire."""
    from aughor.automations.adopt import AGENT_ALERT_PREFIX, list_adopted_automations

    rule = _rule(name="reachable")

    adopted = {a.id: a for a in list_adopted_automations()}

    assert f"{AGENT_ALERT_PREFIX}{rule.id}" in adopted, \
        "an enabled rule must be adopted as a virtual automation, or nothing ever ticks it"
    auto = adopted[f"{AGENT_ALERT_PREFIX}{rule.id}"]
    assert [c.kind for c in auto.conditions] == ["schedule"]
    assert [(e.kind, e.config.get("rule_id")) for e in auto.effects] == \
        [("agent_alert", rule.id)]
    assert auto.max_retries == 0, "the next cron fire is the only retry an alert should get"


def test_a_disabled_rule_is_not_adopted():
    from aughor.automations.adopt import AGENT_ALERT_PREFIX, list_adopted_automations

    rule = _rule(name="off", enabled=False)

    assert f"{AGENT_ALERT_PREFIX}{rule.id}" not in {a.id for a in list_adopted_automations()}


def test_the_tick_counts_agent_alerts_as_their_own_family():
    """'40 automations were evaluated' is not an answer to 'is the alert plane running'."""
    from aughor.automations.scheduler import tick_once

    _rule(name="counted")

    counts = tick_once()

    assert counts.get("agent_alerts", 0) >= 1


def test_the_effect_kind_is_claimed_as_outward():
    """Two loops ticking together both read `last_notified_at` before either writes it, so
    the rule's own debounce cannot close that race. The delivery claim is what does."""
    from aughor.automations.engine import OUTWARD_EFFECT_KINDS

    assert "agent_alert" in OUTWARD_EFFECT_KINDS


def test_the_dispatcher_is_registered_for_the_kind():
    from aughor.automations.engine import _DISPATCHERS

    assert "agent_alert" in _DISPATCHERS


# ── the roadmap's receipt ─────────────────────────────────────────────────────────

def test_three_failures_in_a_window_page_once():
    """Force three failures; the alert fires once, not per failure."""
    rule = _rule(name="three strikes", metric="failed_runs", threshold=3, comparator="gte")
    _insert_jobs(["FAILED", "FAILED", "FAILED", "SUCCEEDED"])
    now = datetime.now(timezone.utc)

    first, event = run_rule(rule, now=now)
    again, second_event = run_rule(store.get_rule(rule.id), now=now + timedelta(minutes=1))

    assert first.matched and first.should_notify
    assert event is not None and event.value == 3.0
    assert again.matched, "the condition is still true"
    assert not again.should_notify, "and the quiet period is what stops the second page"
    assert second_event is None
    assert len(store.list_events(rule_id=rule.id)) == 1


def test_the_debounce_clock_is_stamped_on_notify_only():
    rule = _rule(name="clock", metric="failed_runs", threshold=1, comparator="gte")
    _insert_jobs(["FAILED"])
    assert store.get_rule(rule.id).last_notified_at is None

    run_rule(rule, now=datetime.now(timezone.utc))

    assert store.get_rule(rule.id).last_notified_at is not None


def test_a_test_click_cannot_become_a_debounce_free_pager_button():
    """`suppress=False` ignores the quiet period, but a Test click DELIVERS — so it starts
    one. Otherwise Test pages a human as fast as it can be clicked."""
    rule = _rule(name="tested", metric="failed_runs", threshold=1, comparator="gte")
    _insert_jobs(["FAILED"])

    verdict, event = run_rule(rule, suppress=False, now=datetime.now(timezone.utc))

    assert verdict.matched and event is not None
    assert store.get_rule(rule.id).last_notified_at is not None


def test_a_muted_rule_can_still_be_tested():
    """The point of `suppress=False`: show a currently-quiet rule working."""
    rule = _rule(name="muted", metric="failed_runs", threshold=1, comparator="gte")
    _insert_jobs(["FAILED"])
    now = datetime.now(timezone.utc)
    run_rule(rule, now=now)                                   # starts the quiet period

    quiet, no_event = run_rule(store.get_rule(rule.id), now=now + timedelta(minutes=1))
    _tested, event = run_rule(store.get_rule(rule.id), now=now + timedelta(minutes=1),
                              suppress=False)

    assert not quiet.should_notify and no_event is None
    assert event is not None, "Test must show a muted rule working"


def test_a_window_with_no_population_declines_to_fire():
    """Unknown is never zero: no run finished, so there is no error rate to alert on."""
    rule = _rule(name="quiet sunday", metric="error_rate", threshold=0.0, comparator="gte")

    verdict, event = run_rule(rule, now=datetime.now(timezone.utc) - timedelta(days=400))

    assert verdict.value is None and not verdict.matched
    assert event is None
    assert "no population" in verdict.reason


# ── delivery ──────────────────────────────────────────────────────────────────────

def test_an_in_app_rule_records_the_alert_and_says_it_was_not_sent():
    rule = _rule(name="in-app", metric="failed_runs", threshold=1, comparator="gte")
    _insert_jobs(["FAILED"])

    _verdict, event = run_rule(rule, now=datetime.now(timezone.utc))

    assert event is not None and not event.delivered
    assert "in-app" in event.delivery_detail
    assert store.list_events(rule_id=rule.id)[0].delivered is False


def test_a_rule_pointing_at_a_deleted_trigger_still_leaves_the_alert():
    """The event row is the alert. A channel that is gone must not erase the fact."""
    rule = _rule(name="broken channel", metric="failed_runs", threshold=1,
                 comparator="gte", channel="no-such-trigger")
    _insert_jobs(["FAILED"])

    _verdict, event = run_rule(rule, now=datetime.now(timezone.utc))

    assert event is not None and not event.delivered
    assert "unknown trigger" in event.delivery_detail
    assert len(store.list_events(rule_id=rule.id)) == 1


# ── the store ─────────────────────────────────────────────────────────────────────

def test_editing_a_rule_does_not_reset_the_debounce_clock():
    """Raising a threshold is not a reason to re-page someone about a condition they
    have already been told about."""
    rule = _rule(name="edited", metric="failed_runs", threshold=1, comparator="gte")
    _insert_jobs(["FAILED"])
    run_rule(rule, now=datetime.now(timezone.utc))
    stamped = store.get_rule(rule.id).last_notified_at
    assert stamped

    edited = store.upsert_rule(store.get_rule(rule.id).model_copy(
        update={"threshold": 99.0, "last_notified_at": None}))

    assert edited.threshold == 99.0
    assert edited.last_notified_at == stamped


def test_events_carry_the_numbers_that_outlive_the_rule():
    """A rule is editable; an alert is a statement about a moment."""
    rule = _rule(name="frozen", metric="failed_runs", threshold=2, comparator="gte")
    _insert_jobs(["FAILED", "FAILED"])
    verdict, _event = run_rule(rule, now=datetime.now(timezone.utc))

    store.upsert_rule(store.get_rule(rule.id).model_copy(update={"threshold": 500.0}))

    event = store.list_events(rule_id=rule.id)[0]
    assert event.threshold == 2, "the alert keeps the threshold it was judged against"
    assert event.value == verdict.value
    assert event.population >= 2, "an alert that cannot state its denominator is uncheckable"


def test_acknowledging_an_event_takes_it_out_of_the_unacknowledged_feed():
    rule = _rule(name="ackable", metric="failed_runs", threshold=1, comparator="gte")
    _insert_jobs(["FAILED"])
    _verdict, event = run_rule(rule, now=datetime.now(timezone.utc))
    assert event is not None

    store.acknowledge_event(event.id)

    assert store.list_events(rule_id=rule.id, unacknowledged_only=True) == []
    assert store.list_events(rule_id=rule.id)[0].acknowledged is True


# ── the HTTP surface ──────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from aughor.api import app
    return TestClient(app)


def test_the_metric_vocabulary_comes_from_the_code(client):
    """A filter must never advertise a metric nothing can measure — the same rule
    `/activity` follows for event kinds."""
    from typing import get_args

    from aughor.obs.agent_alerts import Metric

    body = client.get("/obs/agent-alerts/metrics").json()

    assert body["metrics"] == list(get_args(Metric))
    assert "error_rate" in body["metrics"]


def test_rule_crud_round_trip(client):
    created = client.post("/obs/agent-alerts/rules", json={
        "name": "api rule", "metric": "error_rate", "comparator": "gt",
        "threshold": 0.25, "window_minutes": 30})
    assert created.status_code == 200, created.text
    rid = created.json()["id"]
    assert rid

    assert rid in {r["id"] for r in client.get("/obs/agent-alerts/rules").json()["rules"]}
    assert client.get(f"/obs/agent-alerts/rules/{rid}").json()["threshold"] == 0.25

    assert client.delete(f"/obs/agent-alerts/rules/{rid}").status_code == 200
    assert client.get(f"/obs/agent-alerts/rules/{rid}").status_code == 404


def test_an_uncronnable_rule_is_refused_at_create(client):
    """Rejected here, not at the first tick — where the failure is a log line nobody reads."""
    bad = client.post("/obs/agent-alerts/rules", json={
        "name": "bad cron", "metric": "failed_runs", "threshold": 1,
        "check_cron": "not a cron"})

    assert bad.status_code == 422
    assert "check_cron" in bad.text


def test_the_test_endpoint_returns_the_verdict_even_when_nothing_fired(client):
    """'It did not fire, and here is the number and the population it saw' is the answer
    somebody debugging a rule actually needs."""
    rid = client.post("/obs/agent-alerts/rules", json={
        "name": "never", "metric": "failed_runs", "comparator": "gte",
        "threshold": 1_000_000}).json()["id"]

    body = client.post(f"/obs/agent-alerts/rules/{rid}/test").json()

    assert body["event"] is None
    assert body["verdict"]["matched"] is False
    assert body["verdict"]["reason"]


def test_events_feed_and_acknowledge(client):
    rule = _rule(name="feed", metric="failed_runs", threshold=1, comparator="gte")
    _insert_jobs(["FAILED"])
    _verdict, event = run_rule(rule, now=datetime.now(timezone.utc))
    assert event is not None

    feed = client.get("/obs/agent-alerts/events", params={"rule_id": rule.id}).json()
    assert [e["id"] for e in feed["events"]] == [event.id]

    acked = client.post(f"/obs/agent-alerts/events/{event.id}/ack")
    assert acked.status_code == 200 and acked.json()["acknowledged"] is True
    assert client.get("/obs/agent-alerts/events",
                      params={"rule_id": rule.id,
                              "unacknowledged_only": True}).json()["events"] == []


# ── Attention ─────────────────────────────────────────────────────────────────────

def test_an_unacknowledged_alert_is_something_that_needs_a_human(client):
    """Attention is a VIEW over its sources, so a fired alert has to arrive there by
    being IN a source — never by the panel keeping a second copy."""
    rule = _rule(name="attention", metric="failed_runs", threshold=1, comparator="gte")
    _insert_jobs(["FAILED"])
    _verdict, event = run_rule(rule, now=datetime.now(timezone.utc))
    assert event is not None

    body = client.get("/control-room/needs-human").json()

    mine = [r for r in body["rows"] if r["id"] == event.id]
    assert len(mine) == 1, "a fired alert must appear in Attention"
    assert mine[0]["source"] == "agent_alert"
    assert mine[0]["severity"] == "warning"
    assert mine[0]["resolve"]["ack"].endswith(f"/{event.id}/ack")
    assert body["sources"]["agent_alerts"] >= 1
    assert body["count"] == sum(body["sources"].values()), \
        "the CR4 gate: count equals the sum of its sources, with the new one included"


def test_acknowledging_removes_the_row_from_attention(client):
    """Resolving through the native surface removes it here — there are no copies."""
    rule = _rule(name="resolvable", metric="failed_runs", threshold=1, comparator="gte")
    _insert_jobs(["FAILED"])
    _verdict, event = run_rule(rule, now=datetime.now(timezone.utc))
    assert event is not None
    before = client.get("/control-room/needs-human").json()["sources"]["agent_alerts"]

    client.post(f"/obs/agent-alerts/events/{event.id}/ack")

    body = client.get("/control-room/needs-human").json()
    assert body["sources"]["agent_alerts"] == before - 1
    assert [r for r in body["rows"] if r["id"] == event.id] == []
