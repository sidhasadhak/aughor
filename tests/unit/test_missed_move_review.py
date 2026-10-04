"""Idea 8 — "when someone finds a big move nothing flagged, the platform works out why (no alert?
window too short? triage held it?) and proposes the fix." Every answer the review can give is
driven here through the real stores (monitors, inbox, departures) and the Watcher's own series
code, against a synthetic daily series; only the warehouse read and the metric list are stubbed.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from aughor.monitors import missed, sentinel

TODAY = date(2026, 10, 4)
SPIKE = date(2026, 9, 20)
CAND = sentinel.Candidate(name="revenue_mr", label="Revenue", series_sql="SELECT day, value FROM s_mr",
                          source="defined")


def _series(spike_value: float = 160.0):
    days = [TODAY - timedelta(days=i) for i in range(130, -1, -1)]
    return [(d, spike_value if d == SPIKE else 100.0 + ((d.toordinal() % 7) - 3)) for d in days]


@pytest.fixture
def world(monkeypatch):
    monkeypatch.setattr(sentinel, "candidates", lambda conn, schema_name=None, since=None: [CAND])
    monkeypatch.setattr("aughor.settling.learned_lag_days", lambda conn: 1)
    state = {"series": _series()}
    run_sql = lambda sql: (["day", "value"], [list(p) for p in state["series"]], None)  # noqa: E731
    return state, run_sql


def _review(run_sql, day=SPIKE, stage=False, conn="conn-missed", **kw):
    return missed.review_missed(conn, "revenue_mr", day.isoformat(), stage=stage, run_sql=run_sql,
                                today=TODAY, **kw)


def test_nothing_watching_and_a_quiet_watch_would_have_caught_it(world):
    _state, run_sql = world
    r = _review(run_sql, conn="conn-missed-1")
    assert r.z is not None and r.z > 10
    assert "Nothing was watching it. A 2.5σ watch would have caught it" in r.verdict
    assert r.proposal["would_stage"] is True
    staged = _review(run_sql, stage=True, conn="conn-missed-1")
    assert staged.proposal["created"] is True and "proposed in the inbox" in staged.verdict
    from aughor.actions.inbox import get_proposal
    p = get_proposal(staged.proposal["proposal_id"])
    assert (p.kind, p.proposer, p.call_id) == ("monitor_bundle", "watcher", "alert:revenue_mr")


def test_an_ordinary_day_is_said_to_be_one(world):
    from aughor.monitors.models import Monitor
    from aughor.monitors.store import upsert_monitor
    state, run_sql = world
    state["series"] = _series(spike_value=101.0)
    r = _review(run_sql, conn="conn-missed-2")
    assert "an ordinary day" in r.verdict and not r.proposal
    # Found by the isolated receipt: a watch created AFTER the day used to be the verdict.
    upsert_monitor(Monitor(conn_id="conn-missed-2", name="Late watch", metric_name="revenue_mr",
                           alert_on="anomaly", sigma_threshold=2.5, created_at="2026-10-01T00:00:00Z"))
    late = _review(run_sql, conn="conn-missed-2")
    assert "an ordinary day" in late.verdict and "'Late watch'" in late.verdict


def test_a_day_still_settling_is_not_scored_yet(world, monkeypatch):
    _state, run_sql = world
    monkeypatch.setattr("aughor.settling.learned_lag_days", lambda conn: 20)
    r = _review(run_sql, conn="conn-missed-3")
    assert "still settling" in r.verdict and "2026-10-10" in r.verdict


def test_a_watch_too_loose_to_count_it_is_named(world):
    from aughor.monitors.models import Monitor
    from aughor.monitors.store import upsert_monitor
    _state, run_sql = world
    upsert_monitor(Monitor(conn_id="conn-missed-4", name="Revenue watch", custom_sql=CAND.series_sql,
                           alert_on="anomaly", sigma_threshold=99.0, created_at="2026-01-01T00:00:00Z"))
    r = _review(run_sql, conn="conn-missed-4")
    assert [w.rule for w in r.watches] == ["anomaly at 99σ"] and r.watches[0].would_have_fired is False
    assert "'Revenue watch' was watching it (anomaly at 99σ) and its rule did not count" in r.verdict


def test_a_breach_that_fired_but_was_held_is_traced_to_the_gate(world):
    from aughor.automations.models import Automation
    from aughor.automations.store import upsert_automation
    from aughor.govern.departure_store import record_departure
    from aughor.monitors.models import Monitor, MonitorAlert
    from aughor.monitors.store import append_alert, upsert_monitor
    _state, run_sql = world
    m = upsert_monitor(Monitor(conn_id="conn-missed-5", name="Revenue alarm", metric_name="revenue_mr",
                               alert_on="anomaly", sigma_threshold=2.5, created_at="2026-01-01T00:00:00Z"))
    append_alert(MonitorAlert(monitor_id=m.id, conn_id="conn-missed-5", monitor_name=m.name,
                              triggered_at="2026-09-21T09:00:00Z", severity="critical", message="spike"))
    chain = upsert_automation(Automation(
        conn_id="conn-missed-5", name="Revenue alarm chain",
        conditions=[{"kind": "metric", "config": {"monitor_id": m.id}}],
        effects=[{"kind": "notify", "config": {"trigger_id": "t1"}}]))
    record_departure(id="dep-missed-5", kind="slack_post", state="held", conn_id="conn-missed-5",
                     automation_id=chain.id, automation_name=chain.name, ts="2026-09-21T09:01:00Z")
    r = _review(run_sql, conn="conn-missed-5")
    assert r.watches[0].fired and r.watches[0].held
    assert "It WAS flagged: 'Revenue alarm' fired on 2026-09-21" in r.verdict
    assert "held at the departure gate" in r.verdict


def test_a_proposal_still_waiting_is_the_fix(world):
    _state, run_sql = world
    first = _review(run_sql, stage=True, conn="conn-missed-6")           # the Watcher's proposal
    again = _review(run_sql, conn="conn-missed-6")
    assert f"it is pending in the inbox (proposal {first.proposal['proposal_id']})" in again.verdict


def test_an_unknown_metric_names_the_ones_that_have_a_series(world):
    _state, run_sql = world
    r = missed.review_missed("conn-missed-7", "nonsense", SPIKE.isoformat(), run_sql=run_sql, today=TODAY)
    assert "No daily series for 'nonsense'" in r.verdict and "revenue_mr" in r.verdict
