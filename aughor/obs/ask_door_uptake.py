"""SP-15's measure — is the Ask door on a held row actually used?

The wave's done-when is measured like SP-M: *the share of held rows whose Ask door was
used, from the session log, no model.* The door hands the palette its object structurally
(`{kind: "departure", id}` on the `/ask` body), and the ask door's request event records
it (`payload.focus`), so the reading is a join of two things the platform already keeps —
the departures ledger's held rows and the session log's requests — never a counter
somebody has to remember to bump.

Two of §7's standing lessons shape it. **A capability nobody uses looks exactly like one
that works, from the inside** — the departures screen's remedy shipped 2026-09-25 and
without this number nothing could say whether the door was ever pressed. And **an
unreadable log reports `None`, never zero**: a failed probe is not an absence.
"""
from __future__ import annotations

from typing import Optional

#: The kinds the palette can be summoned from; only `departure` has a held population.
FOCUS_KIND = "departure"


def ask_door_uptake(*, org_id: Optional[str] = None, scan: int = 20000) -> dict:
    """``{held, asked, rate, by_day, measured}`` — held rows in the ledger, how many of
    them Spotlight was asked about from the row, and the share. ``measured`` is False and
    ``rate`` None when either store could not be read; ``rate`` is also None when nothing
    is held (0 of 0 is not a rate)."""
    from aughor.govern.departure import HELD, HELD_OWNER, HELD_PROBATION
    from aughor.govern.departure_store import list_departures
    from aughor.kernel.ledger import Ledger
    from aughor.obs.session_log import USER_REQUEST

    try:
        held_rows = list_departures(states=[HELD, HELD_OWNER, HELD_PROBATION], limit=500)
        requests = Ledger.default().session_events(kind=USER_REQUEST, org_id=org_id, limit=scan)
    except Exception as exc:  # noqa: BLE001 — a failed probe is not a zero
        from aughor.kernel.errors import tolerate
        tolerate(exc, "ask-door uptake: a store could not be read; reported unmeasured",
                 counter="obs.ask_door_uptake")
        return {"held": None, "asked": None, "rate": None, "by_day": [], "measured": False}

    held = {str(r.get("id")) for r in held_rows if r.get("id")}
    asked: dict[str, str] = {}                       # departure id -> first day asked
    for e in requests:
        focus = (e.get("payload") or {}).get("focus") or {}
        if not isinstance(focus, dict) or focus.get("kind") != FOCUS_KIND:
            continue
        dep = str(focus.get("id") or "")
        if dep and dep not in asked:
            asked[dep] = str(e.get("at") or "")[:10]
    asked_held = {d for d in asked if d in held}
    by_day: dict[str, int] = {}
    for dep in asked_held:
        by_day[asked[dep]] = by_day.get(asked[dep], 0) + 1
    return {
        "held": len(held),
        "asked": len(asked_held),
        "rate": (round(len(asked_held) / len(held), 3) if held else None),
        "asked_about_rows_not_held": len(asked) - len(asked_held),
        "by_day": [{"day": d, "asked": n} for d, n in sorted(by_day.items(), reverse=True)],
        "measured": True,
    }
