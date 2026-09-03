"""Execution-lifecycle hook registries — invert the agent's reach into query
execution and connection setup.

Two seams the platform's connection layer exposes, which the AGENT fills:

  • **post-execute** — after a (gated, audited, metered) query runs, the agent may
    react: e.g. emit a receipt about what the query did. ``fn(sql, result, connection_id)``.
  • **on-connect** — when a physical DuckDB connection is opened, the agent may
    install capabilities on the raw handle. ``fn(raw_conn, *, is_motherduck=...)``.
  • **guard-receipt** (A4) — when a platform-side guard silently rewrites or
    repairs SQL, it reports what it did through this seam; the agent's hook
    forwards the receipt to the live SSE sink so the intervention becomes a
    ``guard_receipt`` frame (and Chain-of-Thought step) instead of an invisible
    correction. ``fn(guard, action, detail, before, after)``.

Both run under ``tolerate`` — best-effort, never break execution or a connect. With
nothing registered they are no-ops (the platform executes and connects with zero
agent involvement), which is the plug-and-play property the boundary guarantees.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Callable, Optional

from aughor.kernel.errors import tolerate

_POST_EXECUTE: list[tuple[str, Callable]] = []  # fn(sql, result, connection_id)
_ON_CONNECT: list[tuple[str, Callable]] = []    # fn(raw_conn, **ctx)
_GUARD_RECEIPT: list[tuple[str, Callable]] = []  # fn(guard, action, detail, before, after)


def register_post_execute_hook(name: str, fn: Callable) -> None:
    _POST_EXECUTE.append((name, fn))


def register_on_connect_hook(name: str, fn: Callable) -> None:
    _ON_CONNECT.append((name, fn))


def register_guard_receipt_hook(name: str, fn: Callable) -> None:
    _GUARD_RECEIPT.append((name, fn))


def clear() -> None:
    _POST_EXECUTE.clear()
    _ON_CONNECT.clear()
    _GUARD_RECEIPT.clear()


def run_post_execute_hooks(sql: str, result, connection_id) -> None:
    for name, fn in list(_POST_EXECUTE):
        try:
            fn(sql, result, connection_id)
        except Exception as e:
            tolerate(e, f"post-execute hook {name!r}", counter=f"exec.post.{name}")


#: Receipts emitted inside an open :func:`collect_guard_receipts` block. A ContextVar
#: rather than a module list so concurrent requests — and the worker threads a fan-out
#: spawns, which inherit the context — never pour into each other's collection.
_COLLECTOR: ContextVar[Optional[list]] = ContextVar("guard_receipt_collector", default=None)


@contextmanager
def collect_guard_receipts():
    """Accumulate the guard interventions raised inside this block.

    The hook fan-out below is push-only: a receipt goes out to whoever registered a
    sink and is gone. That is right for the SSE stream, where the frame is the point,
    but it means a caller cannot ask "what did the guards do to the query I just ran"
    — the answer only existed as something already sent to somebody else.

    Yields the list, which fills as receipts arrive::

        with collect_guard_receipts() as receipts:
            result = execute_guarded(conn, sql, query_id=...)
        return {"result": result, "guard_receipts": receipts}

    Collecting does not consume: registered hooks still fire, so opening a collector
    around code that also streams cannot silently cost the UI its frames. Nested
    blocks each collect independently, and the outer one does not see the inner's —
    a collector is about one caller's own question.
    """
    token = _COLLECTOR.set([])
    try:
        yield _COLLECTOR.get()
    finally:
        _COLLECTOR.reset(token)


def _record_guard_verdict(guard: str, action: str, detail: str, before) -> None:
    """MI-1 — durable half of a guard receipt. Best-effort and trace-gated; never raises.

    A rewrite guard names no single column, so `subject` stays empty and the guard's own
    name carries the meaning: `pattern` is the guard (``fanout_defan``), `phase` is what
    it did (``rewrote_sql``). The E1 semantic checks fill `subject` because they ARE
    about one column — the two families share a table, not a shape.
    """
    try:
        from aughor.security.audit import GuardVerdicts
        GuardVerdicts.record(pattern=guard, phase=action, detail=detail,
                             sql=str(before) if before is not None else "")
    except Exception as e:
        tolerate(e, "guard-verdict persistence is additive; the receipt still fanned out",
                 counter="exec.guard.persist")


def emit_guard_receipt(guard: str, action: str, detail: str = "",
                       before=None, after=None) -> None:
    """Report a guard intervention (A4). No hook registered = no fan-out, which is
    what a bare platform (tests, scripts) gets.

    Also lands in the innermost open collector, if any — see
    :func:`collect_guard_receipts`.

    MI-1: an intervention is now also PERSISTED here rather than in a registered hook,
    because the only hook that exists is the agent's SSE forwarder — riding it would
    mean a bare platform, an automation tick and the quick path silently recorded
    nothing. This seam is the one every producer already calls, so recording here needs
    no registration and no producer can miss it. The no-op contract above is narrowed
    honestly: the write is trace-gated, so a caller outside a run still pays only a
    contextvar lookup, but a guard that fires inside one now costs a row.
    """
    _record_guard_verdict(guard, action, detail, before)
    sink = _COLLECTOR.get()
    if sink is not None:
        try:
            payload = {"guard": guard, "action": action, "detail": (detail or "")[:500]}
            if before is not None:
                payload["before"] = str(before)[:2000]
            if after is not None:
                payload["after"] = str(after)[:2000]
            sink.append(payload)
        except Exception as e:
            tolerate(e, "guard-receipt collection is additive; the hooks still fired",
                     counter="exec.guard.collect")
    for name, fn in list(_GUARD_RECEIPT):
        try:
            fn(guard, action, detail, before, after)
        except Exception as e:
            tolerate(e, f"guard-receipt hook {name!r}", counter=f"exec.guard.{name}")


def run_on_connect_hooks(raw_conn, **ctx) -> None:
    for name, fn in list(_ON_CONNECT):
        try:
            fn(raw_conn, **ctx)
        except Exception as e:
            tolerate(e, f"on-connect hook {name!r}", counter=f"exec.connect.{name}")
