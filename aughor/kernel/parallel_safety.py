"""Declared parallel-safety (Wave R5) — one property, one checkpoint.

Aughor fans work out in four places today: ADA's per-phase query batch, the explore
wave's sub-questions, the phase waves, and the health check's per-model probes. All four
dispatch **reads**, and the SQL gate proves each one read-only — so the property holds,
but it holds by *coincidence of what is currently fanned out*, not by declaration. Nothing
in the code says "this unit may run concurrently", so nothing can notice when something
that may not does.

That gap is a growth problem, and the K-plane is the thing growing. A declared action can
POST a webhook, write an annotation, mutate an external system. Fan two of those out and
the failure is not a crash — it is two refunds, or a webhook delivered twice, with no
error anywhere. The SQL gate cannot see it because no SQL is involved.

**The checkpoint is on the dangerous side, not the fan-out side.** A helper every fan-out
must remember to call is a helper that the fifth fan-out forgets — the same shape as the
guard battery's five re-assembled sites, and as R4's fifteen hand-built error frames. So
instead: a fan-out *declares itself* by entering :func:`fanout`, and
:func:`assert_dispatchable` — called once, inside the K-plane executor — refuses an action
that is not declared parallel-safe while a fan-out is in progress. A new fan-out added
next year is covered without touching this file; a new action defaults to unsafe.

The default is False everywhere, in both directions: an undeclared action is not
dispatchable inside a fan-out, and an unmarked call site is not a fan-out. Both failures
degrade to *serial*, which is slow rather than wrong.
"""
from __future__ import annotations

import contextvars
import logging
from contextlib import contextmanager
from typing import Any, Optional

logger = logging.getLogger(__name__)

#: The fan-out currently in progress on this context, or "" — a label, so a refusal can
#: name the concurrent region it came from. A contextvar rather than a thread-local
#: because ``ContextThreadPoolExecutor`` copies context into its workers, which is exactly
#: the propagation this needs (and the reason the metering and budget planes use it too).
_fanout: contextvars.ContextVar[str] = contextvars.ContextVar("aughor_fanout", default="")


class ParallelSafetyError(RuntimeError):
    """A unit that is not declared parallel-safe was dispatched inside a fan-out."""


@contextmanager
def fanout(where: str):
    """Mark the enclosing region as running work concurrently.

    Entered by every fan-out site. Nesting is allowed and the innermost label wins — a
    wave inside a wave is still a fan-out, and the nearest label is the more useful one in
    a refusal message.
    """
    token = _fanout.set(where or "a parallel region")
    try:
        yield
    finally:
        try:
            _fanout.reset(token)
        except (ValueError, LookupError):
            # The token belongs to another context (the region was entered on one thread
            # and left on another). Nothing to reset there; leaking the flag would be the
            # dangerous direction, so clear it outright.
            _fanout.set("")


@contextmanager
def fanout_region(where: str):
    """:func:`fanout`, but it can never break the region it wraps.

    The import-and-call form used at the fan-out sites, where an exception from a
    *safety-labelling* helper would take down real work to protect it. Any failure here
    degrades to "this region is unlabelled", which means the K-plane check does not fire —
    the same state as before Wave R5, not a worse one.
    """
    try:
        token = _fanout.set(where or "a parallel region")
    except Exception:
        logger.debug("parallel_safety: could not mark fan-out %s", where, exc_info=True)
        yield
        return
    try:
        yield
    finally:
        try:
            _fanout.reset(token)
        except (ValueError, LookupError):
            _fanout.set("")


def current_fanout() -> str:
    """The label of the fan-out in progress, or ``""``."""
    return _fanout.get()


def in_fanout() -> bool:
    return bool(_fanout.get())


def declared_parallel_safe(unit: Any) -> Optional[bool]:
    """The unit's DECLARED value, or None when it declares nothing.

    None and False are deliberately distinct: "nobody said" is a gap worth logging, while
    "declared unsafe" is a decision that was made. Both refuse — but only one is a bug.
    """
    value = getattr(unit, "parallel_safe", None)
    return bool(value) if isinstance(value, bool) else None


def is_parallel_safe(unit: Any) -> bool:
    """Whether ``unit`` may be dispatched concurrently. Undeclared ⇒ False."""
    return declared_parallel_safe(unit) is True


def assert_dispatchable(unit: Any, *, name: str = "") -> None:
    """Raise :class:`ParallelSafetyError` if ``unit`` is being dispatched inside a fan-out
    without declaring itself parallel-safe. A no-op outside a fan-out.

    This is the ONE checkpoint. It lives at the dispatch site of the dangerous operation
    rather than at each fan-out, so a fan-out added later is covered by construction.
    """
    where = _fanout.get()
    if not where or is_parallel_safe(unit):
        return
    label = name or getattr(unit, "id", None) or type(unit).__name__
    declared = declared_parallel_safe(unit)
    from aughor.stats import bump

    bump("parallel_safety.refused")
    raise ParallelSafetyError(
        f"{label} is {'declared NOT parallel-safe' if declared is False else 'not declared parallel-safe'} "
        f"and was dispatched inside {where}. Run it serially, or declare "
        f"parallel_safe=True if concurrent runs are genuinely independent."
    )


# The SQL half of this policy lives in `aughor.tools.executor`
# (`sql_is_parallel_safe` / `check_sql_fanout`), NOT here. The kernel must not import the
# agent/tools layer — the platform→agent boundary test caught this module reaching for
# `tools.executor.validate_sql`, and it was right to: the generic machinery above belongs
# in the kernel, while "is this statement a read" is SQL-domain knowledge that already has
# a home next to the check it wraps.
