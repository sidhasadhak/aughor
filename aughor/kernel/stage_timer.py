"""Per-stage wall-clock timings for one unit of work, reported IN its response.

WHY NOT THE STATS COUNTERS
---------------------------
`/dev/stats` is per-PROCESS and a serverless deployment answers from many instances,
so a diagnostic read can land on an instance that did none of the work. That is not
a hypothetical: reading `store.schema_ddl.ran` around an 89-second schema refresh
showed no change at all, because the two requests were served by different
instances. A counter cannot measure a fleet.

Returning timings in the SAME response ties them to the request that produced them,
whichever instance served it.

WHY THREAD-LOCAL AND NOT A CONTEXTVAR
--------------------------------------
The routes that need this hand their work to `loop.run_in_executor`, which does not
carry a context into the worker thread. Collection is therefore started INSIDE the
worker, where every stage then runs on one thread.

Cost when nobody is collecting: one `getattr` returning None per stage. The stages
below are seconds long in the case being diagnosed.
"""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager

_local = threading.local()


@contextmanager
def collect():
    """Collect stage timings for this block, on this thread.

    Yields the dict, filled as stages complete. A nested `collect()` reuses the
    outermost one rather than shadowing it, so instrumenting an inner helper cannot
    silently discard the caller's timings.
    """
    outer = getattr(_local, "stages", None)
    if outer is not None:
        yield outer
        return
    stages: dict[str, float] = {}
    _local.stages = stages
    try:
        yield stages
    finally:
        _local.stages = None


@contextmanager
def stage(name: str):
    """Time this block as ``name`` when someone is collecting; otherwise a no-op.

    Repeated entries ACCUMULATE — a per-table stage reports the total across tables,
    which is the number that matters when asking where the time went.
    """
    stages = getattr(_local, "stages", None)
    if stages is None:
        yield
        return
    started = time.perf_counter()
    try:
        yield
    finally:
        stages[name] = round(stages.get(name, 0.0) + (time.perf_counter() - started), 3)


def record(name: str, seconds: float) -> None:
    """Add a stage measured elsewhere. No-op when nobody is collecting."""
    stages = getattr(_local, "stages", None)
    if stages is not None:
        stages[name] = round(stages.get(name, 0.0) + seconds, 3)
