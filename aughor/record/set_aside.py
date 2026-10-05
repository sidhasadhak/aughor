"""Set aside — "not now" on an item that waits on a person (the 2027 study §V, screen 2).

Decided 2026-10-05: dismissing an item on the Now page is a SNOOZE, not a verdict. A person says
until when and why; the item leaves the list until that day and then returns. Nothing about the
thing itself is written — a review that was set aside is still due on its own page, and no outcome,
closing or rejection is booked in its name. An item also returns EARLY when the record behind it
changes (a claim a decision stood on is restated, an inquiry wakes), because what the person
declined to look at is no longer what is there.

A set-aside is a kernel artifact of kind ``set_aside`` under one key per item, so setting the same
item aside again — or restoring it — is a new version with the earlier ones kept. Whether it still
hides its item is computed on read from the day and from the record as it stands; nothing is
written by looking.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Optional

from pydantic import BaseModel

KIND = "set_aside"
#: What can be set aside: the four kinds of row "Waiting on you" lists.
ITEM_KINDS: tuple[str, ...] = ("decision", "inquiry", "departure", "approval")
#: A set-aside whose day came this long ago is no longer listed as returned — its row is either
#: dealt with or simply on the list again.
RETURNED_LISTED_DAYS = 30


class SetAside(BaseModel):
    item_kind: str
    ref: str                       # the item's stable name: a decision's or inquiry's key, a departure's or proposal's id
    until: str                     # ISO day it returns on
    why: str
    by: str = ""
    at: str = ""
    title: str = ""                # the row as it read when it was set aside
    connection_id: str = ""
    seen: str = ""                 # the version of the record that was set aside — what "changed since" is read against
    restored_at: str = ""
    restored_by: str = ""
    # read-only, filled on read
    id: str = ""
    version: int = 0
    #: active — it hides its row · returned — its day came, or the record behind it changed
    status: str = ""
    back_because: str = ""


class SetAsideRefused(ValueError):
    """The door said no, and why."""


def _ledger():
    from aughor.kernel.ledger import Ledger
    return Ledger.default()


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _key(item_kind: str, ref: str) -> str:
    return f"{KIND}:{item_kind}:{ref}"


def _from(art: dict) -> SetAside:
    s = SetAside.model_validate(dict(art.get("payload") or {}))
    s.id, s.version = str(art.get("id") or ""), int(art.get("version") or 0)
    return s


def _book(s: SetAside) -> SetAside:
    data = s.model_dump()
    for read_only in ("id", "version", "status", "back_because"):
        data.pop(read_only, None)
    aid = _ledger().artifact_write(KIND, _key(s.item_kind, s.ref), data, conn_id=s.connection_id or None,
                                   lineage=[("sets_aside", s.ref, f"until {s.until}")])
    art = _ledger().artifact_by_id(aid)
    return _from(art) if art else s


# ── the record behind an item ──────────────────────────────────────────────────────────────

def record_of(item_kind: str, ref_or_id: str) -> Optional[dict[str, str]]:
    """``{ref, seen, connection_id}`` for the record an item is about as it stands now — its stable
    name, the version current today, its connection — or None when there is no such record. A
    decision and an inquiry are named by key, so every version's id resolves to the same item."""
    if item_kind == "decision":
        from aughor.record import decisions as D
        d = D.get_decision(ref_or_id)
        if d is None:
            art = _ledger().artifact_latest(ref_or_id)
            d = D.get_decision(str(art.get("id") or "")) if art else None
        if d is None:
            return None
        current = D.latest_decision(d.source) or d
        return {"ref": current.key, "seen": current.id, "connection_id": current.connection_id}
    if item_kind == "inquiry":
        from aughor.record import inquiry as I
        q = I.get_inquiry(ref_or_id) or I.latest(ref_or_id)
        if q is None:
            return None
        current = I.latest(q.key) or q
        return {"ref": current.key, "seen": current.id, "connection_id": current.connection_id}
    # a departure and a proposed action have one id for life; nothing about them restates
    return {"ref": ref_or_id, "seen": "", "connection_id": ""}


def _changed_because(s: SetAside, stands: dict[str, str]) -> str:
    """Why the record behind a set-aside is not the one that was set aside, or "" when it is."""
    if not s.seen or stands["seen"] == s.seen:
        return ""
    if s.item_kind == "decision":
        from aughor.record import decisions as D
        d = D.get_decision(stands["seen"])
        if d is not None and d.reopened_by:
            return "a claim it relied on was restated"
        return "the decision was changed since it was set aside"
    from aughor.record import inquiry as I
    q = I.get_inquiry(stands["seen"])
    woke = [w for w in (q.woke if q else []) if str(w.get("at") or "") > s.at]
    if woke:
        return str(woke[-1].get("why") or "it woke")[:200]
    return "the inquiry was changed since it was set aside"


def _read(s: SetAside, today: str) -> SetAside:
    """The set-aside with what it does today, computed and never written."""
    if s.until <= today:
        s.status, s.back_because = "returned", f"its day came ({s.until})"
        return s
    stands = record_of(s.item_kind, s.ref)
    because = _changed_because(s, stands) if stands else ""
    s.status, s.back_because = ("returned", because) if because else ("active", "")
    return s


# ── the doors ──────────────────────────────────────────────────────────────────────────────

def set_aside(*, item_kind: str, ref: str, until: str, why: str, by: str = "", title: str = "",
              now: Optional[_dt.datetime] = None) -> SetAside:
    """Set one waiting item aside until a day, with why. Refuses a kind Now does not list, a day
    that is not after today, a reason left out, and an item that does not exist."""
    now = now or _now()
    if item_kind not in ITEM_KINDS:
        raise SetAsideRefused(f"only {', '.join(ITEM_KINDS)} wait on a person here")
    if not (why or "").strip():
        raise SetAsideRefused("setting something aside says why")
    try:
        day = _dt.date.fromisoformat((until or "").strip()[:10])
    except ValueError:
        raise SetAsideRefused("it is set aside until a day, written YYYY-MM-DD")
    if day <= now.date():
        raise SetAsideRefused("it is set aside until a later day — today's list is what it is being taken off")
    stands = record_of(item_kind, (ref or "").strip())
    if stands is None or not stands["ref"]:
        raise SetAsideRefused(f"no such {item_kind} to set aside")
    return _read(_book(SetAside(
        item_kind=item_kind, ref=stands["ref"], until=day.isoformat(), why=why.strip()[:1000],
        by=by or "unidentified", at=now.isoformat(), title=(title or "").strip()[:400],
        connection_id=stands["connection_id"], seen=stands["seen"])), now.date().isoformat())


def restore(*, item_kind: str, ref: str, by: str = "", now: Optional[_dt.datetime] = None) -> SetAside:
    """Bring a set-aside item back before its day. A new version; the set-aside stays in its history."""
    now = now or _now()
    art = _ledger().artifact_latest(_key(item_kind, (ref or "").strip()))
    s = _from(art) if art and art.get("kind") == KIND else None
    if s is None or s.restored_at:
        raise SetAsideRefused("nothing is set aside under that name")
    s.restored_at, s.restored_by = now.isoformat(), by or "unidentified"
    return _book(s)


def listing(*, now: Optional[_dt.datetime] = None, limit: int = 500) -> dict[str, Any]:
    """What is set aside today and what has come back: ``active`` hides its row; ``returned`` says
    why a row that was set aside is on the list again — its day came, or its record changed."""
    now = now or _now()
    today = now.date().isoformat()
    cutoff = (now.date() - _dt.timedelta(days=RETURNED_LISTED_DAYS)).isoformat()
    active: list[SetAside] = []
    returned: list[SetAside] = []
    for art in _ledger().artifacts_of_kind(KIND, limit=limit):
        s = _from(art)
        if s.restored_at:
            continue
        s = _read(s, today)
        if s.status == "active":
            active.append(s)
        elif s.until >= cutoff:
            returned.append(s)
    active.sort(key=lambda s: s.until)
    return {"today": today, "active": [s.model_dump() for s in active], "returned": [s.model_dump() for s in returned]}
