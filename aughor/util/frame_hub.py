"""FL-1a — the frame hub: a run's SSE frames, detached from any one connection.

Today the SSE generator IS the run: Starlette cancels it on client disconnect,
and the stream's finally-reconcile marks the investigation failed — a browser
refresh mid-deep-run destroys the run (routers/investigations.py, the
orphan-reconcile comment). The hub is the seam that breaks that identity: a
producer publishes each frame once; any number of consumers attach, each
receiving a SNAPSHOT of everything already emitted followed by the live tail.
The snapshot is the contract, the tail an optimization — a consumer that falls
behind is told to re-attach (ConsumerLagged) rather than queue unboundedly.

Deliberately in-memory and loop-local. The API is one process (run without
--reload), and a run does not survive the process today either; nothing here
touches data/ (one writer per data/). Backend partials are REPLACE-semantic —
each carries the full partial so far — so a caller-supplied `coalesce` key
collapses those channels to their latest frame: a resumed client sees exactly
what a connected one would, without replaying token history.

NOT wired to any route yet. FL-1b consumes this from the run producer and the
resume endpoint; its seam test must fail while this module is importable but
unconsumed.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import AsyncIterator, Callable, Optional


class RunExists(Exception):
    """open_run() for an id that is still live."""


class ConsumerLagged(Exception):
    """This consumer fell behind and its tail is no longer contiguous with the
    snapshot it was handed; re-attach for a fresh snapshot."""


_EOS = object()  # end-of-stream sentinel on consumer queues


@dataclass
class _Consumer:
    queue: "asyncio.Queue[object]"
    lagged: bool = False


@dataclass
class _Run:
    coalesce: Optional[Callable[[str], Optional[str]]]
    max_frames: int
    ttl_s: float
    # ordered (channel_key | None, frame); a keyed publish replaces its prior
    # entry and moves to the end — arrival order, not first-seen order.
    log: list[tuple[Optional[str], str]] = field(default_factory=list)
    consumers: list[_Consumer] = field(default_factory=list)
    closed: bool = False
    error: Optional[str] = None
    closed_at: Optional[float] = None
    truncated: bool = False


class RunHandle:
    """Producer side of one run. publish() and close() only; loop-affine."""

    def __init__(self, hub: "FrameHub", run_id: str):
        self._hub = hub
        self._run_id = run_id

    def publish(self, frame: str) -> None:
        self._hub._publish(self._run_id, frame)

    def close(self, error: Optional[str] = None) -> None:
        self._hub._close(self._run_id, error)


class Consumer:
    """One attached view: `snapshot` (frames up to attach) then `tail()`."""

    def __init__(self, snapshot: list[str], truncated: bool, closed: bool,
                 error: Optional[str], entry: Optional[_Consumer]):
        self.snapshot = snapshot
        self.truncated = truncated
        self.closed = closed
        self.error = error
        self._entry = entry

    async def tail(self) -> AsyncIterator[str]:
        """Live frames after the snapshot; ends when the run closes. Raises
        ConsumerLagged if the producer had to drop frames for this consumer."""
        if self._entry is None:  # attached after close: snapshot is everything
            return
        while True:
            item = await self._entry.queue.get()
            if item is _EOS:
                if self._entry.lagged:
                    raise ConsumerLagged()
                return
            yield item  # type: ignore[misc]


class FrameHub:
    """All live and recently-closed runs. One instance per process (see hub())."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic):
        self._runs: dict[str, _Run] = {}
        self._clock = clock

    # ── producer side ──────────────────────────────────────────────────────
    def open_run(self, run_id: str, *,
                 coalesce: Optional[Callable[[str], Optional[str]]] = None,
                 max_frames: int = 2000, ttl_s: float = 600.0) -> RunHandle:
        self._purge()
        existing = self._runs.get(run_id)
        if existing is not None and not existing.closed:
            raise RunExists(run_id)
        # Re-opening a closed id (retry of the same investigation) starts fresh.
        self._runs[run_id] = _Run(coalesce=coalesce, max_frames=max_frames,
                                  ttl_s=ttl_s)
        return RunHandle(self, run_id)

    def _publish(self, run_id: str, frame: str) -> None:
        run = self._runs.get(run_id)
        if run is None or run.closed:
            return  # a straggler frame after close is dropped, not an error
        key = run.coalesce(frame) if run.coalesce else None
        if key is not None:
            run.log = [(k, f) for (k, f) in run.log if k != key]
        run.log.append((key, frame))
        if len(run.log) > run.max_frames:
            run.log = run.log[-run.max_frames:]
            run.truncated = True
        for c in run.consumers:
            if c.lagged:
                continue
            try:
                c.queue.put_nowait(frame)
            except asyncio.QueueFull:
                # Drop-and-repair: stop delivering to this consumer and let its
                # tail() end in ConsumerLagged so the caller re-attaches for a
                # fresh snapshot instead of us buffering without bound. The
                # queue is full, so evict one frame to guarantee EOS fits —
                # its tail is no longer contiguous either way.
                c.lagged = True
                try:
                    c.queue.get_nowait()
                except asyncio.QueueEmpty as exc:
                    from aughor.kernel.errors import tolerate
                    tolerate(exc, "a consumer drained its full queue in the race window; "
                                  "EOS fits without the eviction", counter="frame_hub.evict_race")
                c.queue.put_nowait(_EOS)

    def _close(self, run_id: str, error: Optional[str]) -> None:
        run = self._runs.get(run_id)
        if run is None or run.closed:
            return
        run.closed = True
        run.error = error
        run.closed_at = self._clock()
        for c in run.consumers:
            try:
                c.queue.put_nowait(_EOS)
            except asyncio.QueueFull:
                # Evict one frame so EOS always fits — otherwise a full, slow
                # consumer drains its queue and then waits forever.
                c.lagged = True
                try:
                    c.queue.get_nowait()
                except asyncio.QueueEmpty as exc:
                    from aughor.kernel.errors import tolerate
                    tolerate(exc, "a consumer drained its full queue in the race window; "
                                  "EOS fits without the eviction", counter="frame_hub.evict_race")
                c.queue.put_nowait(_EOS)
        run.consumers = []

    # ── consumer side ──────────────────────────────────────────────────────
    def attach(self, run_id: str, *, queue_size: int = 256) -> Consumer:
        self._purge()
        run = self._runs.get(run_id)
        if run is None:
            raise KeyError(run_id)
        snapshot = [f for (_k, f) in run.log]
        if run.closed:
            return Consumer(snapshot, run.truncated, True, run.error, None)
        entry = _Consumer(queue=asyncio.Queue(maxsize=queue_size))
        run.consumers.append(entry)
        return Consumer(snapshot, run.truncated, False, run.error, entry)

    def close_run(self, run_id: str, error: Optional[str] = None) -> None:
        """Close from outside the producer — e.g. superseding a stale run when a
        conversation starts its next turn. Same semantics as RunHandle.close()."""
        self._close(run_id, error)

    def detach(self, run_id: str, consumer: Consumer) -> None:
        """Optional early-release; a vanished consumer only costs its queue."""
        run = self._runs.get(run_id)
        if run is not None and consumer._entry is not None:
            run.consumers = [c for c in run.consumers if c is not consumer._entry]

    def status(self, run_id: str) -> Optional[str]:
        self._purge()
        run = self._runs.get(run_id)
        if run is None:
            return None
        return "closed" if run.closed else "live"

    # ── housekeeping ───────────────────────────────────────────────────────
    def _purge(self) -> None:
        # No background timer: purge on every open/attach/status keeps expiry
        # deterministic and the module timer-free (test- and shutdown-friendly).
        now = self._clock()
        dead = [rid for rid, r in self._runs.items()
                if r.closed and r.closed_at is not None
                and now - r.closed_at > r.ttl_s]
        for rid in dead:
            del self._runs[rid]


_hub: Optional[FrameHub] = None


def hub() -> FrameHub:
    """Process-wide hub. Import-time side-effect free; first call constructs."""
    global _hub
    if _hub is None:
        _hub = FrameHub()
    return _hub
