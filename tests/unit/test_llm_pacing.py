"""The request-rate gate — Wave L2.

E4 guards the daily request BUDGET but nothing guarded the RATE, so a measured grid
burst into the free tier's 20 RPM cap, and every 429 was recorded as a case failure.
A run that trips the limiter measures the limiter.
"""
from __future__ import annotations

import threading
import time

from aughor.llm import provider as P


def _reset():
    with P._PACE_LOCK:
        P._LAST_CALL_AT.clear()


def test_pacing_is_off_by_default(monkeypatch):
    """An interactive answer must not be slowed for a limit it will never approach."""
    _reset()
    monkeypatch.delenv("AUGHOR_LLM_RPM", raising=False)
    start = time.monotonic()
    for _ in range(5):
        P._pace("https://example.test")
    assert time.monotonic() - start < 0.05


def test_calls_are_spaced_when_an_rpm_is_declared(monkeypatch):
    _reset()
    monkeypatch.setenv("AUGHOR_LLM_RPM", "600")      # 0.1s apart
    start = time.monotonic()
    for _ in range(3):
        P._pace("https://example.test")
    # first is free, then two waits of ~0.1s
    assert time.monotonic() - start >= 0.18


def test_endpoints_are_paced_independently(monkeypatch):
    """A slow free endpoint must not throttle a paid one behind it."""
    _reset()
    monkeypatch.setenv("AUGHOR_LLM_RPM", "600")
    P._pace("https://a.test")
    start = time.monotonic()
    P._pace("https://b.test")                        # different key ⇒ no wait
    assert time.monotonic() - start < 0.05


def test_concurrent_callers_cannot_both_claim_one_slot(monkeypatch):
    """Two threads that both read 'clear' and then both called would be the burst this
    exists to prevent — the slot is claimed inside the lock."""
    _reset()
    monkeypatch.setenv("AUGHOR_LLM_RPM", "600")
    P._pace("https://example.test")                  # consume the free first slot

    done: list[float] = []

    def worker():
        P._pace("https://example.test")
        done.append(time.monotonic())

    start = time.monotonic()
    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(done) == 2
    # serialised: the second cannot land in the first's interval
    assert max(done) - start >= 0.18
