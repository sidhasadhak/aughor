"""K1 Job Kernel invariants — supervised state machines over background work.

These lock in the properties that kill the orphaned-state class structurally:
every job reaches a terminal state with a reason, restarts fail-and-resume
orphans instead of forgetting them, idempotency collapses double-submits, and
deleting an owner cancels its jobs.

No pytest-asyncio in the env — each test drives the kernel inside asyncio.run.
"""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from aughor.kernel.jobs import JobKernel, JobState
from aughor.kernel.ledger import Ledger


@pytest.fixture()
def ledger(tmp_path):
    return Ledger(tmp_path / "system.db")


def run(coro):
    return asyncio.run(coro)


class TestLifecycle:
    def test_success_path(self, ledger):
        async def main():
            k = JobKernel(ledger)
            done = asyncio.Event()

            async def work():
                done.set()

            jid = await k.submit("exploration", work, conn_id="c1")
            await asyncio.wait_for(done.wait(), 5)
            while jid in k._tasks:
                await asyncio.sleep(0.01)
            return jid

        jid = run(main())
        job = ledger.job_get(jid)
        assert job["state"] == JobState.SUCCEEDED
        assert job["started_at"] and job["finished_at"]
        states = [e["payload"]["state"] for e in ledger.events(kind="job.state")]
        assert states[0] == JobState.SUCCEEDED          # newest first
        assert JobState.PENDING in states and JobState.RUNNING in states

    def test_failure_records_error(self, ledger):
        async def main():
            k = JobKernel(ledger)

            async def work():
                raise RuntimeError("boom: the DB went away")

            jid = await k.submit("exploration", work, conn_id="c1")
            while jid in k._tasks:
                await asyncio.sleep(0.01)
            return jid

        jid = run(main())
        job = ledger.job_get(jid)
        assert job["state"] == JobState.FAILED
        assert "boom" in job["error"]

    def test_cancel(self, ledger):
        async def main():
            k = JobKernel(ledger)
            started = asyncio.Event()

            async def work():
                started.set()
                await asyncio.sleep(60)

            jid = await k.submit("exploration", work, conn_id="c1")
            await asyncio.wait_for(started.wait(), 5)
            assert k.cancel(jid)
            while jid in k._tasks:
                await asyncio.sleep(0.01)
            return jid

        jid = run(main())
        assert ledger.job_get(jid)["state"] == JobState.CANCELLED

    def test_on_finish_hook_receives_final_state(self, ledger):
        seen = {}

        async def main():
            k = JobKernel(ledger)

            async def work():
                pass

            jid = await k.submit("x", work, on_finish=lambda j, s: seen.update({j: s}))
            while jid in k._tasks:
                await asyncio.sleep(0.01)
            return jid

        jid = run(main())
        assert seen == {jid: JobState.SUCCEEDED}


class TestIdempotency:
    def test_active_key_collapses_to_same_job(self, ledger):
        async def main():
            k = JobKernel(ledger)
            release = asyncio.Event()

            async def work():
                await release.wait()

            j1 = await k.submit("exploration", work, idempotency_key="explore:c1")
            j2 = await k.submit("exploration", work, idempotency_key="explore:c1")
            release.set()
            while j1 in k._tasks:
                await asyncio.sleep(0.01)
            return j1, j2

        j1, j2 = run(main())
        assert j1 == j2

    def test_terminal_key_allows_resubmit(self, ledger):
        async def main():
            k = JobKernel(ledger)

            async def work():
                pass

            j1 = await k.submit("exploration", work, idempotency_key="explore:c1")
            while j1 in k._tasks:
                await asyncio.sleep(0.01)
            j2 = await k.submit("exploration", work, idempotency_key="explore:c1")
            while j2 in k._tasks:
                await asyncio.sleep(0.01)
            return j1, j2

        j1, j2 = run(main())
        assert j1 != j2


class TestScopeCancellation:
    def test_cancel_scope_by_canvas(self, ledger):
        async def main():
            k = JobKernel(ledger)
            started = asyncio.Event()

            async def work():
                started.set()
                await asyncio.sleep(60)

            jid = await k.submit("exploration", work, conn_id="c1", canvas_id="cv1")
            await asyncio.wait_for(started.wait(), 5)
            n = k.cancel_scope(canvas_id="cv1")
            while jid in k._tasks:
                await asyncio.sleep(0.01)
            return jid, n

        jid, n = run(main())
        assert n == 1
        assert ledger.job_get(jid)["state"] == JobState.CANCELLED

    def test_connection_scope_covers_its_canvas_jobs(self, ledger):
        async def main():
            k = JobKernel(ledger)
            started = asyncio.Event()

            async def work():
                started.set()
                await asyncio.sleep(60)

            jid = await k.submit("exploration", work, conn_id="c1", canvas_id="cv1")
            await asyncio.wait_for(started.wait(), 5)
            n = k.cancel_scope(conn_id="c1")
            while jid in k._tasks:
                await asyncio.sleep(0.01)
            return jid, n

        jid, n = run(main())
        assert n >= 1
        assert ledger.job_get(jid)["state"] == JobState.CANCELLED


class TestOrphanRecovery:
    def _orphan_row(self, ledger, *, state=JobState.RUNNING, kind="exploration",
                    conn_id="c1", canvas_id=None, hb_age_s=0):
        """Simulate a row left behind by a dead process."""
        hb = (datetime.now(timezone.utc) - timedelta(seconds=hb_age_s)).isoformat()
        ledger.job_insert({
            "id": f"dead-{state}-{hb_age_s}", "kind": kind, "conn_id": conn_id,
            "canvas_id": canvas_id, "state": state, "payload": None,
            "idempotency_key": None, "attempt": 1,
            "created_at": hb, "started_at": hb, "heartbeat_at": hb,
        })
        return f"dead-{state}-{hb_age_s}"

    def test_boot_recovery_fails_orphans_and_returns_explorations(self, ledger):
        k = JobKernel(ledger)
        jid = self._orphan_row(ledger)
        other = self._orphan_row(ledger, kind="brief_delivery", hb_age_s=1)
        resumable = k.boot_recovery()
        assert ledger.job_get(jid)["state"] == JobState.FAILED
        assert "server restart" in ledger.job_get(jid)["error"]
        assert ledger.job_get(other)["state"] == JobState.FAILED
        assert [j["id"] for j in resumable] == [jid]     # only explorations
        # Idempotent: a clean second pass finds nothing
        assert k.boot_recovery() == []

    def test_sweep_stale_fails_only_stale_taskless_jobs(self, ledger):
        k = JobKernel(ledger)
        stale = self._orphan_row(ledger, hb_age_s=600)
        fresh = self._orphan_row(ledger, hb_age_s=5)
        n = k.sweep_stale(stale_after=120)
        assert n == 1
        assert ledger.job_get(stale)["state"] == JobState.FAILED
        assert "stale heartbeat" in ledger.job_get(stale)["error"]
        assert ledger.job_get(fresh)["state"] == JobState.RUNNING

    def test_sweep_spares_jobs_with_live_tasks(self, ledger):
        async def main():
            k = JobKernel(ledger)
            started = asyncio.Event()

            async def work():
                started.set()
                await asyncio.sleep(60)

            jid = await k.submit("exploration", work, conn_id="c1")
            await asyncio.wait_for(started.wait(), 5)
            # Make the heartbeat look ancient — but the task is alive, so the
            # sweep must NOT kill it.
            ledger.job_update(jid, heartbeat_at="2000-01-01T00:00:00+00:00")
            n = k.sweep_stale(stale_after=1)
            k.cancel(jid)
            while jid in k._tasks:
                await asyncio.sleep(0.01)
            return n

        assert run(main()) == 0


class TestTransitionGuard:
    def test_illegal_transition_ignored(self, ledger):
        k = JobKernel(ledger)
        ledger.job_insert({
            "id": "j1", "kind": "x", "state": JobState.SUCCEEDED,
            "attempt": 1, "created_at": "2026-01-01T00:00:00+00:00",
        })
        assert not k._transition("j1", JobState.RUNNING)
        assert ledger.job_get("j1")["state"] == JobState.SUCCEEDED
