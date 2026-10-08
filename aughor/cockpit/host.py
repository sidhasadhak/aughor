"""What the host says to a cockpit about the range it is read for (Arc CT, CT-4).

A cockpit's conditions may read ``/range/status``. This is where that word comes from: the
range is resolved exactly as the Briefing resolves its own (``briefing.ranges.resolve_for`` —
the connection's measured lag, the organisation's fiscal year, **no model call**), and its
status is read off the dates.

    standing     no range was chosen: every card runs as it was written
    final        the range's days have all settled
    provisional  the range is over, and some of its days have not settled yet
    to_date      the range is still under way

The four words are the web's (``web/lib/cockpit/hostState.ts``); a test holds the two lists
together. A card's own status — within, over, unmeasured — is read off the card's run, which
happens in the browser, so it is said there (``web/lib/cockpit/hostStatus.ts``).
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional

STANDING = "standing"
FINAL = "final"
PROVISIONAL = "provisional"
TO_DATE = "to_date"
RANGE_STATUSES = (STANDING, FINAL, PROVISIONAL, TO_DATE)

_TO_DATE_PRESETS = ("month_to_date", "year_to_date")


def status_of(spec: Any) -> str:
    """The status of a resolved range (a ``RangeSpec``), from its own dates."""
    if spec.preset in _TO_DATE_PRESETS or getattr(spec, "under_way", False):
        return TO_DATE
    settled = spec.as_of - timedelta(days=int(spec.lag_days or 0))   # the newest settled day
    if spec.last_day >= spec.as_of:
        return TO_DATE
    if spec.last_day > settled:
        return PROVISIONAL
    return FINAL


def standing() -> dict:
    """The range block when no range was chosen."""
    return {"status": STANDING, "preset": None, "start": None, "last_day": None,
            "covers": "", "as_of": None, "lag_days": None, "still_moving": [],
            "data_through": None, "edge_note": ""}


def range_state(conn_id: str, preset: Optional[str] = None, *, start: Optional[date] = None,
                end: Optional[date] = None, workspace_id: Optional[str] = None,
                today: Optional[date] = None) -> tuple[Optional[dict], str]:
    """The range block a cockpit is read for, or ``(None, why)`` when the range cannot be read."""
    if not (preset or start or end):
        return standing(), ""
    from aughor.briefing import ranges
    spec, why = ranges.resolve_for(conn_id, preset, start=start, end=end,
                                   workspace_id=workspace_id, today=today)
    if spec is None:
        return None, why
    return {"status": status_of(spec), "preset": spec.preset,
            "start": spec.start.isoformat(), "last_day": spec.last_day.isoformat(),
            "covers": ranges.phrases(spec)["covers"], "as_of": spec.as_of.isoformat(),
            "lag_days": spec.lag_days, "still_moving": list(spec.still_moving),
            "data_through": spec.data_through.isoformat() if spec.data_through else None,
            "edge_note": spec.edge_note}, ""
