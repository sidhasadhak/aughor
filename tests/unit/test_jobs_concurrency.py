"""K1 — user-initiated jobs are bounded by AUGHOR_MAX_CONCURRENT_JOBS so a
/investigate loop can't exhaust the single process (AUDIT_2026-06-27.md #4).
Background explorers are exempt (idempotency-bounded per connection) and must
still run while user jobs are saturated.

No pytest-asyncio in the env — drive the kernel inside asyncio.run.
"""
import asyncio

import pytest

from aughor.kernel.jobs import JobKernel, JobState


@pytest.fixture()
def ledger(tmp_path):
    from aughor.kernel.ledger import Ledger
    return Ledger(tmp_path / "system.db")


def run(coro):
    return asyncio.run(coro)


def test_bounded_kind_respects_the_cap(ledger, monkeypatch):
    monkeypatch.setenv("AUGHOR_MAX_CONCURRENT_JOBS", "2")

    async def main():
        k = JobKernel(ledger)
        release = asyncio.Event()
        running = []

        def make_work(i):
            async def work():
                running.append(i)
                await release.wait()
            return work

        ids = [await k.submit("investigation", make_work(i), conn_id=f"c{i}") for i in range(5)]
        # Let the loop schedule the gated tasks.
        await asyncio.sleep(0.05)
        # Only the cap may be RUNNING; the rest sit PENDING behind the semaphore.
        assert len(running) == 2
        states = [ledger.job_get(j)["state"] for j in ids]
        assert states.count(JobState.RUNNING) == 2
        assert states.count(JobState.PENDING) == 3

        release.set()
        for j in ids:
            while j in k._tasks:
                await asyncio.sleep(0.01)
        return ids

    ids = run(main())
    assert all(ledger.job_get(j)["state"] == JobState.SUCCEEDED for j in ids)


def test_exploration_is_exempt_from_the_cap(ledger, monkeypatch):
    monkeypatch.setenv("AUGHOR_MAX_CONCURRENT_JOBS", "1")

    async def main():
        k = JobKernel(ledger)
        release = asyncio.Event()
        running = []

        def make_work(i):
            async def work():
                running.append(i)
                await release.wait()
            return work

        # Distinct idempotency keys so they don't collapse into one job.
        for i in range(4):
            await k.submit("exploration", make_work(i), conn_id=f"c{i}",
                           idempotency_key=f"explore:{i}")
        await asyncio.sleep(0.05)
        # All four run despite the cap of 1 — exploration is unbounded.
        assert len(running) == 4
        release.set()
        while k._tasks:
            await asyncio.sleep(0.01)

    run(main())


def test_queued_job_cancel_closes_the_row(ledger, monkeypatch):
    monkeypatch.setenv("AUGHOR_MAX_CONCURRENT_JOBS", "1")

    async def main():
        k = JobKernel(ledger)
        release = asyncio.Event()

        async def blocker():
            await release.wait()

        running_id = await k.submit("investigation", blocker, conn_id="c0")
        queued_id = await k.submit("investigation", blocker, conn_id="c1")
        await asyncio.sleep(0.05)
        assert ledger.job_get(queued_id)["state"] == JobState.PENDING

        # Cancel the still-queued job — it must reach a terminal state, not leak.
        k.cancel(queued_id)
        await asyncio.sleep(0.02)
        assert ledger.job_get(queued_id)["state"] == JobState.CANCELLED

        release.set()
        while k._tasks:
            await asyncio.sleep(0.01)
        return running_id

    rid = run(main())
    assert ledger.job_get(rid)["state"] == JobState.SUCCEEDED


def test_default_cap_when_env_unset(monkeypatch):
    monkeypatch.delenv("AUGHOR_MAX_CONCURRENT_JOBS", raising=False)
    from aughor.kernel.jobs import _max_concurrent_jobs
    assert _max_concurrent_jobs() == 8
