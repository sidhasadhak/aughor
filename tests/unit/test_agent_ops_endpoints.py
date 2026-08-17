"""The Agent Ops surface's routes, and the promise that makes it a control room.

**Every number is a door.** A tile that shows 24 and opens a list of 31 is worse than no
tile — it teaches the reader that the page is decorative. So the parity between a figure
and the list it links to is a TEST, not a promise: the same shape as CR4's
`needs-human.count == Σ sources`, which is the one guarantee on this surface that has
never regressed.

Hermetic — `tests/conftest.py` points `AUGHOR_SYSTEM_DB` at a tempdir, so nothing here can
reach `data/system.db`.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


# ── the shared window reaches every panel ─────────────────────────────────────────

def test_fleet_accepts_a_range_and_ships_the_window_it_used(client):
    r = client.get("/control-room/fleet?range=7d")
    assert r.status_code == 200
    body = r.json()
    win = body["window"]
    assert win["range"] == "7d"
    assert win["buckets"] == len(body["edges"]), "the x axis and the bar count must agree"
    assert body["tiles"]["window"]["since"] == win["since"]


def test_every_row_spark_has_exactly_one_bar_per_bucket(client):
    """The old surface drew client-side 1-minute buckets over an hour beside server-side
    hourly buckets over a day — two time bases in one table, which cannot be read."""
    body = client.get("/control-room/fleet?range=24h").json()
    n = body["window"]["buckets"]
    for row in body["rows"] + body["runners"]:
        assert len(row["spark"]) == n, f"{row['name']} drew {len(row['spark'])} of {n}"


@pytest.mark.parametrize("range_key", ["1h", "24h", "7d", "30d"])
def test_the_fleet_answers_for_every_offered_range(client, range_key):
    body = client.get(f"/control-room/fleet?range={range_key}").json()
    assert body["window"]["range"] == range_key
    assert body["tiles"]["runs_started"] >= 0


# ── runners are reported, and kept out of the agent numbers ───────────────────────

def test_runners_are_a_separate_list_never_an_agent_row(client):
    body = client.get("/control-room/fleet?range=24h").json()
    assert "runners" in body
    assert all(r["kind"] in ("charter", "persona") for r in body["rows"]), (
        "a runner in `rows` is the defect this split exists to fix")
    assert all(r["kind"] == "runner" for r in body["runners"])
    assert "Unassigned kinds" not in [r["name"] for r in body["runners"]], (
        "name a runner for what it is, not for the lookup that produced it")


def test_the_tiles_say_what_they_left_out(client):
    """A reader who sees '24 runs' while the machine did 1,315 things is owed the
    difference — stated, not implied by an absence."""
    tiles = client.get("/control-room/fleet?range=24h").json()["tiles"]
    assert "runner_runs" in tiles and tiles["include_runners"] is False


def test_include_runners_changes_the_count_it_claims_to(client):
    off = client.get("/control-room/fleet?range=30d").json()["tiles"]
    on = client.get("/control-room/fleet?range=30d&include_runners=true").json()["tiles"]
    assert on["include_runners"] is True
    assert on["runs_started"] >= off["runs_started"]
    assert on["runs_started"] == off["runs_started"] + off["runner_runs"]


# ── cost, priced from the provider, honest about its gaps ─────────────────────────

def test_cost_ships_with_the_share_nothing_could_price(client):
    cost = client.get("/control-room/fleet?range=24h").json()["tiles"]["cost"]
    assert set(cost) >= {"usd", "unpriced_calls", "is_complete", "calls"}
    if cost["unpriced_calls"]:
        assert cost["is_complete"] is False, (
            "a cost figure with unpriced calls in it must not claim to be complete")


# ── the timeseries: one axis for everything ───────────────────────────────────────

@pytest.mark.parametrize("group", ["model", "provider", "charter", "agent", "role", "kind"])
def test_timeseries_answers_on_every_group(client, group):
    body = client.get(f"/obs/timeseries?group={group}&range=24h").json()
    assert body["measured"] is True
    assert body["group"] == group
    assert len(body["edges"]) == body["window"]["buckets"]
    for s in body["series"]:
        assert len(s["values"]) == body["window"]["buckets"]


def test_the_runs_chart_plots_the_same_runs_the_runs_tile_counts(client):
    """Found by looking at the page: the chart was headed "Runs by agent" and plotting
    model CALLS grouped by charter, so every bar read "(unattributed)" — the attribution
    is stamped at write time and no historical call carries it. Runs are attributed by
    the charter that owns each job KIND, derived at read time, so they are complete for
    all history. A chart that contradicts the tile above it is worse than no chart.
    """
    _seed(n_profile=4, n_automation=11)
    tiles = client.get("/control-room/fleet?range=1h").json()["tiles"]
    chart = client.get("/obs/timeseries?source=jobs&range=1h").json()
    assert chart["measure"] == "runs" and chart["group"] == "charter"
    assert chart["agent_runs"] == tiles["runs_started"] == 4
    assert chart["runner_runs"] == tiles["runner_runs"] == 11
    assert sum(sum(s["values"]) for s in chart["series"]) == 4, (
        "the drawn series must sum to the tile; runners live in their own list")
    assert all(s["key"] for s in chart["series"]), "a run always knows its charter"
    assert chart["coverage"] == 1.0


def test_timeseries_refuses_an_unknown_group_rather_than_substituting_one(client):
    """Silently answering a different question than the one asked is the single thing a
    usage page cannot do."""
    r = client.get("/obs/timeseries?group=wishful")
    assert r.status_code == 400
    assert "wishful" in r.json()["detail"]


def test_timeseries_reports_its_own_coverage(client):
    """A top-N built from 3% of the traffic is not a top-N."""
    body = client.get("/obs/timeseries?group=charter&range=7d").json()
    assert "coverage" in body and "attributed" in body and "scanned" in body


# ── the drill filters: the door actually opens ────────────────────────────────────

def test_activity_accepts_every_drill_filter(client):
    for q in ("model=x", "provider=y", "charter=curator", "job_id=j1", "role=coder",
              "trace_id=t1"):
        r = client.get(f"/activity?{q}&limit=5")
        assert r.status_code == 200, q
        assert r.json()["measured"] is True


def test_activity_window_is_reported_when_asked_for(client):
    body = client.get("/activity?range=24h&limit=5").json()
    assert body["window"] is not None and body["window"]["range"] == "24h"
    assert client.get("/activity?limit=5").json()["window"] is None, (
        "an unwindowed tail is the pre-existing behaviour and must stay available")


# ── usage summary: the tiles the Usage page is made of ────────────────────────────

def _seed_calls(n: int = 3) -> None:
    """Write llm_call rows inside the window.

    Load-bearing. The first version of these tests asserted over an EMPTY store, so the
    per-model list comprehension never executed and the endpoint's 500 — it reached for
    `UsageRow.failure_rate`, which does not exist — shipped past a green test and was
    caught only by calling the live route. A test whose population is empty proves the
    shape of nothing.
    """
    from aughor.kernel.ledger import Ledger

    led = Ledger.default()
    now = datetime.now(timezone.utc)
    for i in range(n):
        led.session_event_insert({
            "trace_id": f"seed-trace-{i}", "kind": "llm_call", "name": "seed",
            "at": _iso(now - timedelta(minutes=i + 1)),
            "provider": "openrouter", "model": "vendor/seed-model:free",
            "prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120,
            "duration_ms": 250.0, "ok": True, "charter_id": "curator",
            "payload": {"role": "coder", "caller": "seed_site", "fallback": i == 0},
        })


def test_usage_summary_renders_every_model_row_it_promises(client):
    """The regression for the live 500: with rows present, each model row must carry the
    derived fields the panel reads."""
    _seed_calls()
    body = client.get("/obs/usage-summary?range=24h").json()
    assert body["calls"] >= 3
    assert body["models"], "seeded calls must produce model rows"
    row = body["models"][0]
    for field in ("calls", "total_tokens", "failures", "failure_rate", "mean_ms",
                  "cost_usd", "cost_is_complete", "calls_without_usage", "model"):
        assert field in row, f"the Usage panel reads {field}; the endpoint omitted it"
    assert body["sites"] and body["roles"], "call sites and roles fold from the payload"


def test_usage_summary_carries_coverage_and_a_two_sided_fallback_rate(client):
    _seed_calls()
    body = client.get("/obs/usage-summary?range=7d").json()
    assert set(body) >= {"calls", "tokens", "cost_usd", "unpriced_calls",
                         "calls_without_usage", "fallback", "models", "sites", "roles"}
    fb = body["fallback"]
    assert set(fb) == {"fell_back", "of_attributed", "rate"}, (
        "a rate whose denominator is invisible gets read as 'right now'")
    if fb["of_attributed"] == 0:
        assert fb["rate"] is None, "no eligible calls is None, never a confident 0%"


def test_usage_summary_never_claims_completeness_it_does_not_have(client):
    body = client.get("/obs/usage-summary?range=30d").json()
    assert body["cost_is_complete"] == (body["unpriced_calls"] == 0)


# ── the parity ratchet: every tile equals the list it opens ───────────────────────

def _seed(n_profile: int, n_automation: int):
    """Write jobs directly, at a known instant inside the window."""
    import sqlite3

    from aughor.kernel.ledger import Ledger

    led = Ledger.default()
    now = datetime.now(timezone.utc)
    c = sqlite3.connect(led.path)
    c.execute("DELETE FROM jobs")
    i = 0
    for kind, count in (("profile", n_profile), ("automation", n_automation)):
        for _ in range(count):
            c.execute("INSERT INTO jobs (id, kind, state, created_at, started_at, "
                      "finished_at) VALUES (?,?,?,?,?,?)",
                      (f"seed-{i}", kind, "SUCCEEDED",
                       _iso(now - timedelta(minutes=5)), _iso(now - timedelta(minutes=5)),
                       _iso(now - timedelta(minutes=4))))
            i += 1
    c.commit()
    c.close()


def test_runs_tile_equals_the_agent_jobs_it_links_to(client):
    """THE ratchet. 3 agent runs and 40 runner ticks must read as 3, with the 40 named."""
    _seed(n_profile=3, n_automation=40)
    body = client.get("/control-room/fleet?range=1h").json()
    tiles = body["tiles"]
    assert tiles["runs_started"] == 3, "the tick must not be counted as agent work"
    assert tiles["runner_runs"] == 40
    # and the table agrees with the tile
    assert sum(r.get("runs", 0) for r in body["rows"] if r["kind"] == "charter") == 3
    assert sum(r["runs"] for r in body["runners"]) == 40


def test_the_runs_per_minute_figure_is_agents_not_a_heartbeat(client):
    """Measured live 2026-08-17: 1.10 with the tick, 0.10 without. The tick is a cron."""
    _seed(n_profile=1, n_automation=59)
    tiles = client.get("/control-room/fleet?range=1h").json()["tiles"]
    assert tiles["runs_per_min"] < 0.5, (
        f"runs_per_min {tiles['runs_per_min']} is reading the automation heartbeat")
