"""Per-stage timings reported in the response, because counters cannot measure a fleet.

Two production diagnoses stalled on this. `/dev/stats` counters are per-PROCESS and a
serverless deployment answers from many instances, so a read can land on an instance
that did none of the work: reading `store.schema_ddl.ran` around an 89-second schema
refresh showed no change at all. Timings returned in the SAME response come from the
instance that produced them.

The threading choice is load-bearing rather than incidental — the routes that need
this hand their work to `run_in_executor`, which does not carry a contextvar into the
worker thread, so collection is thread-local and started inside the worker.
"""
from __future__ import annotations

import threading
import time

from aughor.kernel.stage_timer import collect, record, stage


def test_a_stage_is_timed_when_someone_is_collecting():
    with collect() as stages:
        with stage("work"):
            time.sleep(0.02)
    assert "work" in stages and stages["work"] >= 0.02


def test_a_stage_outside_collection_is_a_no_op():
    """The hot path must pay nothing when nobody is diagnosing."""
    with stage("work"):        # must not raise, must not record anywhere
        pass
    with collect() as stages:
        pass
    assert stages == {}


def test_repeated_stages_accumulate():
    """A per-table stage should report the TOTAL across tables — that is the number
    worth having when asking where the time went."""
    with collect() as stages:
        for _ in range(3):
            with stage("per_table"):
                time.sleep(0.01)
    assert stages["per_table"] >= 0.03


def test_a_nested_collect_reuses_the_outer_one():
    """Instrumenting an inner helper must not silently discard the caller's stages."""
    with collect() as outer:
        with stage("a"):
            pass
        with collect() as inner:
            with stage("b"):
                pass
        assert inner is outer
    assert set(outer) == {"a", "b"}


def test_collection_is_per_thread():
    """Two requests served concurrently must not merge their timings."""
    seen: dict[str, dict] = {}

    def worker(name: str):
        with collect() as stages:
            with stage(name):
                time.sleep(0.02)
            seen[name] = dict(stages)

    ts = [threading.Thread(target=worker, args=(n,)) for n in ("t1", "t2")]
    for t in ts:
        t.start()
    for t in ts:
        t.join()

    assert set(seen["t1"]) == {"t1"}, f"t1 saw another thread's stages: {seen['t1']}"
    assert set(seen["t2"]) == {"t2"}


def test_an_exception_still_records_the_stage():
    """A stage that raised is exactly the one worth seeing the duration of."""
    with collect() as stages:
        try:
            with stage("boom"):
                raise RuntimeError("x")
        except RuntimeError:
            pass
    assert "boom" in stages


def test_record_adds_a_stage_measured_elsewhere():
    with collect() as stages:
        record("external", 1.5)
        record("external", 0.5)
    assert stages["external"] == 2.0
    record("ignored", 1.0)      # outside collection — no error, nothing kept
