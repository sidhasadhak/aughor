"""Triage under an attention budget (`IDEAS.md` 9; the 2027 study §I "triage"; phase 2, P2-2).

Each addressee gets a fixed number of unattended interruptions a week — alerts, briefings, inbox
items and analysis sends all compete for the same slots. The budget is charged at the ONE door
every message already passes, the departure gate (`govern/departure.py`), as its last guard:
once the week's slots to an addressee are spent, the next unattended departure is HELD, recorded
in the departures ledger under its own state (``held_budget``) with its score, so what was held
is a list a person can read, never a silence. A person pressing Share is not an interruption the
platform chose, and is exempt — the gate's own rule for probation and the repeat law.

**The addressee today is the target** (a Slack channel is the people who read it) or, where the
gate knows a person, that person. Slots per person arrive when identity resolves a channel's
members; until then the budget is per place and this docstring says so.

**The four ranking terms are published** (:data:`TERMS`), each with its weight and with how it is
READ today, because triage's weights are set by hand and only a published list lets misses (the
review of a missed move, `IDEAS.md` 8) move them. A departure arrives one at a time, so the score
cannot reorder what already left: it rides every row (``checks["triage"]``) and every hold, and a
held row with a higher score than the ones that departed is the measurement that says the weights
or the slots are wrong. Nothing here is a model.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

#: Unattended interruptions a week per addressee, when no one has set another number.
DEFAULT_SLOTS_PER_WEEK = 10
#: The kernel kv store that holds a per-addressee override.
KV_STORE = "attention_slots"
#: The departures ledger state of a departure the budget held.
HELD_BUDGET = "held_budget"

#: The four terms, with their weights (summing to 1) and how each is read today.
TERMS: tuple[dict[str, Any], ...] = (
    {"term": "mission", "label": "bears on a mission", "weight": 0.35,
     "read_today": ("from the missions people wrote (`record/mission.py`, phase 5): 1 when the message is about an "
                    "active mission's objective metric, 0.7 a constraint's, 0.5 something it watches; 0 when no "
                    "active mission with an owner bears on it — and a mission's own interruptions a week are "
                    "charged on top of the addressee's slots")},
    {"term": "size", "label": "size against its own normal range", "weight": 0.25,
     "read_today": ("the caller's reading of how far the number sits outside its declared range, 0 to 1 — "
                    "a monitor alert gives |current − threshold| / |threshold|, capped; a message that "
                    "brings no range reads 0")},
    {"term": "waiting", "label": "cost of waiting", "weight": 0.20,
     "read_today": "by kind: an alert 1.0; an analysis or a finding 0.6; a briefing 0.4; anything else 0.5"},
    {"term": "novelty", "label": "novelty against lessons", "weight": 0.20,
     "read_today": ("from the repeat guard: 1 when nothing of this shape departed to this place in the repeat "
                    "window; 0.5 when the same shape departed with numbers that moved; 1 when the guard did not "
                    "judge (a person's send, a kind with its own policy)")},
)
_WAITING_BY_KIND = {"monitor_alert": 1.0, "agent_alert": 1.0, "analysis": 0.6, "finding": 0.6, "briefing": 0.4}


def _ledger():
    from aughor.kernel.ledger import Ledger
    return Ledger.default()


def slots_for(addressee: str) -> int:
    """The week's slots for an addressee: the override a person set, else the default."""
    try:
        raw = _ledger().kv_get(KV_STORE, addressee or "", None)
        if raw is not None and int(raw) >= 0:
            return int(raw)
    except Exception:  # noqa: BLE001 — an unreadable override is the default, said by the view
        pass
    return DEFAULT_SLOTS_PER_WEEK


def set_slots(addressee: str, slots: int) -> int:
    if not addressee:
        raise ValueError("slots are set for an addressee")
    n = int(slots)
    if n < 0:
        raise ValueError("slots are a count")
    _ledger().kv_put(KV_STORE, addressee, n, max_entries=5000)
    return n


def week_start(now: Optional[datetime] = None) -> str:
    """Monday 00:00 UTC of the week ``now`` falls in, as the ledger's timestamp shape."""
    now = now or datetime.now(timezone.utc)
    monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return monday.strftime("%Y-%m-%dT%H:%M:%SZ")


def used_this_week(addressee: str, now: Optional[datetime] = None) -> int:
    from aughor.govern.departure_store import count_departed_to
    return count_departed_to(addressee, since=week_start(now))


def score(*, kind: str, size: float = 0.0, novelty: float = 1.0, mission: float = 0.0) -> dict:
    """The four terms and their weighted sum, each term in [0, 1]."""
    terms = {"mission": _unit(mission), "size": _unit(size),
             "waiting": _WAITING_BY_KIND.get(kind or "", 0.5), "novelty": _unit(novelty)}
    total = sum(float(t["weight"]) * terms[str(t["term"])] for t in TERMS)
    return {"terms": terms, "score": round(total, 3)}


def _unit(x) -> float:
    try:
        return max(0.0, min(1.0, float(x)))
    except (TypeError, ValueError):
        return 0.0


def charge(*, addressee: str, kind: str, size: float = 0.0, novelty: float = 1.0, mission: float = 0.0,
           now: Optional[datetime] = None) -> dict:
    """Whether this unattended departure has a slot: ``{"allowed", "used", "slots", "score",
    "terms", "why", "resets"}``. The slot is not spent here — the departure's own ledger row,
    written by the gate, is the count. ``mission`` is the bearing term the gate read from the
    missions people wrote (phase 5)."""
    now = now or datetime.now(timezone.utc)
    slots = slots_for(addressee)
    used = used_this_week(addressee, now)
    ranked = score(kind=kind, size=size, novelty=novelty, mission=mission)
    start = datetime.strptime(week_start(now), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    resets = (start + timedelta(days=7)).date().isoformat()
    allowed = used < slots
    why = (f"{used} of {slots} slots to {addressee or 'this place'} used this week; score {ranked['score']:.2f}"
           if allowed else
           f"attention budget: all {slots} slots to {addressee or 'this place'} are used this week "
           f"(they reset {resets}); held with score {ranked['score']:.2f} — listed on the departures screen")
    return {"allowed": allowed, "used": used, "slots": slots, "score": ranked["score"], "terms": ranked["terms"],
            "why": why, "resets": resets}


def held_this_week(addressee: Optional[str] = None, now: Optional[datetime] = None, *, limit: int = 100) -> list[dict]:
    """What the budget held, newest first, with each row's score — the list a person reads."""
    from aughor.govern.departure_store import decode_row, held_by_budget
    rows = held_by_budget(addressee=addressee, since=week_start(now), limit=limit)
    out = []
    for r in rows:
        d = decode_row(r)
        out.append({"departure_id": d.get("id", ""), "at": d.get("ts", ""), "kind": d.get("kind", ""),
                    "target": d.get("target", ""), "addressed_to": d.get("addressed_to", ""),
                    "by": d.get("automation_name") or d.get("actor") or "", "text": d.get("text_preview", ""),
                    "why": (d.get("checks") or {}).get("attention", ""),
                    "triage": (d.get("checks") or {}).get("triage", "")})
    return out


def budget_view(addressee: str, now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    slots, used = slots_for(addressee), used_this_week(addressee, now)
    held = held_this_week(addressee, now)
    return {"addressee": addressee, "week_start": week_start(now)[:10], "slots": slots, "used": used,
            "left": max(slots - used, 0), "held": held, "held_count": len(held),
            "note": ("the budget is per place until identity resolves a channel's members; a person the gate "
                     "addresses directly is their own addressee")}


def size_for_alert(current: Optional[float], threshold: Optional[float]) -> float:
    """A monitor alert's size term: how far the reading sits outside its declared threshold."""
    if current is None or threshold in (None, 0):
        return 0.0
    try:
        return _unit(abs(float(current) - float(threshold)) / abs(float(threshold)))
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0
