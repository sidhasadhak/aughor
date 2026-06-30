"""Tests for the LLM provider resilience layer (aughor/llm/provider.py):
per-endpoint concurrency semaphore + transient-error retry/backoff/deadline.

This is platform robustness — every Aughor LLM call goes through _run_resilient — so the contract
matters: retry throttle/transient, surface real failures immediately, never hold a slot while sleeping.
"""
from __future__ import annotations

import pytest

from aughor.llm import provider as P


class _Transient(Exception):
    status_code = 429


class _Fatal(Exception):
    pass


def test_is_transient_classification():
    assert P._is_transient(_Transient())                       # 429 status
    assert P._is_transient(Exception("Read timed out"))
    assert P._is_transient(Exception("429 Too Many Requests"))
    assert P._is_transient(Exception("upstream overloaded"))
    # real failures must NOT be retried
    assert not P._is_transient(_Fatal("validation error: missing field"))
    assert not P._is_transient(Exception("no such column: foo"))
    bad = Exception("bad request"); bad.status_code = 400
    assert not P._is_transient(bad)


def test_retries_transient_then_succeeds(monkeypatch):
    monkeypatch.setattr(P.time, "sleep", lambda *_: None)      # no real backoff in tests
    monkeypatch.setenv("AUGHOR_LLM_MAX_RETRIES", "3")
    calls = {"n": 0}
    def do():
        calls["n"] += 1
        if calls["n"] < 3:
            raise _Transient()
        return "ok"
    assert P._run_resilient(do, "u1") == "ok"
    assert calls["n"] == 3                                     # initial + 2 retries


def test_non_transient_raises_immediately(monkeypatch):
    monkeypatch.setattr(P.time, "sleep", lambda *_: None)
    calls = {"n": 0}
    def do():
        calls["n"] += 1
        raise _Fatal("bad sql")
    with pytest.raises(_Fatal):
        P._run_resilient(do, "u2")
    assert calls["n"] == 1                                     # no retry on real failure


def test_retries_bounded_by_max(monkeypatch):
    monkeypatch.setattr(P.time, "sleep", lambda *_: None)
    monkeypatch.setenv("AUGHOR_LLM_MAX_RETRIES", "2")
    calls = {"n": 0}
    def do():
        calls["n"] += 1
        raise _Transient()
    with pytest.raises(_Transient):
        P._run_resilient(do, "u3")
    assert calls["n"] == 3                                     # initial + exactly 2 retries


def test_semaphore_shared_per_base_url():
    a = P._semaphore_for("http://x")
    b = P._semaphore_for("http://x")
    c = P._semaphore_for("http://y")
    assert a is b and a is not c                               # one gate per endpoint


def test_success_path_calls_once(monkeypatch):
    monkeypatch.setattr(P.time, "sleep", lambda *_: None)
    calls = {"n": 0}
    def do():
        calls["n"] += 1
        return 42
    assert P._run_resilient(do, "u4") == 42 and calls["n"] == 1   # happy path unchanged
