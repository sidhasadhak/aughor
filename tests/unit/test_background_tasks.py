"""Background tasks that outlive the request that started them.

`asyncio.create_task` returns the only strong reference to its task; the stdlib docs say
to keep it, or the task can be garbage-collected part-way through and vanish without
finishing and without raising. Every fire-and-forget kick in the routers — exploration,
the birth rite, the two syncs — dropped that reference.

Keeping it buys a second thing: somewhere to cancel from. A kick started inside one test
kept running after it, and its doc-tree write landed in a later test's fake vector store.
"""
from __future__ import annotations

import asyncio

from aughor.kernel.concurrency import cancel_background, pending_background, spawn


def test_a_spawned_task_is_referenced_even_when_the_caller_keeps_nothing():
    """The whole point: the registry IS the reference the caller threw away."""
    seen = {}

    async def _main():
        async def _work():
            await asyncio.sleep(0.05)
            seen["ran"] = True

        spawn(_work(), name="probe")          # return value deliberately discarded
        assert [t.get_name() for t in pending_background()] == ["probe"]
        await asyncio.sleep(0.2)
        return None

    asyncio.run(_main())
    assert seen.get("ran") is True


def test_a_finished_task_leaves_the_registry():
    """Otherwise this grows for the life of the process and `pending` stops meaning it."""
    async def _main():
        async def _work():
            return None

        spawn(_work(), name="brief")
        await asyncio.sleep(0.05)
        assert pending_background() == []

    asyncio.run(_main())


def test_cancel_ends_what_a_test_started():
    """A kick that outlives its test is the leak; this is the drain conftest calls."""
    state = {}

    async def _main():
        async def _forever():
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                state["cancelled"] = True
                raise

        spawn(_forever(), name="long")
        assert len(pending_background()) == 1

        assert cancel_background() == 1
        await asyncio.sleep(0.05)
        assert pending_background() == []

    asyncio.run(_main())
    assert state.get("cancelled") is True


def test_cancelling_nothing_is_not_an_error():
    """The autouse drain runs after every test in the suite, and almost always to no work."""
    assert cancel_background() == 0
