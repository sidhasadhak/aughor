"""A job submitted from another event loop while every slot is taken waits for one, instead of dying unseen.

A step that needs an investigation's answer (the Daily Briefing's Slack post) drains it on its worker thread's own event
loop (`runners/investigation.py`). The cap on running jobs was an `asyncio.Semaphore`, which belongs to one loop: free, any
loop may take it; full, a second loop's `acquire` raises RuntimeError. That killed the job's task before it ran, so its row
stayed PENDING and the step waited on it forever. Automation ticks fill the cap for half a second a minute, so from
2026-10-30 the Daily Briefing never finished (measured 2026-11-03: last completed run 28 Oct).
"""
import asyncio
import threading

from aughor.kernel.jobs import JobKernel, JobState
from aughor.kernel.ledger import Ledger


def test_a_job_from_another_loop_waits_for_a_slot_and_then_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGHOR_MAX_CONCURRENT_JOBS", "1")
    seen: dict = {}

    async def main() -> None:
        k = JobKernel(Ledger(str(tmp_path / "jobs.db")))
        free, running = asyncio.Event(), asyncio.Event()

        async def holds_the_slot() -> None:
            running.set()
            await free.wait()

        await k.submit("automation", holds_the_slot)
        await running.wait()
        await k.submit("automation", holds_the_slot)      # waits on this loop, as a busy tick's jobs do
        await asyncio.sleep(0.05)

        def worker() -> None:
            async def on_its_own_loop() -> None:
                ran = asyncio.Event()

                async def the_investigation() -> None:
                    ran.set()

                job_id = await k.submit("investigation", the_investigation)
                task = k._tasks[job_id]
                await asyncio.sleep(0.2)
                seen["while_full"] = (task.done(), k.ledger.job_get(job_id)["state"])
                main_loop.call_soon_threadsafe(free.set)
                await asyncio.wait_for(ran.wait(), timeout=5)
                await asyncio.wait_for(task, timeout=5)
                seen["after"] = k.ledger.job_get(job_id)["state"]

            asyncio.run(on_its_own_loop())

        main_loop = asyncio.get_running_loop()
        thread = threading.Thread(target=lambda: seen.update(error=_caught(worker)))
        thread.start()
        while thread.is_alive():
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.05)

    asyncio.run(main())
    assert seen.get("error") is None, seen
    assert seen["while_full"] == (False, JobState.PENDING), "it died instead of waiting for a slot"
    assert seen["after"] == JobState.SUCCEEDED


def _caught(fn) -> "str | None":
    try:
        fn()
    except BaseException as exc:  # noqa: BLE001 — the test reports what the worker met
        return repr(exc)
    return None
