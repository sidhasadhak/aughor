"""Canonical time helpers — one source for UTC timestamps and ISO age.

Previously `_now()` / `_now_iso()` / `_age_hours()` were re-defined in ~13 modules
(and twice within `process/causal.py`). They are unified here. `now_iso()` returns an
aware UTC ISO-8601 string (``…+00:00``); `age_hours()` is tolerant of naive strings and
parse errors.
"""
from __future__ import annotations

from datetime import datetime, timezone


def now_iso() -> str:
    """Current UTC time as an ISO-8601 string (aware, ``…+00:00``)."""
    return datetime.now(timezone.utc).isoformat()


def now_iso_z() -> str:
    """Current UTC time as an ISO-8601 string with a ``Z`` suffix (``…Z``) — the form some
    stores/APIs persist. Preserved so consolidating those modules changes no stored format."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def age_hours(iso: str) -> float:
    """Hours elapsed since an ISO timestamp. Naive strings are treated as UTC; a bad/empty
    value returns a large sentinel (9999) so 'too old' checks fail safe."""
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 3600
    except Exception:
        return 9999.0
