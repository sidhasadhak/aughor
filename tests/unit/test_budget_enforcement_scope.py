"""Budget enforcement when job and supervisor do not share a process.

The kernel enforces token budgets from the heartbeat, which reads the run's live
accumulator out of `metering._by_job` — a module-level registry that is process-local
by contract. The durable-execution plan (docs/VERCEL_PLATFORM_DESIGN_2026-08-05.md §2)
splits job from supervisor, at which point the supervisor's lookup misses; the old
check treated a miss as "no spend", so token budgets silently stopped being enforced
behind healthy heartbeats — the §5.2 defect class: nothing errors, a limit just
quietly stops existing.

The fix is flush + rehydrate: the heartbeat persists the live snapshot onto the job
row it already updates, and budget readers fall back to that row when the registry
misses. These tests demonstrate the miss (why the fallback exists), the fallback, and
the full heartbeat → cancel chain running off the flushed row alone.

No pytest-asyncio in the env — each test drives the kernel inside asyncio.run.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from aughor.kernel import jobs as J
from aughor.kernel import metering
from aughor.kernel.jobs import JobKernel, JobState
from aughor.kernel.ledger import Ledger


@pytest.fixture()
def ledger(tmp_path):
    return Ledger(tmp_path / "system.db")


def _gov(token_budget=None, time_budget_s=None):
    # model=None so _set_run_model's best-effort resolve is a no-op.
    return SimpleNamespace(token_budget=token_budget, time_budget_s=time_budget_s, model=None)


def _insert_job(ledger, job_id: str, *, metrics: dict | None = None) -> None:
    ledger.job_insert({
        "id": job_id, "kind": "exploration", "conn_id": "c1", "canvas_id": None,
        "org_id": "default", "state": JobState.RUNNING, "payload": None,
        "idempotency_key": None, "attempt": 1, "created_at": "2026-08-05T00:00:00+00:00",
    })
    if metrics is not None:
        ledger.job_update(job_id, metrics=json.dumps(metrics))


# ── the miss, and what it must not mean ──────────────────────────────────────

def test_registry_lookup_misses_for_a_job_in_another_process(ledger):
    """The premise: a supervisor cannot see a worker's accumulator. The registry
    alone answers None — which the OLD budget check read as 'not over budget'."""
    _insert_job(ledger, "job-elsewhere", metrics={"total_tokens": 500_000})
    assert metering.metrics_for_job("job-elsewhere") is None


def test_over_budget_enforces_from_the_flushed_row(ledger):
    """The fix: a registry miss falls back to the snapshot the worker's heartbeat
    flushed. 500k spent against a 100k budget must read as blown — one beat stale
    is enforcement; a kill that never comes is not."""
    _insert_job(ledger, "job-elsewhere", metrics={"total_tokens": 500_000})
    k = JobKernel(ledger)
    over = k._over_budget("job-elsewhere", _gov(token_budget=100_000), elapsed_s=1.0)
    assert over is not None and "token budget" in over


def test_no_row_and_no_registry_still_means_unknown_not_over(ledger):
    """Fail-open holds: with nothing to read anywhere, the token check stays silent
    (the time budget still enforces from the heartbeat's own clock)."""
    _insert_job(ledger, "job-unknown")
    k = JobKernel(ledger)
    assert k._over_budget("job-unknown", _gov(token_budget=100_000), elapsed_s=1.0) is None
    over = k._over_budget("job-unknown", _gov(token_budget=100_000, time_budget_s=1), elapsed_s=5.0)
    assert over is not None and "time budget" in over


def test_live_registry_wins_over_a_stale_flushed_row(ledger):
    """In-process, the live accumulator is exact and must be preferred — the flushed
    row lags by up to one heartbeat."""
    _insert_job(ledger, "job-here", metrics={"total_tokens": 999_999})
    token = metering.start()
    try:
        metering.register_job("job-here")
        m = J._live_or_flushed_metrics("job-here", ledger)
        assert m is not None and m.total_tokens == 0      # live (fresh), not the stale row
    finally:
        metering.unregister_job("job-here")
        metering.reset(token)


# ── snapshot round-trip ──────────────────────────────────────────────────────

def test_from_snapshot_round_trips_and_survives_unknown_keys():
    m = metering.RunMetrics(total_tokens=1234, llm_calls=7, org_id="acme")
    snap = m.to_dict()
    snap["a_field_added_in_a_future_version"] = "ignored"
    back = metering.from_snapshot(snap)
    assert back is not None
    assert (back.total_tokens, back.llm_calls, back.org_id) == (1234, 7, "acme")


def test_from_snapshot_is_fail_open_on_garbage():
    assert metering.from_snapshot(None) is None
    assert metering.from_snapshot("not a dict") is None
    assert metering.from_snapshot({"total_tokens": object()}) is None


def test_snapshot_for_job_is_registry_only(ledger):
    """The write side must never read the ledger back — flushing a value that was
    itself rehydrated would launder staleness into freshness."""
    _insert_job(ledger, "job-elsewhere", metrics={"total_tokens": 500_000})
    assert metering.snapshot_for_job("job-elsewhere") is None


# ── the real chain: heartbeat flushes, supervisor kills off the row ──────────

def test_heartbeat_flushes_live_spend_onto_the_job_row(ledger, monkeypatch):
    """While a job runs, its row's `metrics` fills in — the Fleet view shows live
    spend, and any other process can now read what this one is spending."""
    monkeypatch.setattr(J, "_HEARTBEAT_SECONDS", 0.05)
    monkeypatch.setattr(JobKernel, "_resolve_governance", lambda self, jid: (_gov(), "test-agent"))

    async def main():
        k = JobKernel(ledger)
        release = asyncio.Event()

        async def work():
            metering.record_llm(prompt_tokens=400, completion_tokens=100)
            await asyncio.wait_for(release.wait(), 10)

        jid = await k.submit("exploration", work, conn_id="c1")
        # Wait for a beat to flush spend onto the row while the job still RUNS.
        for _ in range(200):
            row = ledger.job_get(jid) or {}
            if isinstance(row.get("metrics"), dict) and row["metrics"].get("total_tokens") == 500:
                assert row["state"] == JobState.RUNNING
                break
            await asyncio.sleep(0.02)
        else:
            pytest.fail("no heartbeat flush observed within 4s")
        release.set()
        while jid in k._tasks:
            await asyncio.sleep(0.01)
        return jid

    jid = asyncio.run(main())
    # The final flush stands after completion — a late beat must not null it.
    row = ledger.job_get(jid)
    assert row["state"] == JobState.SUCCEEDED
    assert row["metrics"]["total_tokens"] == 500


def test_supervisor_kills_over_budget_run_it_cannot_see(ledger, monkeypatch):
    """End to end through the REAL heartbeat loop: the run's accumulator is made
    invisible to the supervisor (as another process's memory is), its spend standing
    only on the flushed row — the supervisor must still cancel it for the token
    budget, stamping the reason. This is the test that fails if the fallback goes."""
    monkeypatch.setattr(J, "_HEARTBEAT_SECONDS", 0.05)
    monkeypatch.setattr(JobKernel, "_resolve_governance",
                        lambda self, jid: (_gov(token_budget=100), "test-agent"))

    async def main():
        k = JobKernel(ledger)

        async def work():
            metering.record_llm(prompt_tokens=400, completion_tokens=100)   # 500 > 100
            jid = J.current_job_id()
            # Simulate the process split: flush spend to the row (as the worker's own
            # beat would), then drop out of THIS process's registry so the supervisor
            # can only see the durable state.
            snap = metering.snapshot_for_job(jid)
            ledger.job_update(jid, metrics=json.dumps(snap))
            metering.unregister_job(jid)
            await asyncio.sleep(30)          # would run forever; the kill ends it

        jid = await k.submit("exploration", work, conn_id="c1")
        for _ in range(200):
            row = ledger.job_get(jid) or {}
            if row.get("state") == JobState.CANCELLED:
                return jid, row
            await asyncio.sleep(0.02)
        pytest.fail("supervisor never cancelled the over-budget run")

    jid, row = asyncio.run(main())
    assert "budget exceeded" in (row.get("error") or "")
    events = [e for e in ledger.events(kind="budget.exceeded") if e.get("job_id") == jid]
    assert events, "budget.exceeded event was not emitted"


# ── headroom reads the same story ────────────────────────────────────────────

def test_budget_fraction_used_reads_the_flushed_row(monkeypatch):
    """An agent reserving headroom must not read '100% free' for a run whose spend
    lives in another process. Uses the process-default kernel, whose ledger the
    conftest redirects to a temp store."""
    k = J.kernel()
    monkeypatch.setattr(JobKernel, "_resolve_governance",
                        lambda self, jid: (_gov(token_budget=1_000), "test-agent"))
    _insert_job(k.ledger, "job-headroom", metrics={"total_tokens": 250})
    try:
        assert J.budget_fraction_used("job-headroom") == pytest.approx(0.25)
    finally:
        k.ledger.job_update("job-headroom", state=JobState.CANCELLED)
