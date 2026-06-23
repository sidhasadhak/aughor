"""Scoped cumulative-budget governance — the control plane's spend gate.

aughor enforced only *per-run* budgets (the kernel heartbeat kills one run over its
token/time cap). This locks in the missing *cumulative* layer: a scope (Org or agent)
that has spent over its windowed cap is refused at the **submit chokepoint**, before a
run is spawned — the per-run gate stays the in-flight backstop.

Properties pinned here:
- spend is reconciled-on-read from the metered job rows (no new write path);
- status is a *derived* incident, so raising a limit clears a breach automatically;
- the gate is fail-open and a **no-op until a policy is set** (byte-identical legacy
  behaviour); and — the load-bearing one — the real ``JobKernel.submit`` path refuses
  an over-budget run and records it FAILED without spawning the work.

No pytest-asyncio in the env — async tests drive the kernel inside ``asyncio.run``
(matching ``test_jobs.py``).
"""
from __future__ import annotations

import asyncio
import json

import pytest

from aughor.kernel.jobs import JobKernel, JobState
from aughor.kernel.ledger import Ledger
from aughor.platform import budget as bg


@pytest.fixture()
def ledger(tmp_path):
    return Ledger(tmp_path / "system.db")


def _finished_job(led: Ledger, *, kind: str, tokens: int, org_id: str = "default",
                  finished_at: str | None = None) -> str:
    """Insert a terminal job row carrying metered token spend (the source of truth
    spend reconciliation reads). Mirrors the kernel's own metrics flush."""
    import uuid
    from datetime import datetime, timezone
    jid = uuid.uuid4().hex[:12]
    led.job_insert({"id": jid, "kind": kind, "org_id": org_id, "attempt": 1,
                    "state": JobState.SUCCEEDED, "created_at": datetime.now(timezone.utc).isoformat()})
    led.job_update(jid, metrics=json.dumps({"total_tokens": tokens, "org_id": org_id}),
                   finished_at=finished_at or datetime.now(timezone.utc).isoformat())
    return jid


def run(coro):
    return asyncio.run(coro)


# ── policy store ──────────────────────────────────────────────────────────────


class TestPolicyStore:
    def test_set_get_roundtrip(self, ledger):
        bg.set_policy("org", "default", limit_tokens=1000, warn_percent=75, ledger=ledger)
        pol = bg.get_policy("org", "default", ledger=ledger)
        assert pol is not None
        assert pol.limit_tokens == 1000 and pol.warn_percent == 75 and pol.hard_stop is True

    def test_absent_policy_is_none(self, ledger):
        assert bg.get_policy("agent", "scout", ledger=ledger) is None

    def test_delete_restores_unbounded(self, ledger):
        bg.set_policy("agent", "scout", limit_tokens=500, ledger=ledger)
        bg.delete_policy("agent", "scout", ledger=ledger)
        assert bg.get_policy("agent", "scout", ledger=ledger) is None


# ── spend reconciliation (read-side) ─────────────────────────────────────────


class TestSpendReconcile:
    def test_org_spend_sums_all_kinds_in_org(self, ledger):
        _finished_job(ledger, kind="exploration", tokens=300)
        _finished_job(ledger, kind="investigation", tokens=700)
        assert bg.spend_tokens("org", "default", ledger=ledger) == 1000

    def test_org_spend_is_tenant_isolated(self, ledger):
        _finished_job(ledger, kind="exploration", tokens=300, org_id="default")
        _finished_job(ledger, kind="exploration", tokens=999, org_id="acme")
        assert bg.spend_tokens("org", "default", ledger=ledger) == 300
        assert bg.spend_tokens("org", "acme", ledger=ledger) == 999

    def test_agent_spend_is_per_charter(self, ledger):
        _finished_job(ledger, kind="exploration", tokens=300)     # scout
        _finished_job(ledger, kind="investigation", tokens=700)   # analyst
        assert bg.spend_tokens("agent", "scout", ledger=ledger) == 300
        assert bg.spend_tokens("agent", "analyst", ledger=ledger) == 700

    def test_lifetime_window_includes_old_runs_that_month_excludes(self, ledger):
        _finished_job(ledger, kind="exploration", tokens=500, finished_at="2020-01-01T00:00:00+00:00")
        assert bg.spend_tokens("org", "default", window="calendar_month", ledger=ledger) == 0
        assert bg.spend_tokens("org", "default", window="lifetime", ledger=ledger) == 500

    def test_rows_without_metrics_contribute_nothing(self, ledger):
        from datetime import datetime, timezone
        ledger.job_insert({"id": "nometrics", "kind": "exploration", "org_id": "default",
                           "attempt": 1, "state": JobState.RUNNING,
                           "created_at": datetime.now(timezone.utc).isoformat()})
        assert bg.spend_tokens("org", "default", ledger=ledger) == 0


# ── derived status + raise-clears-incident ───────────────────────────────────


class TestStatus:
    def test_unbounded_without_policy(self, ledger):
        _finished_job(ledger, kind="exploration", tokens=10_000)
        st = bg.status("org", "default", ledger=ledger)
        assert st.state == "unbounded" and st.limit_tokens is None and st.spent_tokens == 10_000

    def test_ok_warning_hardstop_thresholds(self, ledger):
        bg.set_policy("org", "default", limit_tokens=1000, warn_percent=80, ledger=ledger)
        assert bg.status("org", "default", ledger=ledger).state == "ok"          # 0
        _finished_job(ledger, kind="exploration", tokens=850)
        assert bg.status("org", "default", ledger=ledger).state == "warning"     # 85%
        _finished_job(ledger, kind="exploration", tokens=200)
        assert bg.status("org", "default", ledger=ledger).state == "hard_stop"   # 105%

    def test_raising_the_limit_clears_the_breach(self, ledger):
        bg.set_policy("org", "default", limit_tokens=1000, ledger=ledger)
        _finished_job(ledger, kind="exploration", tokens=1500)
        assert bg.status("org", "default", ledger=ledger).state == "hard_stop"
        bg.set_policy("org", "default", limit_tokens=5000, ledger=ledger)        # raise
        assert bg.status("org", "default", ledger=ledger).state == "ok"          # auto-cleared

    def test_hard_stop_disabled_warns_but_never_blocks(self, ledger):
        bg.set_policy("org", "default", limit_tokens=1000, hard_stop=False, ledger=ledger)
        _finished_job(ledger, kind="exploration", tokens=2000)
        assert bg.status("org", "default", ledger=ledger).state == "warning"
        assert bg.block_reason("org", "default", ledger=ledger) is None


# ── the preflight gate ───────────────────────────────────────────────────────


class TestPreflight:
    def test_org_cap_blocks_any_kind(self, ledger):
        bg.set_policy("org", "default", limit_tokens=1000, ledger=ledger)
        _finished_job(ledger, kind="exploration", tokens=1200)
        assert bg.preflight_block_for_kind("investigation", ledger=ledger) is not None

    def test_agent_cap_blocks_only_that_agent(self, ledger):
        bg.set_policy("agent", "scout", limit_tokens=500, ledger=ledger)
        _finished_job(ledger, kind="exploration", tokens=600)   # scout over
        assert bg.preflight_block_for_kind("exploration", ledger=ledger) is not None  # scout
        assert bg.preflight_block_for_kind("investigation", ledger=ledger) is None    # analyst free

    def test_no_policy_is_a_noop(self, ledger):
        _finished_job(ledger, kind="exploration", tokens=10_000_000)
        assert bg.preflight_block_for_kind("exploration", ledger=ledger) is None


# ── real-path proof: JobKernel.submit refuses an over-budget run ─────────────


class TestSubmitGate:
    def test_over_budget_submit_is_refused_and_audited(self, ledger):
        bg.set_policy("org", "default", limit_tokens=1000, ledger=ledger)
        _finished_job(ledger, kind="exploration", tokens=1500)   # org already over

        async def main():
            k = JobKernel(ledger)
            ran = asyncio.Event()

            async def work():
                ran.set()

            jid = await k.submit("exploration", work, conn_id="c1")
            await asyncio.sleep(0.05)
            return jid, ran.is_set(), k

        jid, did_run, k = run(main())
        job = ledger.job_get(jid)
        assert did_run is False                          # work never spawned
        assert job["state"] == JobState.FAILED
        assert "budget blocked" in (job.get("error") or "")
        assert jid not in k._tasks                       # no live task
        # auditable: a budget.blocked event was journaled
        assert any(e["kind"] == "budget.blocked" for e in ledger.events(job_id=jid))

    def test_under_budget_submit_runs_normally(self, ledger):
        bg.set_policy("org", "default", limit_tokens=1_000_000, ledger=ledger)

        async def main():
            k = JobKernel(ledger)
            ran = asyncio.Event()

            async def work():
                ran.set()

            jid = await k.submit("exploration", work, conn_id="c1")
            await asyncio.wait_for(ran.wait(), 5)
            while jid in k._tasks:
                await asyncio.sleep(0.01)
            return jid

        jid = run(main())
        assert ledger.job_get(jid)["state"] == JobState.SUCCEEDED

    def test_no_policy_leaves_submit_behaviour_identical(self, ledger):
        async def main():
            k = JobKernel(ledger)
            ran = asyncio.Event()

            async def work():
                ran.set()

            jid = await k.submit("exploration", work)
            await asyncio.wait_for(ran.wait(), 5)
            while jid in k._tasks:
                await asyncio.sleep(0.01)
            return jid

        jid = run(main())
        assert ledger.job_get(jid)["state"] == JobState.SUCCEEDED

    def test_raising_the_budget_unblocks_the_next_submit(self, ledger):
        bg.set_policy("org", "default", limit_tokens=1000, ledger=ledger)
        _finished_job(ledger, kind="exploration", tokens=1500)

        async def submit_once():
            k = JobKernel(ledger)
            ran = asyncio.Event()

            async def work():
                ran.set()

            jid = await k.submit("exploration", work)
            await asyncio.sleep(0.05)
            return jid, ran, k

        jid1, ran1, _ = run(submit_once())
        assert ledger.job_get(jid1)["state"] == JobState.FAILED   # blocked

        bg.set_policy("org", "default", limit_tokens=100_000, ledger=ledger)  # raise

        async def submit_after_raise():
            k = JobKernel(ledger)
            ran = asyncio.Event()

            async def work():
                ran.set()

            jid = await k.submit("exploration", work)
            await asyncio.wait_for(ran.wait(), 5)
            while jid in k._tasks:
                await asyncio.sleep(0.01)
            return jid

        jid2 = run(submit_after_raise())
        assert ledger.job_get(jid2)["state"] == JobState.SUCCEEDED
