"""Prompt capture as a bounded ACT, not a standing state (flag endgame, 2026-08-01).

Storing the content of model calls — schema, sampled values, glossary text and the
user's own question — is the most sensitive thing this product can write down. It used
to be governed by ``obs.prompt_capture``, a switch with no expiry: turned on to
reproduce one bad run, then on forever, silently, because nothing ever asked for it
back. A privacy control that depends on somebody remembering to close it is not a
control.

So capture is a WINDOW an operator opens deliberately, and it closes itself two ways at
once — after ``calls`` captured model calls, or at ``expires_at`` — whichever comes
first. Both bounds are recorded, both are reported, and a window that has run out is
indistinguishable from one that was never opened: :func:`active` is False and
:func:`consume` writes nothing.

Two deliberate choices worth stating, because the alternative is what the flag did:

* **The budget is counted in captured MODEL CALLS, not runs.** A run makes an
  unpredictable number of calls, so "the next 3 runs" is a bound nobody can size in
  advance. A caller asking for runs is asking for an unbounded amount of content.
* **Decrementing is what capture COSTS.** The counter falls when content is actually
  stored, not when a call is made, so a window opened while recording is off is not
  silently spent — and the operator's budget means what it says.

Fail-safe: any store error means "no window", i.e. no capture. Same posture as every
other observability read — the log must never break, or widen, the path it observes.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

_STORE = "obs_prompt_window"
_KEY = "window"

#: Ceilings on what one window may ask for. A request above either is clamped (and the
#: clamp is reported), never silently honoured — an operator who asks for 10,000 calls
#: over a week has described a standing switch, which is the thing this replaces.
MAX_CALLS = 200
MAX_MINUTES = 120

DEFAULT_CALLS = 20
DEFAULT_MINUTES = 15


def _ledger():
    from aughor.kernel.ledger import Ledger
    return Ledger.default()


def _read() -> Optional[dict]:
    try:
        row = _ledger().kv_get(_STORE, _KEY, None)
    except Exception:
        logger.debug("prompt-capture window read failed; treating as closed", exc_info=True)
        return None
    return row if isinstance(row, dict) else None


def _write(row: Optional[dict]) -> None:
    try:
        led = _ledger()
        if row is None:
            led.kv_delete(_STORE, _KEY)
        else:
            led.kv_put(_STORE, _KEY, row)
    except Exception:
        logger.debug("prompt-capture window write failed", exc_info=True)


def _live(row: Optional[dict]) -> Optional[dict]:
    """The row if it is still open on BOTH bounds, else None."""
    if not row:
        return None
    try:
        if int(row.get("remaining", 0)) <= 0:
            return None
        if float(row.get("expires_at", 0)) <= time.time():
            return None
    except (TypeError, ValueError):
        return None
    return row


def open_window(*, calls: int = DEFAULT_CALLS, minutes: int = DEFAULT_MINUTES,
                opened_by: str = "", reason: str = "") -> dict:
    """Open (or replace) the capture window. Returns its :func:`status` shape.

    ``calls`` and ``minutes`` are clamped to :data:`MAX_CALLS` / :data:`MAX_MINUTES`,
    and the clamp is visible in the returned row rather than being a surprise later.
    """
    calls = max(1, min(int(calls or DEFAULT_CALLS), MAX_CALLS))
    minutes = max(1, min(int(minutes or DEFAULT_MINUTES), MAX_MINUTES))
    now = time.time()
    row = {
        "granted": calls,
        "remaining": calls,
        "minutes": minutes,
        "opened_at": now,
        "expires_at": now + minutes * 60,
        "opened_by": (opened_by or "")[:120],
        "reason": (reason or "")[:280],
    }
    _write(row)
    return status()


def close_window() -> dict:
    """Close the window now. Idempotent — closing a closed window is not an error."""
    _write(None)
    return status()


def active() -> bool:
    """True when content may still be captured."""
    return _live(_read()) is not None


def consume() -> bool:
    """Claim one call's worth of budget. True when the caller may store content.

    Decrementing HERE — at the moment content is about to be written — is what keeps
    the operator's number honest: an unused window expires by clock alone, and a
    recording-off process cannot silently spend somebody's budget.
    """
    row = _live(_read())
    if row is None:
        return False
    row["remaining"] = int(row["remaining"]) - 1
    if row["remaining"] <= 0:
        _write(None)          # spent — the window is gone, not a zero row lying around
    else:
        _write(row)
    return True


def status() -> dict[str, Any]:
    """What an operator needs to answer "is anything being recorded right now?"."""
    row = _live(_read())
    if row is None:
        return {"active": False, "remaining": 0, "granted": 0,
                "expires_in_seconds": 0, "opened_by": "", "reason": ""}
    return {
        "active": True,
        "remaining": int(row["remaining"]),
        "granted": int(row.get("granted", 0)),
        "expires_in_seconds": max(0, int(float(row["expires_at"]) - time.time())),
        "opened_by": row.get("opened_by", ""),
        "reason": row.get("reason", ""),
    }
