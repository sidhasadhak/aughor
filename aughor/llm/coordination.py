"""Where the LLM path's cross-caller coordination lives — one seam, swappable backend.

Three pieces of provider state decide whether we respect an inference provider's
limits: how fast calls may be issued (pacing), how many may be in flight
(concurrency), and which backends are known-exhausted (cooldown). All three were
module-level dicts in ``aughor/llm/provider.py`` guarded by ``threading`` locks —
correct for exactly one process.

**Why that stops being correct.** The Vercel spike (docs/VERCEL_PLATFORM_DESIGN_2026-08-05.md
§3.5) drove five exploration slices and Vercel scaled them across *three cold plus two
warm instances by itself*. Process-local pacing means each instance independently
believes it is honouring the limit, so a declared 15 RPM becomes 15×N; a backend one
instance has learned is quota-exhausted keeps being probed by the others; and a
``threading.Semaphore`` caps nothing at all across processes. Measured free-tier caps
this runs against are small enough for that to matter — gemini-3.1-flash-lite at
15 RPM / 500 per day, OpenRouter free at 20 RPM / 1,000 per day.

So the *mechanism* is right and its *scope* is wrong. This module keeps the mechanism
and makes the scope a deployment choice: :class:`InProcessCoordinator` is today's exact
behaviour and stays the default, and a shared (Redis/Postgres-backed) implementation of
the same Protocol makes the gates hold across instances without provider.py changing.

Nothing here is Vercel-specific — the same seam is what makes a multi-worker
``uvicorn --workers N`` honour its own rate limit today, which it currently does not.

🔑 **The clock is part of the contract.** The in-process backend uses
``time.monotonic()``, whose epoch is arbitrary *per process* — sharing those numbers
between instances would compare unrelated timelines and silently produce no pacing at
all. A shared backend MUST use wall-clock time (or the store's own clock, which is
better still, since it removes the callers' clock skew). The Protocol is written so
that choice belongs to the backend: callers exchange **durations**, never timestamps.
"""
from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager
from typing import Iterator, Optional, Protocol, runtime_checkable


@runtime_checkable
class Coordinator(Protocol):
    """The cross-caller gates the LLM path needs. Implementations differ only in scope.

    Callers exchange durations, never timestamps — see the clock note in the module
    docstring. Every method is keyed by an opaque string (an endpoint base_url or a
    backend name); an implementation must treat distinct keys as fully independent,
    because a slow free endpoint must never throttle a paid one queued behind it.
    """

    def reserve(self, key: str, interval_s: float) -> float:
        """Claim the next issue-slot for ``key``, or report the wait until one frees.

        Returns ``0.0`` when the slot was claimed and the caller may proceed, else the
        number of seconds to wait before asking again. The claim MUST be atomic: two
        callers that both observe "clear" and both proceed are precisely the burst this
        exists to prevent. The retry loop stays with the caller so a shared backend
        never has to hold a connection open while sleeping.
        """
        ...

    def mark_cooldown(self, key: str, seconds: float) -> None:
        """Record that ``key`` is exhausted and should not be probed for ``seconds``."""
        ...

    def in_cooldown(self, key: str) -> bool:
        """Whether ``key`` is still inside a cooldown recorded earlier."""
        ...

    def concurrency_slot(self, key: str, limit: int):
        """Context manager capping in-flight work for ``key`` at ``limit``."""
        ...


class InProcessCoordinator:
    """Today's behaviour, unchanged — the default, and the only correct one for a
    single process with threads.

    Carried over verbatim from provider.py so this refactor is a change of *location*,
    not of semantics: the same ``monotonic`` clock, the same claim-inside-the-lock
    pacing, the same lazily-created per-endpoint ``threading.Semaphore``.
    """

    def __init__(self) -> None:
        self._pace_lock = threading.Lock()
        self._last_call_at: dict[str, float] = {}
        self._quota_lock = threading.Lock()
        self._cooldown_until: dict[str, float] = {}
        self._sem_lock = threading.Lock()
        self._semaphores: dict[str, threading.Semaphore] = {}

    # ── pacing ───────────────────────────────────────────────────────────────

    def reserve(self, key: str, interval_s: float) -> float:
        with self._pace_lock:
            now = time.monotonic()
            earliest = self._last_call_at.get(key, 0.0) + interval_s
            if now >= earliest:
                # Claimed INSIDE the lock: two threads that both read "clear" and then
                # both called would be the burst this exists to prevent.
                self._last_call_at[key] = now
                return 0.0
            return earliest - now

    # ── quota cooldown ───────────────────────────────────────────────────────

    def mark_cooldown(self, key: str, seconds: float) -> None:
        with self._quota_lock:
            self._cooldown_until[key] = time.monotonic() + max(0.0, seconds)

    def in_cooldown(self, key: str) -> bool:
        with self._quota_lock:
            until = self._cooldown_until.get(key)
            if until is None:
                return False
            if time.monotonic() >= until:      # expired — let it prove itself again
                del self._cooldown_until[key]
                return False
            return True

    # ── concurrency ──────────────────────────────────────────────────────────

    @contextmanager
    def concurrency_slot(self, key: str, limit: int) -> Iterator[None]:
        with self._sem_lock:
            sem = self._semaphores.get(key)
            if sem is None:
                sem = threading.Semaphore(max(1, limit))
                self._semaphores[key] = sem
        sem.acquire()
        try:
            yield
        finally:
            sem.release()

    # ── test / operational support ───────────────────────────────────────────

    def reset(self) -> None:
        """Drop all coordination state. For tests; never called on the serving path."""
        with self._pace_lock:
            self._last_call_at.clear()
        with self._quota_lock:
            self._cooldown_until.clear()
        with self._sem_lock:
            self._semaphores.clear()


# ── selection ────────────────────────────────────────────────────────────────
#
# One accessor, resolved on CALL rather than at import, following the Ledger.default()
# convention — a module that captures the coordinator in a constant at import time
# would pin whichever backend happened to be configured when it was first imported,
# which is the same trap db/paths.py records for state_dir().

_COORDINATOR: Optional[Coordinator] = None
_SELECT_LOCK = threading.Lock()

#: Env var naming the backend. Only ``inprocess`` ships today; a shared backend
#: registers here rather than editing provider.py.
COORDINATOR_ENV = "AUGHOR_LLM_COORDINATOR"

_BACKENDS: dict[str, type] = {"inprocess": InProcessCoordinator}


def default() -> Coordinator:
    """The process's coordinator, created once.

    An unknown name in ``AUGHOR_LLM_COORDINATOR`` degrades to ``inprocess`` rather than
    raising: a typo in a deployment env must not take the whole LLM path down, and the
    in-process gate is always a *safe* fallback — it paces more conservatively than a
    shared one (each instance gates itself), never less.
    """
    global _COORDINATOR
    if _COORDINATOR is None:
        with _SELECT_LOCK:
            if _COORDINATOR is None:
                name = (os.getenv(COORDINATOR_ENV) or "inprocess").strip().lower()
                _COORDINATOR = _BACKENDS.get(name, InProcessCoordinator)()
    return _COORDINATOR


def set_default(coordinator: Optional[Coordinator]) -> None:
    """Install a coordinator (or ``None`` to re-resolve from env on next use).

    The seam's test hook, and the entry point a shared backend uses at startup.
    """
    global _COORDINATOR
    with _SELECT_LOCK:
        _COORDINATOR = coordinator
