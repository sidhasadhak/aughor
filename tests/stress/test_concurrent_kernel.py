"""WCH-9 stress: the kernel under concurrency storms.

Scenarios 1/4/8 from the audit, at the kernel layer: racing submissions with
one idempotency key must collapse to ONE job; a create/cancel churn loop must
leak nothing; the supervisor must stay correct while jobs churn around it.
"""
import asyncio

import pytest

from aughor.kernel.jobs import JobKernel, JobState
from aughor.kernel.ledger import Ledger


@pytest.fixture()
def ledger(tmp_path):
    return Ledger(tmp_path / "system.db")


class TestSubmissionStorm:
    def test_racing_idempotent_submits_collapse_to_one(self, ledger):
        async def main():
            k = JobKernel(ledger)
            release = asyncio.Event()

            async def work():
                await release.wait()

            # 25 concurrent submits, same key — the manual-rebuild-races-Phase-8 class.
            ids = await asyncio.gather(*[
                k.submit("exploration", work, conn_id="c1", idempotency_key="explore:c1")
                for _ in range(25)
            ])
            release.set()
            while any(j in k._tasks for j in ids):
                await asyncio.sleep(0.01)
            return ids

        ids = asyncio.run(main())
        assert len(set(ids)) == 1, f"expected 1 job, got {len(set(ids))}"
        assert len(ledger.jobs_where(states=[JobState.SUCCEEDED])) == 1

    def test_distinct_scopes_do_not_collapse(self, ledger):
        async def main():
            k = JobKernel(ledger)

            async def work():
                pass

            ids = await asyncio.gather(*[
                k.submit("exploration", work, conn_id=f"c{i}",
                         idempotency_key=f"explore:c{i}")
                for i in range(10)
            ])
            while any(j in k._tasks for j in ids):
                await asyncio.sleep(0.01)
            return ids

        ids = asyncio.run(main())
        assert len(set(ids)) == 10


class TestChurn:
    def test_create_cancel_churn_leaks_nothing(self, ledger):
        """Scenario 8: repeated spawn+cancel cycles. Before K1, the task
        registries grew forever; the kernel must end the churn with zero live
        tasks and every job row in a terminal state."""
        async def main():
            k = JobKernel(ledger)
            for i in range(20):
                started = asyncio.Event()

                async def work(ev=started):
                    ev.set()
                    await asyncio.sleep(60)

                jid = await k.submit("exploration", work, conn_id="c1",
                                     canvas_id=f"cv{i}")
                await asyncio.wait_for(started.wait(), 5)
                k.cancel_scope(canvas_id=f"cv{i}")
                while jid in k._tasks:
                    await asyncio.sleep(0.01)
            return k

        k = asyncio.run(main())
        assert not k._tasks, f"leaked tasks: {list(k._tasks)}"
        states = {j["state"] for j in ledger.jobs_where()}
        assert states <= set(JobState.TERMINAL), f"non-terminal rows after churn: {states}"

    def test_supervisor_sweep_correct_amid_churn(self, ledger):
        """Stale rows are failed while live jobs keep running — under load."""
        async def main():
            k = JobKernel(ledger)
            # 5 stale orphan rows (dead process), 5 live jobs.
            for i in range(5):
                ledger.job_insert({
                    "id": f"dead{i}", "kind": "exploration", "conn_id": "c1",
                    "state": JobState.RUNNING, "attempt": 1,
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "started_at": "2026-01-01T00:00:00+00:00",
                    "heartbeat_at": "2026-01-01T00:00:00+00:00",
                })
            release = asyncio.Event()

            async def work():
                await release.wait()

            live = [await k.submit("exploration", work, conn_id="c2") for _ in range(5)]
            await asyncio.sleep(0.05)
            n = k.sweep_stale(stale_after=60)
            release.set()
            while any(j in k._tasks for j in live):
                await asyncio.sleep(0.01)
            return n, live

        n, live = asyncio.run(main())
        assert n == 5
        for jid in live:
            assert ledger.job_get(jid)["state"] == JobState.SUCCEEDED
