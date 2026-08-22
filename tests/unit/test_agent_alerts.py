"""VA-6 — alerting on the agent plane.

The three properties worth guarding are the three that go wrong quietly: a quiet window
must not read as a healthy one, a ratio's denominator must hold only rows that could have
had the property, and a persistent fault must not become a pager storm.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aughor.obs.agent_alerts import (
    AgentAlertRule,
    debounce_allows,
    evaluate,
    measure,
)

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)


def _job(state="SUCCEEDED", duration_ms=100, tokens=None, agent_id="", charter_id=""):
    return {"state": state, "duration_ms": duration_ms, "agent_id": agent_id,
            "charter_id": charter_id,
            "metrics": ({"total_tokens": tokens} if tokens is not None else None)}


def _rule(**kw):
    kw.setdefault("name", "r")
    kw.setdefault("metric", "error_rate")
    kw.setdefault("threshold", 0.1)
    return AgentAlertRule(id="rule-1", **kw)


# ── unknown is never zero ─────────────────────────────────────────────────────────

def test_a_window_with_no_finished_runs_has_NO_error_rate_not_a_zero_one():
    """A quiet Sunday must not read as a perfect one, or it silences Monday's first
    failure by making the rule look already-satisfied."""
    value, population, _ = measure("error_rate", [])
    assert value is None and population == 0


def test_a_rule_declines_to_fire_on_an_empty_population_and_says_so():
    v = evaluate(_rule(metric="error_rate", comparator="lt", threshold=0.5), [], now=NOW)
    assert v.matched is False and v.should_notify is False
    assert "no population" in v.reason


def test_every_call_unpriced_is_coverage_not_a_zero_bill():
    """The most expensive form of the mistake: reporting $0.00 spend because nothing
    carried a price."""
    value, population, observed = measure("cost_usd", [], calls=[{"cost_usd": None}] * 5)
    assert value is None and population == 0
    assert observed["calls"] == 5 and observed["priced_calls"] == 0


def test_tokens_with_nothing_metered_is_none_not_zero():
    value, _, observed = measure("tokens", [_job(tokens=None), _job(tokens=None)])
    assert value is None and observed["metered_runs"] == 0


# ── the denominator holds only what could have had the property ───────────────────

def test_a_run_still_in_flight_is_not_in_the_error_rate_denominator():
    """A running job has not failed. Counting it drags the rate down exactly while a slow
    failure is unfolding."""
    jobs = [_job("FAILED"), _job("SUCCEEDED"), _job("RUNNING"), _job("PENDING")]
    value, population, observed = measure("error_rate", jobs)
    assert population == 2, "only the two terminal runs could have failed"
    assert value == 0.5
    assert observed["terminal"] == 2


def test_a_restart_orphaned_run_is_not_counted_as_an_agent_error():
    """An INTERRUPTED run is an infrastructure fact. Conflating it pages a human for a
    redeploy."""
    jobs = [_job("INTERRUPTED"), _job("INTERRUPTED"), _job("SUCCEEDED")]
    value, _, observed = measure("error_rate", jobs)
    assert value == 0.0, "no agent errors here"
    assert observed["orphaned_excluded"] == 2


def test_p95_is_measured_only_over_runs_that_recorded_a_duration():
    jobs = [_job(duration_ms=None), _job(duration_ms=1000), _job(duration_ms=2000)]
    value, population, _ = measure("p95_duration_ms", jobs)
    assert population == 2 and value == 2000


# ── firing is not notifying ───────────────────────────────────────────────────────

def test_a_persistent_fault_notifies_once_per_quiet_period_not_once_per_evaluation():
    rule = _rule(metric="failed_runs", threshold=0, debounce_minutes=30,
                 last_notified_at=(NOW - timedelta(minutes=5)).isoformat())
    v = evaluate(rule, [_job("FAILED")] * 9, now=NOW)
    assert v.matched is True, "the condition is still true"
    assert v.should_notify is False, "but it is inside the quiet period"
    assert "quiet period" in v.reason


def test_the_quiet_period_expires():
    rule = _rule(metric="failed_runs", threshold=0, debounce_minutes=30,
                 last_notified_at=(NOW - timedelta(minutes=31)).isoformat())
    assert evaluate(rule, [_job("FAILED")], now=NOW).should_notify is True


def test_a_rule_that_never_fired_is_free_to_notify():
    assert debounce_allows(_rule(debounce_minutes=30), NOW) is True


def test_zero_debounce_means_every_match_notifies():
    rule = _rule(metric="failed_runs", threshold=0, debounce_minutes=0,
                 last_notified_at=NOW.isoformat())
    assert evaluate(rule, [_job("FAILED")], now=NOW).should_notify is True


# ── scoping, comparators, and the verdict contract ────────────────────────────────

def test_a_rule_can_watch_one_agent_rather_than_the_fleet():
    jobs = [_job("FAILED", agent_id="ua_1"), _job("SUCCEEDED", agent_id="ua_2")]
    v = evaluate(_rule(metric="error_rate", threshold=0.9, comparator="gte",
                       agent_id="ua_1"), jobs, now=NOW)
    assert v.value == 1.0 and v.population == 1 and v.matched is True


def test_a_fleet_that_has_gone_QUIET_can_be_alerted_on():
    """`lt` on runs_started is how you notice nothing is running at all — the failure that
    looks like health on every other metric."""
    v = evaluate(_rule(metric="runs_started", comparator="lt", threshold=1), [], now=NOW)
    assert v.value == 0.0 and v.matched is True and v.should_notify is True


def test_a_disabled_rule_never_fires():
    v = evaluate(_rule(metric="failed_runs", threshold=0, enabled=False),
                 [_job("FAILED")], now=NOW)
    assert v.matched is False and "disabled" in v.reason


def test_the_verdict_states_its_population_so_the_number_can_be_checked():
    v = evaluate(_rule(metric="error_rate", threshold=0.1),
                 [_job("FAILED"), _job("SUCCEEDED")], now=NOW)
    assert v.population == 2 and str(v.population) in v.reason
    assert v.as_dict()["observed"]["terminal"] == 2


def test_an_unknown_metric_raises_rather_than_returning_a_confident_zero():
    with pytest.raises(ValueError):
        measure("made_up_metric", [])   # type: ignore[arg-type]
