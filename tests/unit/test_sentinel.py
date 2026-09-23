"""Idea 2 · the Watcher proposes the alerts worth having.

The distribution is learned from a series, the threshold is the one a replay earns, the
still-settling days are not scored, and what is staged is the inbox's own `monitor_bundle`
— unarmed, destination open, never duplicated, never resurrected once a person resolved it.
"""
from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from aughor.monitors import sentinel
from aughor.monitors.sentinel import (
    candidates, choose_sigma, daily_series_sql, learn_distribution,
    propose_for_connection, read_series,
)

D0 = date(2026, 6, 1)


def _series(n: int = 100, base: float = 100.0, spikes: dict[int, float] | None = None):
    pts = []
    for i in range(n):
        v = base + (i % 7) * 2.0          # a mild weekly pattern, σ ≈ 4
        if spikes and i in spikes:
            v = spikes[i]
        pts.append((D0 + timedelta(days=i), v))
    return pts


# ── the distribution and its threshold ───────────────────────────────────────────

def test_the_threshold_is_the_smallest_that_fires_at_most_three_times_in_the_replay():
    values = [v for _, v in _series(100, spikes={40: 400.0, 70: 400.0})]
    sigma, fired = choose_sigma(values)
    assert sigma == 2.5 and fired == [40, 70]
    # A noisier series climbs the ladder until the replay quietens.
    noisy = [v for _, v in _series(100, spikes={i: 130.0 for i in range(20, 100, 9)})]
    sigma2, fired2 = choose_sigma(noisy)
    assert sigma2 > 2.5 and len(fired2) <= sentinel.MAX_FIRINGS or sigma2 == sentinel.SIGMA_LADDER[-1]


def test_the_distribution_drops_still_settling_days_and_reports_the_replay():
    pts = _series(100, spikes={95: 400.0})
    today = D0 + timedelta(days=100)
    dist = learn_distribution(pts, today=today, settle_days=8)
    assert dist is not None
    assert dist.last_day == today - timedelta(days=8)       # the youngest 8 days are not scored
    assert dist.n == sentinel.HISTORY_DAYS
    assert dist.would_have_fired == 0 and dist.fired_days == []   # the spike sat inside the settling window
    quick = learn_distribution(pts, today=today, settle_days=1)
    assert quick is not None and quick.would_have_fired == 1
    assert quick.fired_days == [(D0 + timedelta(days=95)).isoformat()]
    assert quick.mean == pytest.approx(106.0, abs=4) and quick.std > 0


def test_too_few_settled_days_is_no_distribution_at_all():
    assert learn_distribution(_series(20), today=D0 + timedelta(days=20)) is None
    assert learn_distribution(_series(30), today=D0 + timedelta(days=30), settle_days=12) is None


# ── series ───────────────────────────────────────────────────────────────────────

def test_read_series_sorts_dates_and_refuses_a_breakdown():
    ok = read_series(lambda sql: (["d", "v"], [("2026-06-03", 3), (date(2026, 6, 1), 1), ("2026-06-02", None)], None), "q")
    assert ok == [(date(2026, 6, 1), 1.0), (date(2026, 6, 2), 0.0), (date(2026, 6, 3), 3.0)]
    assert read_series(lambda sql: (["cat", "v"], [("Jeans", 3), ("Swim", 1)], None), "q") == []
    assert read_series(lambda sql: ([], [], "permission denied"), "q") == []
    assert read_series(lambda sql: (_ for _ in ()).throw(RuntimeError("down")), "q") == []


def test_the_daily_series_sql_wraps_the_approved_expression_like_value_query():
    sql = daily_series_sql("SUM(sale_price)", "order_items", "created_at", ["status = 'Complete'"])
    assert sql == ('SELECT CAST("created_at" AS DATE) AS day, (SUM(sale_price)) AS value '
                   "FROM order_items WHERE status = 'Complete' GROUP BY 1 ORDER BY 1")
    # Found live: an unbounded series is cut by the executor's row cap, and "the last 90
    # days" of the cut series ended two years early. The window is asked for IN the SQL.
    bounded = daily_series_sql("COUNT(*)", "orders", "created_at", since=date(2026, 5, 1))
    assert bounded.endswith("""WHERE CAST("created_at" AS DATE) >= DATE '2026-05-01' GROUP BY 1 ORDER BY 1""")


def test_a_series_that_ends_long_ago_is_stale_or_truncated_and_stages_nothing(monkeypatch):
    monkeypatch.setattr("aughor.business_profile.store.load",
                        lambda cid, schema=None: _profile_with("Revenue"))
    monkeypatch.setattr("aughor.settling.sampler.time_tables", lambda cid: [])
    monkeypatch.setattr("aughor.semantic.metrics.list_metrics", lambda connection_id=None: [])
    monkeypatch.setattr("aughor.settling.learned_lag_days", lambda cid: None)
    old = [((date(2024, 6, 1) + timedelta(days=i)).isoformat(), 100.0 + (i % 7) * 2.0)
           for i in range(100)]                                   # June–Sept 2024
    result = propose_for_connection("c-stale", run_sql=lambda sql: (["d", "v"], old, None),
                                    today=date(2026, 9, 23))
    assert result["staged"] == []
    assert result["skipped"]["Revenue"].startswith("the series ends on 2024-09-08 — stale, or truncated")
    assert result["since"] == "2026-05-18"          # 90 + 30 + 1 + 7 = 128 days back, asked for in SQL


# ── candidates ───────────────────────────────────────────────────────────────────

def _profile_with(*names):
    return SimpleNamespace(north_star_metrics=[
        SimpleNamespace(name=n, chart_sql=f"SELECT day, v FROM trend_{n}", unit_or_range="USD")
        for n in names])


def test_candidates_come_from_the_north_star_trends_and_approved_metrics_on_time_tables(monkeypatch):
    monkeypatch.setattr("aughor.business_profile.store.load",
                        lambda cid, schema=None: _profile_with("Revenue", "AOV"))
    monkeypatch.setattr("aughor.settling.sampler.time_tables",
                        lambda cid: [("thelook.orders", "created_at", 100)])
    metrics = [
        SimpleNamespace(name="revenue", label="Revenue", status="approved", sql="SUM(sale_price)",
                        tables=["orders"], filters=[], unit="$"),            # shadowed by the trend's name
        SimpleNamespace(name="units_sold", label="Units sold", status="approved", sql="COUNT(*)",
                        tables=["orders"], filters=["status = 'Complete'"], unit=""),
        SimpleNamespace(name="draft_metric", label="Draft", status="draft", sql="COUNT(*)",
                        tables=["orders"], filters=[], unit=""),               # not approved
        SimpleNamespace(name="no_clock", label="No clock", status="approved", sql="COUNT(*)",
                        tables=["products"], filters=[], unit=""),            # no timestamp
        SimpleNamespace(name="whole_select", label="Whole", status="approved",
                        sql="SELECT 1", tables=["orders"], filters=[], unit=""),  # states its own shape
    ]
    monkeypatch.setattr("aughor.semantic.metrics.list_metrics", lambda connection_id=None: metrics)
    got = candidates("c1", since=date(2026, 5, 8))
    assert [(c.name, c.source) for c in got] == [("Revenue", "explorer"), ("AOV", "explorer"),
                                                 ("units_sold", "defined")]
    assert got[2].series_sql.startswith('SELECT CAST("created_at" AS DATE) AS day, (COUNT(*)) AS value FROM orders WHERE')
    assert "status = 'Complete' AND CAST(\"created_at\" AS DATE) >= DATE '2026-05-08'" in got[2].series_sql


# ── staging ──────────────────────────────────────────────────────────────────────

@pytest.fixture
def two_metrics(monkeypatch):
    monkeypatch.setattr("aughor.business_profile.store.load",
                        lambda cid, schema=None: _profile_with("Revenue", "Orders", "Breakdown"))
    monkeypatch.setattr("aughor.settling.sampler.time_tables", lambda cid: [])
    monkeypatch.setattr("aughor.semantic.metrics.list_metrics", lambda connection_id=None: [])
    monkeypatch.setattr("aughor.settling.learned_lag_days", lambda cid: 8 if cid == "c-lag" else None)

    def run_sql(sql):
        if "Breakdown" in sql:
            return (["cat", "v"], [("Jeans", 3)], None)
        if "Orders" in sql:
            return (["d", "v"], [(D0 + timedelta(days=i), 10.0) for i in range(10)], None)   # too short
        return (["d", "v"], [(d.isoformat(), v) for d, v in _series(100, spikes={50: 400.0})], None)

    return run_sql


def test_the_watcher_stages_a_monitor_bundle_with_its_evidence_and_an_open_destination(two_metrics):
    from aughor.actions.inbox import get_proposal

    today = D0 + timedelta(days=100)
    result = propose_for_connection("c-lag", run_sql=two_metrics, today=today)
    assert result["settle_days"] == 8 and result["candidates"] == 3
    assert [s["metric"] for s in result["staged"]] == ["Revenue"]
    assert result["skipped"] == {
        "Orders": "too few settled days (10 points; needs 21 settled)",
        "Breakdown": "no daily series (the query returned no (day, value) rows)"}
    staged = result["staged"][0]
    assert staged["sigma"] == 2.5 and staged["would_have_fired"] == 1

    p = get_proposal(staged["proposal_id"])
    assert p is not None and p.kind == "monitor_bundle" and p.proposer == "watcher"
    assert p.run_id == "sentinel:v3:c-lag" and p.call_id == "alert:revenue"
    monitor, chain = p.params["monitor"], p.params["automation"]
    assert monitor["custom_sql"] == "SELECT day, v FROM trend_Revenue"
    assert monitor["alert_on"] == "anomaly" and monitor["sigma_threshold"] == 2.5
    assert monitor["check_cron"] == sentinel.CHECK_CRON
    assert chain["effects"][1]["config"]["channel"] == ""          # the destination is the approver's
    assert p.detail["to_fill"], "an open choice must be named, or Accept would post nowhere"
    assert p.detail["distribution"]["would_have_fired"] == 1
    assert p.detail["distribution"]["settle_days"] == 8
    assert "would have fired 1 time" in p.reasoning and "still settling" in p.reasoning
    assert "SQL only" in p.reasoning


def test_a_rerun_stages_nothing_twice_and_never_resurrects_a_resolved_proposal(two_metrics):
    from aughor.actions.inbox import reject_proposal

    today = D0 + timedelta(days=100)
    first = propose_for_connection("c-plain", run_sql=two_metrics, today=today)
    assert [s["metric"] for s in first["staged"]] == ["Revenue"]
    again = propose_for_connection("c-plain", run_sql=two_metrics, today=today)
    assert again["staged"] == [] and again["already_staged"] == ["Revenue"]

    reject_proposal(first["staged"][0]["proposal_id"], actor="user:a@b")
    after = propose_for_connection("c-plain", run_sql=two_metrics, today=today)
    assert after["staged"] == [] and after["already_staged"] == ["Revenue"]


def test_a_new_evidence_method_supersedes_what_the_old_one_left_pending(two_metrics, monkeypatch):
    from aughor.actions.inbox import get_proposal

    today = D0 + timedelta(days=100)
    monkeypatch.setattr(sentinel, "METHOD_VERSION", "v2")
    old = propose_for_connection("c-method", run_sql=two_metrics, today=today)
    old_id = old["staged"][0]["proposal_id"]
    assert get_proposal(old_id).run_id == "sentinel:v2:c-method"

    monkeypatch.setattr(sentinel, "METHOD_VERSION", "v3")
    new = propose_for_connection("c-method", run_sql=two_metrics, today=today)
    assert new["superseded"] == [old_id]
    assert [s["metric"] for s in new["staged"]] == ["Revenue"]
    assert get_proposal(old_id).status == "superseded"
    assert get_proposal(new["staged"][0]["proposal_id"]).run_id == "sentinel:v3:c-method"
    # A re-run under the same method supersedes nothing and stages nothing twice.
    again = propose_for_connection("c-method", run_sql=two_metrics, today=today)
    assert again["superseded"] == [] and again["staged"] == [] and again["already_staged"] == ["Revenue"]


def test_a_watch_the_ladder_cannot_quieten_is_not_proposed(monkeypatch):
    # theLook, 2026-09-23, before any settling lag was learned: the youngest days read ~8×
    # high, and even 4σ would have fired five times. That is noise, and it is not staged.
    monkeypatch.setattr("aughor.business_profile.store.load",
                        lambda cid, schema=None: _profile_with("Revenue"))
    monkeypatch.setattr("aughor.settling.sampler.time_tables", lambda cid: [])
    monkeypatch.setattr("aughor.semantic.metrics.list_metrics", lambda connection_id=None: [])
    monkeypatch.setattr("aughor.settling.learned_lag_days", lambda cid: None)
    # Six spikes, each ten times the last: every one lands far outside the σ of the window
    # before it, so no threshold on the ladder brings the replay under three firings.
    spikes = {60 + 8 * k: 10.0 ** (k + 3) for k in range(6)}
    rows = [(d.isoformat(), v) for d, v in _series(100, spikes=spikes)]
    result = propose_for_connection("c-noisy", run_sql=lambda sql: (["d", "v"], rows, None),
                                    today=D0 + timedelta(days=100))
    assert result["staged"] == []
    reason = result["skipped"]["Revenue"]
    assert reason.startswith("too noisy to propose: even a 4.0σ watch would have fired")
    assert "settling lag is not learned yet" in reason


def test_the_watcher_owns_the_job_kind():
    from aughor.kernel.agents import charter_for_kind, get_charter

    assert charter_for_kind(sentinel.JOB_KIND).id == "watcher"
    assert "alert_proposals" in get_charter("watcher").job_kinds


def test_the_door_runs_the_same_work(monkeypatch):
    from fastapi.testclient import TestClient

    from aughor.api import app

    monkeypatch.setattr("aughor.business_profile.store.load", lambda cid, schema=None: None)
    monkeypatch.setattr("aughor.settling.sampler.time_tables", lambda cid: [])
    monkeypatch.setattr("aughor.semantic.metrics.list_metrics", lambda connection_id=None: [])
    monkeypatch.setattr("aughor.db.measure.run_sql_for", lambda cid: (lambda sql: ([], [], None)))
    r = TestClient(app).post("/alerts/propose/c-empty")
    assert r.status_code == 200
    body = r.json()
    assert {k: body[k] for k in ("connection_id", "candidates", "staged", "already_staged", "skipped",
                                 "settle_days", "superseded")} == {
        "connection_id": "c-empty", "candidates": 0, "staged": [], "already_staged": [],
        "skipped": {}, "settle_days": 1, "superseded": []}
    assert body["since"] < date.today().isoformat()
