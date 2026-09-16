"""Stopping work nobody is waiting for any more.

An abandoned run kept spending. Measured 2026-09-16: the kernel cancelled analyst jobs at
their 900s time budget, and their bodies — synchronous code on a worker thread, which an
asyncio cancel cannot reach — went on issuing model calls for up to six minutes after the
kill, three fresh requests in the worst case. A timed-out synthesis did the same one level
down: the run moved on to its rescue while the abandoned worker's stream failed validation
and launched a full blocking redo that nothing would ever read.

A thread cannot be interrupted mid-request, but it can be told not to START the next one.
A :class:`StopScope` rides a contextvar, so it crosses every ``ContextThreadPoolExecutor``
hop the metering accumulator already crosses. Whoever abandons the work stops the scope,
and :func:`checkpoint` — called by the LLM funnel before each request — raises
:class:`RunStopped` instead of spending.

Scopes nest: a child sees its parent's stop, never the reverse, so abandoning ONE bounded
call (a synthesis past its timeout) cannot stop the run that moved on without it.
"""
from __future__ import annotations

import concurrent.futures as _cf
import contextvars
from contextlib import contextmanager
from typing import Callable, Iterator, Optional, TypeVar

T = TypeVar("T")


class RunStopped(BaseException):
    """The work this call belonged to was abandoned.

    A ``BaseException`` for the reason ``BudgetExceeded`` and the kernel's cancel are one:
    the answer path is full of fail-open ``except Exception`` blocks, and a stop they could
    swallow would stop nothing.
    """

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class StopScope:
    """One unit of abandonable work. Stopping is one-way and the first reason wins."""

    __slots__ = ("_parent", "_reason")

    def __init__(self, parent: Optional["StopScope"] = None):
        self._parent = parent
        self._reason: Optional[str] = None

    def stop(self, reason: str) -> None:
        if self._reason is None:
            self._reason = reason or "stopped"

    @property
    def reason(self) -> Optional[str]:
        """Why this scope — or any scope enclosing it — was stopped; None while it runs."""
        if self._reason is not None:
            return self._reason
        return self._parent.reason if self._parent is not None else None


_scope: contextvars.ContextVar[Optional[StopScope]] = contextvars.ContextVar(
    "aughor_stop_scope", default=None)


def current() -> Optional[StopScope]:
    return _scope.get()


@contextmanager
def scope(target: Optional[StopScope] = None) -> Iterator[StopScope]:
    """Run the block inside ``target`` — by default a fresh child of the current scope."""
    s = target if target is not None else StopScope(_scope.get())
    token = _scope.set(s)
    try:
        yield s
    finally:
        _scope.reset(token)


def checkpoint() -> None:
    """Raise :class:`RunStopped` if the current work was abandoned.

    One contextvar read when nothing is scoped, so every caller outside an abandonable
    body — the explorer, the scheduler, a health probe — is untouched.
    """
    s = _scope.get()
    if s is not None:
        reason = s.reason
        if reason is not None:
            raise RunStopped(reason)


def run_bounded(fn: Callable[[], T], timeout_s: float, *, abandoned: str) -> T:
    """Run ``fn`` on its own worker for at most ``timeout_s``.

    Past the bound the worker's scope is stopped and ``TimeoutError`` raised; the request
    already in flight finishes on its own, but no further request starts. The pool copies
    context, so the worker keeps the run's metering, trace and org — all three of which a
    plain executor silently dropped.
    """
    from aughor.kernel.concurrency import ContextThreadPoolExecutor

    child = StopScope(_scope.get())

    def _body() -> T:
        with scope(child):
            return fn()

    ex = ContextThreadPoolExecutor(max_workers=1)
    try:
        fut = ex.submit(_body)
        try:
            return fut.result(timeout=timeout_s)
        except _cf.TimeoutError:
            child.stop(abandoned)
            raise
    finally:
        ex.shutdown(wait=False)
