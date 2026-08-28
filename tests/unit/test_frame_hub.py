"""FL-1a — frame hub: snapshot-then-tail semantics, detached from connections.

Hermetic: no DB, no routes, no timers — the hub is loop-local state and the
clock is injected. The FL-1b seam test (route actually consumes the hub) is
deliberately NOT here; it must live with the wiring so it fails while the hub
is importable but unconsumed.
"""
from __future__ import annotations

import asyncio

import pytest

from aughor.util.frame_hub import ConsumerLagged, FrameHub, RunExists


async def _collect(consumer, limit: int | None = None) -> list[str]:
    got: list[str] = []
    async for frame in consumer.tail():
        got.append(frame)
        if limit is not None and len(got) >= limit:
            break
    return got


@pytest.mark.anyio
async def test_snapshot_then_tail_then_close():
    hub = FrameHub()
    run = hub.open_run("r1")
    run.publish("a")
    run.publish("b")

    c = hub.attach("r1")
    assert c.snapshot == ["a", "b"]
    assert not c.closed

    task = asyncio.create_task(_collect(c))
    await asyncio.sleep(0)  # let the consumer park on its queue
    run.publish("c")
    run.close()
    assert await task == ["c"]
    assert hub.status("r1") == "closed"


@pytest.mark.anyio
async def test_coalesce_keeps_only_latest_per_channel():
    # REPLACE-semantic frames carry the full partial; the snapshot keeps the
    # latest per channel, at its arrival position, one-shots untouched.
    hub = FrameHub()
    key = lambda f: "narrative" if f.startswith("n:") else None
    run = hub.open_run("r1", coalesce=key)
    for f in ("n:he", "start", "n:hell", "n:hello"):
        run.publish(f)

    c = hub.attach("r1")
    assert c.snapshot == ["start", "n:hello"]


@pytest.mark.anyio
async def test_late_attach_after_close_gets_snapshot_and_error():
    hub = FrameHub()
    run = hub.open_run("r1")
    run.publish("a")
    run.close(error="boom")

    c = hub.attach("r1")
    assert c.snapshot == ["a"]
    assert c.closed and c.error == "boom"
    assert await _collect(c) == []  # tail of a closed run ends immediately


@pytest.mark.anyio
async def test_one_consumer_vanishing_does_not_affect_the_run():
    # The whole point of FL-1: a departed viewer must cost the run nothing.
    hub = FrameHub()
    run = hub.open_run("r1")
    gone = hub.attach("r1")
    stay = hub.attach("r1")
    hub.detach("r1", gone)

    run.publish("x")
    run.close()
    assert await _collect(stay) == ["x"]


@pytest.mark.anyio
async def test_lagged_consumer_is_told_to_reattach():
    hub = FrameHub()
    run = hub.open_run("r1")
    slow = hub.attach("r1", queue_size=2)
    for f in ("a", "b", "c", "d"):  # c overflows; d must not be delivered
        run.publish(f)

    with pytest.raises(ConsumerLagged):
        await _collect(slow)

    fresh = hub.attach("r1")  # repair path: a new snapshot is complete
    assert fresh.snapshot == ["a", "b", "c", "d"]


@pytest.mark.anyio
async def test_log_cap_truncates_snapshot_and_flags_it():
    hub = FrameHub()
    run = hub.open_run("r1", max_frames=3)
    for f in ("a", "b", "c", "d", "e"):
        run.publish(f)

    c = hub.attach("r1")
    assert c.snapshot == ["c", "d", "e"]
    assert c.truncated


@pytest.mark.anyio
async def test_closed_run_expires_after_ttl():
    now = [0.0]
    hub = FrameHub(clock=lambda: now[0])
    hub.open_run("r1", ttl_s=10).close()

    now[0] = 5.0
    assert hub.status("r1") == "closed"  # still resumable inside the TTL
    now[0] = 11.0
    assert hub.status("r1") is None
    with pytest.raises(KeyError):
        hub.attach("r1")


@pytest.mark.anyio
async def test_open_twice_live_raises_but_closed_id_can_reopen():
    hub = FrameHub()
    hub.open_run("r1")
    with pytest.raises(RunExists):
        hub.open_run("r1")

    hub.close_run("r1")
    run2 = hub.open_run("r1")  # a retry of the same investigation starts fresh
    run2.publish("fresh")
    assert hub.attach("r1").snapshot == ["fresh"]


@pytest.mark.anyio
async def test_straggler_publish_after_close_is_dropped():
    hub = FrameHub()
    run = hub.open_run("r1")
    run.close()
    run.publish("late")  # must not raise, must not appear
    assert hub.attach("r1").snapshot == []
