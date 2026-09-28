"""A person's cockpits in the Briefing — list, read, start, keep, go back, retire, draft, move
(Arc CT, CT-7 to CT-10; ROADMAP §3.50).

Behind ``cockpit.composed``. Off, every route here answers 404 and the Briefing draws its
cockpit as it always did. On, **one route calls a model** — ``POST /cockpits/draft``, when a
person names an area and asks for a draft. Every other route reads what was kept, or keeps
what a person wrote, and calls none.

A cockpit is the asker's own (``aughor/cockpit/home.py``): the person comes from the request,
never from a parameter, so no route here can read or change someone else's. Every connection a
route names is checked by the router's guard, which is why the connection is a query parameter
on every route, the writes included.

Every write goes through ``aughor.cockpit.versions``, so it goes through the validator and is
kept with the person's name. A refusal is an HTTP error that carries the validator's own
sentences; it is never a 200 with nothing kept.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from aughor.security.authz import connection_owner_guard

router = APIRouter(tags=["cockpit"], dependencies=[Depends(connection_owner_guard)])

#: What a kept-or-not outcome is to a caller over HTTP.
_STATUS_CODE = {"refused": 422, "not_checked": 503, "failed": 500}


class KeepRequest(BaseModel):
    spec: Any
    note: str = ""


class RestoreRequest(BaseModel):
    version: int


class RetireRequest(BaseModel):
    note: str = ""


class DraftRequest(BaseModel):
    area: str
    schema_name: Optional[str] = None


class MoveRequest(BaseModel):
    canvas_id: str


def _on() -> None:
    from aughor.kernel.flags import flag_enabled
    if not flag_enabled("cockpit.composed"):
        raise HTTPException(status_code=404, detail="cockpits need the 'cockpit.composed' flag")


def _home(request: Request, connection_id: str, cockpit_id: str):
    from aughor.cockpit.home import Home, person_of, valid_id
    if not connection_id:
        raise HTTPException(status_code=422, detail="connection_id is required")
    if not valid_id(cockpit_id):
        raise HTTPException(status_code=404, detail="No such cockpit")
    return Home(connection_id, person_of(request), cockpit_id)


def _answer(kept, **more) -> dict:
    code = _STATUS_CODE.get(kept.status)
    if code:
        raise HTTPException(status_code=code, detail=kept.as_dict())
    return {**kept.as_dict(), **more}


def _day(value: Optional[str], what: str) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"{what} is an ISO day, e.g. 2026-08-17")


def _layout_order(connection_id: str, owner: str) -> list[str]:
    """The card ids in the order the person arranged them in the Briefing before cockpits had
    names: top to bottom, then left to right."""
    from aughor.dashboard.store import get_layout
    layout = get_layout(connection_id, owner) or {}
    placed = [(float((v or {}).get("y", 0) or 0), float((v or {}).get("x", 0) or 0), k)
              for k, v in layout.items() if isinstance(v, dict)]
    return [k for _, _, k in sorted(placed)]


@router.get("/cockpits")
def list_cockpits(request: Request, connection_id: str) -> dict:
    """The asker's cockpits on this connection, the cards they may place, and the canvas
    cockpits waiting to be moved here. No model call, and nothing is written."""
    _on()
    from aughor.cockpit import cards, versions
    from aughor.cockpit.home import FIRST, Home, person_of
    owner = person_of(request)
    home = Home(connection_id, owner, FIRST)
    return {
        "person": owner,
        "cockpits": versions.of_person(connection_id, owner),
        "shared_cards": len(cards.shared(connection_id)),
        "own_cards": len(cards.own(home)),
        "from_canvases": versions.canvas_cockpits(connection_id),
    }


@router.get("/cockpits/{cockpit_id}")
def read_cockpit(request: Request, cockpit_id: str, connection_id: str, preset: Optional[str] = None,
                 start: Optional[str] = None, end: Optional[str] = None,
                 workspace_id: Optional[str] = None) -> dict:
    """One of the asker's cockpits as it stands: its newest version with its spec, every card
    it may place (theirs and the connection's), the range it is read for, and its history."""
    _on()
    from aughor.cockpit import cards, host, versions
    from aughor.kernel.flags import flag_enabled
    home = _home(request, connection_id, cockpit_id)
    kept = versions.latest(home)
    if kept is None:
        raise HTTPException(status_code=404, detail="No such cockpit")
    ranges_on = flag_enabled("briefing.ranges")
    if (preset or start or end) and not ranges_on:
        raise HTTPException(status_code=404, detail="a cockpit for a date range needs the 'briefing.ranges' flag")
    block, why = host.range_state(connection_id, preset, start=_day(start, "start"), end=_day(end, "end"),
                                  workspace_id=workspace_id)
    if block is None:
        raise HTTPException(status_code=422, detail=why)
    return {
        **home.as_params(),
        "cockpit": kept,
        "cards": [{**c.model_dump(), "own": c.scope == cards.OWN} for c in cards.cards_of(home)],
        "range": block,
        "ranges_on": ranges_on,
        "history": versions.history(home),
    }


@router.put("/cockpits/{cockpit_id}")
def keep_cockpit(request: Request, cockpit_id: str, connection_id: str, req: KeepRequest) -> dict:
    """Keep a spec the person wrote — a card moved, a section renamed — as the cockpit's next
    version, or a refusal with the reasons."""
    _on()
    from aughor.cockpit import versions
    from aughor.cockpit.home import approver
    home = _home(request, connection_id, cockpit_id)
    return _answer(versions.keep(home, req.spec, approved_by=approver(home.owner),
                                 source="a person's own hand", note=req.note, written_by_model=False),
                   cockpit_id=home.cockpit_id)


@router.post("/cockpits/start")
def start_first(request: Request, connection_id: str) -> dict:
    """Start "My cockpit" from the cards pinned in the Briefing before cockpits had names, in the
    order the person arranged them. Written by code, kept like any other spec."""
    _on()
    from aughor.cockpit import cards, compose, versions
    from aughor.cockpit.home import FIRST, approver
    home = _home(request, connection_id, FIRST)
    if versions.latest(home) is not None:
        raise HTTPException(status_code=409, detail={
            "status": "refused", "kept": False, "version": None, "artifact_id": "",
            "sentences": ['You already have "My cockpit". Its history is kept; go back to a version from there.']})
    held = cards.cards_of(home)
    if not held:
        raise HTTPException(status_code=422, detail={
            "status": "refused", "kept": False, "version": None, "artifact_id": "",
            "sentences": ["There are no pinned cards to start from. Name an area to draft a cockpit instead."]})
    spec = compose.default_spec("My cockpit", held, order=_layout_order(connection_id, home.owner))
    return _answer(versions.keep(home, spec, approved_by=approver(home.owner),
                                 source="started from the cards pinned in the Briefing",
                                 written_by_model=False),
                   cockpit_id=home.cockpit_id)


@router.post("/cockpits/draft")
def draft_cockpit(request: Request, connection_id: str, req: DraftRequest) -> dict:
    """⚑ Spends model calls. Draft a new cockpit for the area the person named: one short
    model run with the drafting tool alone. What comes back is a proposal to keep or not, or
    the reasons none was drafted — never a cockpit changed."""
    _on()
    from aughor.cockpit.ask import draft_for_area
    from aughor.cockpit.home import person_of
    return draft_for_area(connection_id, person_of(request), req.area, schema=req.schema_name)


@router.post("/cockpits/move")
def move_cockpit(request: Request, connection_id: str, req: MoveRequest) -> dict:
    """Move a canvas's cockpit to the asker's Briefing. One act: the cards it places become
    theirs, its spec their cockpit's first version, and the canvas's is retired with a note."""
    _on()
    from aughor.cockpit.home import person_of
    from aughor.cockpit.move import move_from_canvas
    out = move_from_canvas(req.canvas_id, connection_id=connection_id, owner=person_of(request))
    if not out["moved"]:
        raise HTTPException(status_code=422, detail=out)
    return out


@router.post("/cockpits/{cockpit_id}/restore")
def restore_cockpit(request: Request, cockpit_id: str, connection_id: str, req: RestoreRequest) -> dict:
    """Go back to an earlier version. It is kept again as the newest, checked against the
    cards as they are today."""
    _on()
    from aughor.cockpit import versions
    from aughor.cockpit.home import approver
    home = _home(request, connection_id, cockpit_id)
    return _answer(versions.restore(home, req.version, approved_by=approver(home.owner)),
                   cockpit_id=home.cockpit_id)


@router.post("/cockpits/{cockpit_id}/retire")
def retire_cockpit(request: Request, cockpit_id: str, connection_id: str, req: RetireRequest) -> dict:
    """Retire a cockpit. Its history stays."""
    _on()
    from aughor.cockpit import versions
    from aughor.cockpit.home import approver
    home = _home(request, connection_id, cockpit_id)
    return _answer(versions.retire(home, approved_by=approver(home.owner), note=req.note),
                   cockpit_id=home.cockpit_id)
