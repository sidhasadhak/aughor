"""The work-dispatch seam: in-process default proven against the real kernel.

No pytest-asyncio in the env — each test drives the kernel inside asyncio.run.
"""
from __future__ import annotations

import asyncio

import pytest

from aughor.kernel import queue as Q
from aughor.kernel.jobs import JobState, kernel
from aughor.kernel import jobs as J


@pytest.fixture(autouse=True)
def _fresh_queue():
    Q.set_default(None)
    yield
    Q.set_default(None)


def test_inprocess_is_the_default(monkeypatch):
    monkeypatch.delenv(Q.QUEUE_ENV, raising=False)
    assert isinstance(Q.default(), Q.InProcessQueue)
    assert isinstance(Q.default(), Q.WorkQueue)          # satisfies the Protocol


def test_unknown_backend_degrades_to_inprocess(monkeypatch):
    monkeypatch.setenv(Q.QUEUE_ENV, "qstash-typo")
    assert isinstance(Q.default(), Q.InProcessQueue)


def test_dispatch_runs_the_registered_runner_through_the_kernel(monkeypatch):
    """A dispatch is a supervised kernel job: the runner gets the payload, the job
    reaches SUCCEEDED, and the payload travelled as a REFERENCE (plain dict)."""
    ran: list[dict] = []

    async def runner(payload):
        ran.append(payload)

    Q.register_runner("probe_work", runner)

    async def main():
        monkeypatch.setattr(J, "_main_loop", asyncio.get_running_loop())
        jid = await asyncio.get_running_loop().run_in_executor(
            None, lambda: Q.default().dispatch(
                "probe_work", {"store_key": "c1__main"}, conn_id="c1",
                idempotency_key="probe-1"))
        for _ in range(200):
            row = kernel().ledger.job_get(jid)
            if row and row["state"] in (JobState.SUCCEEDED, JobState.FAILED):
                return jid, row
            await asyncio.sleep(0.02)
        pytest.fail("dispatched job never finished")

    jid, row = asyncio.run(main())
    assert row["state"] == JobState.SUCCEEDED
    assert ran == [{"store_key": "c1__main"}]


def test_dispatch_without_a_loop_declines_instead_of_hanging(monkeypatch):
    """No running main loop (a unit test, pre-startup) → None, so the caller runs
    the work inline — the same decline contract submit_scheduled_tick has."""
    monkeypatch.setattr(J, "_main_loop", None)
    assert Q.default().dispatch("probe_work", {}) is None


def test_unregistered_kind_fails_the_job_not_the_dispatcher(monkeypatch):
    """Dispatching a kind nobody registered must surface as a FAILED job with the
    reason — not an exception in the dispatching request path."""
    async def main():
        monkeypatch.setattr(J, "_main_loop", asyncio.get_running_loop())
        jid = await asyncio.get_running_loop().run_in_executor(
            None, lambda: Q.default().dispatch("nobody_registered_this", {}))
        for _ in range(200):
            row = kernel().ledger.job_get(jid)
            if row and row["state"] in (JobState.SUCCEEDED, JobState.FAILED):
                return row
            await asyncio.sleep(0.02)
        pytest.fail("job never finished")

    row = asyncio.run(main())
    assert row["state"] == JobState.FAILED
    assert "no runner registered" in (row.get("error") or "")
