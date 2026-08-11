"""`/suggestions` stops paying for the model on every request.

The endpoint caches its 6 starter questions in the vector store, keyed by
(connection_id, schema fingerprint). But `vector_store.available()` reports
INSTALLATION, not liveness — its own docstring says it "says nothing about the
server being up" — and both call sites wrap the cache in `except Exception: pass`.
So a backend that is configured but down (a local Qdrant that is not running is the
ordinary case) made the cache silently stop caching, and EVERY request paid the
model. Measured on this machine: 42.8s of a 43.7s request.

These tests pin the two properties that fix costs: a repeat request must not reach
the model, and concurrent requests for the same schema must share one call rather
than each buying the identical answer against a 20-request/minute free tier.
"""
from __future__ import annotations

import threading
import time

import pytest

from aughor.semantic import suggestions_cache as sc


@pytest.fixture(autouse=True)
def clean_local():
    sc.local_clear()
    yield
    sc.local_clear()


def _six(tag: str = "q") -> list[dict]:
    return [{"text": f"{tag}{i}", "mode": "ask"} for i in range(6)]


# ── the process-local layer ───────────────────────────────────────────────────

def test_a_stored_entry_is_readable_without_the_backend(monkeypatch) -> None:
    """The whole point: with no persistent backend at all, a write still makes the
    next read a hit instead of another model call."""
    monkeypatch.setattr("aughor.semantic.vector_store.available", lambda: False)

    sc.store("c1", "fp1", _six())          # degrades quietly — nothing persisted
    assert sc.get_cached("c1", "fp1") == _six()


def test_the_local_write_happens_before_anything_that_can_raise(monkeypatch) -> None:
    """Ordering is the load-bearing detail, and the case that actually bites is a
    backend that is CONFIGURED but DOWN — then the persist raises rather than
    degrading. The caller swallows that, so if the local write came after the
    persist, a down backend would still mean a model call on every request.
    """
    def _boom(*a, **k):
        raise RuntimeError("qdrant is configured but not answering")

    monkeypatch.setattr("aughor.semantic.vector_store.available", lambda: True)
    monkeypatch.setattr("aughor.semantic.vector_store.ensure_collection", _boom)

    with pytest.raises(RuntimeError):
        sc.store("c1", "fp1", _six())

    assert sc.get_cached("c1", "fp1") == _six(), (
        "the local layer was written after the failing persist, so it never happened")


def test_a_different_schema_is_a_different_entry() -> None:
    sc._local_put(("c1", "fp1"), _six("a"))
    sc._local_put(("c1", "fp2"), _six("b"))
    assert sc.get_cached("c1", "fp1")[0]["text"] == "a0"
    assert sc.get_cached("c1", "fp2")[0]["text"] == "b0"


def test_a_different_connection_is_a_different_entry() -> None:
    sc._local_put(("c1", "fp1"), _six("a"))
    assert sc.get_cached("c2", "fp1") is None


def test_the_local_layer_is_bounded() -> None:
    """A long-lived process serving many connections must not grow without limit."""
    for i in range(sc._LOCAL_MAX + 10):
        sc._local_put(("c", f"fp{i}"), _six())
    assert sc.local_count() == sc._LOCAL_MAX


def test_the_bound_evicts_the_least_recently_used() -> None:
    for i in range(sc._LOCAL_MAX):
        sc._local_put(("c", f"fp{i}"), _six())
    sc.get_cached("c", "fp0")                      # touch the oldest
    sc._local_put(("c", "new"), _six())            # forces one eviction

    assert sc.get_cached("c", "fp0") is not None, "the touched entry was evicted"
    assert sc.get_cached("c", "fp1") is None, "the least-recently-used survived"


def test_a_returned_entry_cannot_be_mutated_through() -> None:
    """Callers hand this straight into a response payload."""
    sc._local_put(("c1", "fp1"), _six())
    got = sc.get_cached("c1", "fp1")
    got.append({"text": "injected", "mode": "ask"})
    assert len(sc.get_cached("c1", "fp1")) == 6


# ── the thundering-herd guard ─────────────────────────────────────────────────

def test_concurrent_requests_for_one_schema_share_a_single_computation() -> None:
    """Two tabs, or a reload, made two 42.8s model calls that could not hit each
    other's cache because neither had finished."""
    calls: list[int] = []
    lock = threading.Lock()

    def compute():
        with lock:
            calls.append(1)
        time.sleep(0.3)
        return _six()

    out: list = []
    threads = [threading.Thread(target=lambda: out.append(
        sc.compute_once("c1", "fp1", compute))) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(calls) == 1, f"{len(calls)} model calls for 5 concurrent requests"
    assert len(out) == 5 and all(r == _six() for r in out), "a follower got nothing"
    assert sc.inflight_count() == 0, "a leader was left registered"


def test_distinct_schemas_do_not_block_each_other() -> None:
    calls: list[str] = []
    lock = threading.Lock()

    def make(tag):
        def compute():
            with lock:
                calls.append(tag)
            time.sleep(0.2)
            return _six(tag)
        return compute

    threads = [threading.Thread(target=sc.compute_once, args=("c1", f"fp{i}", make(str(i))))
               for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(calls) == ["0", "1", "2"], "independent schemas were serialized"


def test_a_leader_that_raises_does_not_strand_followers() -> None:
    """A failed leader must release the key, or every later request for that schema
    waits the full timeout for a computation that will never come."""
    def boom():
        raise RuntimeError("the model refused")

    with pytest.raises(RuntimeError):
        sc.compute_once("c1", "fp1", boom)

    assert sc.inflight_count() == 0, "a failed leader stayed registered"
    assert sc.compute_once("c1", "fp1", lambda: _six()) == _six()


def test_a_leaders_result_is_published_before_followers_wake() -> None:
    """The follower reads the value out of the local layer, so the leader must put
    it there before setting the event — otherwise the follower recomputes."""
    started = threading.Event()
    calls: list[int] = []
    lock = threading.Lock()

    def compute():
        with lock:
            calls.append(1)
        started.set()
        time.sleep(0.3)
        return _six()

    leader = threading.Thread(target=sc.compute_once, args=("c1", "fp1", compute))
    leader.start()
    started.wait(timeout=5)

    got = sc.compute_once("c1", "fp1", compute)    # joins as a follower
    leader.join()

    assert got == _six()
    assert len(calls) == 1, "the follower recomputed instead of taking the result"
