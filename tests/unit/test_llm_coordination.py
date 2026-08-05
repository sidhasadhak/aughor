"""The coordination seam — and the defect it exists to close.

The provider's pacing, concurrency and quota-cooldown gates were module-level dicts:
correct for one process, silently wrong for many. The Vercel spike
(docs/VERCEL_PLATFORM_DESIGN_2026-08-05.md §3.5) drove five slices and Vercel spread
them over three cold plus two warm instances on its own, so "many" is the deployment
that plan asks for, not a hypothetical.

Two instances are simulated as two ``InProcessCoordinator`` objects, and a shared
backend as one object both callers hold. That is a faithful stand-in — the thing that
differs between the two deployments is precisely whether the state is one object or N —
and it needs no Redis to run in CI.

The pair of tests that matter are ``*_is_the_defect`` / ``*_is_the_fix``: the first
FAILS to hold the limit and asserts that it fails, so the seam is measured against a
demonstrated problem rather than an asserted one.
"""
from __future__ import annotations

import threading

from aughor.llm import coordination as C
from aughor.llm import provider as P

INTERVAL = 0.1          # 600 RPM — the spacing a declared limit would demand


# ── selection ────────────────────────────────────────────────────────────────

def test_inprocess_is_the_default():
    """Nothing changes for the single-process deployment unless it opts in."""
    C.set_default(None)
    assert isinstance(C.default(), C.InProcessCoordinator)


def test_unknown_backend_degrades_to_inprocess(monkeypatch):
    """A typo in a deployment env must not take the whole LLM path down — and the
    in-process gate is a SAFE fallback: it paces more conservatively than a shared
    one, never less."""
    C.set_default(None)
    monkeypatch.setenv(C.COORDINATOR_ENV, "redis-typo")
    assert isinstance(C.default(), C.InProcessCoordinator)


def test_inprocess_coordinator_satisfies_the_protocol():
    assert isinstance(C.InProcessCoordinator(), C.Coordinator)


# ── pacing across instances ──────────────────────────────────────────────────

def test_per_instance_pacing_is_the_defect():
    """Two instances each believe they are honouring the limit, so the endpoint sees
    double the declared rate. This is the current behaviour, asserted so the fix below
    is measured against a demonstrated problem."""
    a, b = C.InProcessCoordinator(), C.InProcessCoordinator()
    assert a.reserve("https://api.test", INTERVAL) == 0.0
    assert b.reserve("https://api.test", INTERVAL) == 0.0     # ← both go at once


def test_shared_pacing_is_the_fix():
    """One shared coordinator and the same two callers: the second is made to wait."""
    shared = C.InProcessCoordinator()
    assert shared.reserve("https://api.test", INTERVAL) == 0.0
    wait = shared.reserve("https://api.test", INTERVAL)
    assert 0.0 < wait <= INTERVAL


def test_reserve_returns_a_duration_not_a_timestamp():
    """The clock is part of the contract. A backend that leaked its own timestamps
    would have callers comparing unrelated timelines — ``time.monotonic()`` has a
    per-process epoch, so shared monotonic values silently produce NO pacing at all."""
    shared = C.InProcessCoordinator()
    shared.reserve("https://api.test", INTERVAL)
    wait = shared.reserve("https://api.test", INTERVAL)
    assert wait <= INTERVAL          # a timestamp would be ~1e5..1e9, not ≤ 0.1


def test_endpoints_are_paced_independently():
    """A saturated free endpoint must not throttle a paid one queued behind it."""
    shared = C.InProcessCoordinator()
    shared.reserve("https://free.test", INTERVAL)
    assert shared.reserve("https://paid.test", INTERVAL) == 0.0


def test_concurrent_callers_cannot_both_claim_one_slot():
    """The claim is atomic — two threads that both read 'clear' and then both called
    would be the burst the gate exists to prevent."""
    shared = C.InProcessCoordinator()
    granted: list[float] = []
    lock = threading.Lock()

    def worker():
        w = shared.reserve("https://api.test", INTERVAL)
        with lock:
            granted.append(w)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(granted) == 8
    assert sum(1 for g in granted if g == 0.0) == 1     # exactly one winner


# ── quota cooldown across instances ──────────────────────────────────────────

def test_per_instance_cooldown_reprobes_an_exhausted_backend():
    """The defect: what one instance learned, the others pay to rediscover."""
    a, b = C.InProcessCoordinator(), C.InProcessCoordinator()
    a.mark_cooldown("openrouter", 900.0)
    assert a.in_cooldown("openrouter")
    assert not b.in_cooldown("openrouter")        # ← b will probe it again

def test_shared_cooldown_is_learned_once():
    shared = C.InProcessCoordinator()
    shared.mark_cooldown("openrouter", 900.0)
    assert shared.in_cooldown("openrouter")
    assert not shared.in_cooldown("gemini")      # scoped to the backend that failed


# ── the seam is actually wired ───────────────────────────────────────────────

class _RecordingCoordinator:
    """A stand-in for a shared backend: records what the provider asks of it.

    Proves the provider CONSULTS the seam rather than keeping a private gate — the
    failure mode where both ends of a feature exist but the feature does not.
    """

    def __init__(self) -> None:
        self.reserved: list[tuple[str, float]] = []
        self.cooled: list[str] = []
        self.slots: list[tuple[str, int]] = []
        self._inner = C.InProcessCoordinator()

    def reserve(self, key: str, interval_s: float) -> float:
        self.reserved.append((key, interval_s))
        return 0.0                                # never make the suite wait

    def mark_cooldown(self, key: str, seconds: float) -> None:
        self.cooled.append(key)
        self._inner.mark_cooldown(key, seconds)

    def in_cooldown(self, key: str) -> bool:
        return self._inner.in_cooldown(key)

    def concurrency_slot(self, key: str, limit: int):
        self.slots.append((key, limit))
        return self._inner.concurrency_slot(key, limit)


def test_provider_pacing_goes_through_the_seam(monkeypatch):
    fake = _RecordingCoordinator()
    C.set_default(fake)
    try:
        monkeypatch.setenv("AUGHOR_LLM_RPM", "600")
        P._pace("https://api.test")
        assert fake.reserved == [("https://api.test", 0.1)]
    finally:
        C.set_default(None)


def test_provider_cooldown_goes_through_the_seam():
    fake = _RecordingCoordinator()
    C.set_default(fake)
    try:
        P._mark_quota_exhausted("openrouter")
        assert fake.cooled == ["openrouter"]
        assert P._in_quota_cooldown("openrouter")
    finally:
        C.set_default(None)


def test_provider_concurrency_goes_through_the_seam(monkeypatch):
    fake = _RecordingCoordinator()
    C.set_default(fake)
    try:
        monkeypatch.setenv("AUGHOR_LLM_MAX_CONCURRENCY", "4")
        with P._concurrency_slot("https://api.test"):
            pass
        assert fake.slots == [("https://api.test", 4)]
    finally:
        C.set_default(None)


def test_a_retry_reacquires_the_gate_rather_than_reentering_it(monkeypatch):
    """``_run_resilient`` loops on transient failures. The slot is a single-use context
    manager, so a retry must take a fresh one — re-entering a spent generator raises,
    and the raise would surface as a bogus LLM failure."""
    fake = _RecordingCoordinator()
    C.set_default(fake)
    try:
        monkeypatch.setattr(P.time, "sleep", lambda *_: None)
        monkeypatch.setenv("AUGHOR_LLM_MAX_RETRIES", "2")
        calls = {"n": 0}

        def do():
            calls["n"] += 1
            if calls["n"] < 3:
                # NOT a 429: a rate limit deliberately gets one retry rather than the
                # full ladder, which would stop this before it exercised a re-acquire.
                err = Exception("upstream overloaded")
                err.status_code = 503
                raise err
            return "ok"

        assert P._run_resilient(do, "https://api.test") == "ok"
        assert len(fake.slots) == calls["n"]      # one fresh slot per attempt
    finally:
        C.set_default(None)


# ── ratchet ──────────────────────────────────────────────────────────────────

def test_provider_keeps_no_private_coordination_state():
    """Guard the seam. One convenience dict at module scope in provider.py puts the
    per-instance defect straight back, and nothing else would notice — the gates all
    still 'work', just once per process.
    """
    import ast
    import pathlib

    src = pathlib.Path(P.__file__).read_text()
    offenders = []
    for node in ast.parse(src).body:            # MODULE level only
        targets = (node.targets if isinstance(node, ast.Assign)
                   else [node.target] if isinstance(node, ast.AnnAssign) else [])
        for t in targets:
            if not isinstance(t, ast.Name):
                continue
            name = t.id.lower()
            if any(w in name for w in ("semaphore", "last_call", "cooldown_at", "pace")):
                if isinstance(node.value, (ast.Dict, ast.List, ast.Set)):
                    offenders.append(t.id)
    assert not offenders, (
        f"coordination state back at module scope in provider.py: {offenders}. "
        "It belongs in aughor/llm/coordination.py so a shared backend can hold it.")
