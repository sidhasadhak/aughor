"""K4 — the error taxonomy: failure is data, never silence.

The measured baseline was 207 except-blocks whose body is a bare ``pass`` /
``continue`` — each one a place where the platform eats a failure and the user
later sees a blank panel, a missing ontology, or vanished sample data with no
trail. The kernel rule:

    The ONLY legal way to swallow an exception is ``tolerate()``.

``tolerate`` keeps the resilience (the caller continues) but makes the failure
observable three ways: a log line with the *reason the swallow is acceptable*,
a stats counter, and a journal event (so "what failed at 14:32" stays a query).
A ratchet test (tests/unit/test_kernel_contracts.py) pins the bare-swallow
count: new ones fail CI; the number can only go down.

Usage::

    try:
        refresh_cache(conn_id)
    except Exception as exc:
        tolerate(exc, "cache refresh is best-effort; next poll retries",
                 counter="cache.refresh", conn_id=conn_id)
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


def tolerate(
    exc: BaseException,
    reason: str,
    *,
    counter: Optional[str] = None,
    conn_id: Optional[str] = None,
    canvas_id: Optional[str] = None,
    level: int = logging.WARNING,
) -> None:
    """Record a deliberately-swallowed exception. Never raises."""
    try:
        logger.log(level, "tolerated: %s (%s: %s)", reason, type(exc).__name__, exc)
    except Exception:
        pass
    try:
        from aughor.stats import stats
        stats.inc(f"tolerated.{counter or 'uncategorized'}")
    except Exception:
        pass
    if os.environ.get("AUGHOR_KERNEL_EVENTS", "1") != "0":
        try:
            from aughor.kernel.ledger import Ledger
            from aughor.kernel.jobs import current_job_id
            Ledger.default().emit(
                "error.tolerated",
                {"reason": reason, "error": f"{type(exc).__name__}: {str(exc)[:300]}",
                 **({"counter": counter} if counter else {})},
                conn_id=conn_id, canvas_id=canvas_id, job_id=current_job_id(),
            )
        except Exception:
            pass
