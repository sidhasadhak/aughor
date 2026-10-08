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

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import Response
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


class AskRequest(BaseModel):
    words: str
    schema_name: Optional[str] = None


class PublishRequest(BaseModel):
    """Who the cockpit is published to: groups and roles, each by kind and id or name."""
    to: list[dict[str, Any]]


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


def _approved_by(request: Request) -> str:
    """Who approves a version: the person signed in, else the one this request acts for. It was the
    home's owner, which without a sign-in is nobody in particular and wrote the bare word "person"."""
    from aughor.security.authz import acting_person, caller, get_principal
    return acting_person(get_principal(request)) or f"user:{caller()}"


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


def _as_read(card, connection_id: str) -> dict:
    """A card as a cockpit draws it: the card, whose it is, the record it was made from, and —
    for a card made from a metric — the metric's unit and the range that unit states, read by
    the same reader the Briefing's figures are (`business_profile/validate.stated_range`)."""
    from aughor.business_profile.validate import stated_range
    from aughor.cockpit import cards
    from aughor.cockpit.propose import made_from
    from aughor.semantic.metrics import get_metric

    made = made_from(card)
    out = {**card.model_dump(), "own": card.scope == cards.OWN, "made_from": made[0] if made else "",
           "unit": "", "stated_range": None}
    if made and made[0] == "metric":
        metric = get_metric(made[1], connection_id=connection_id)
        unit = str(getattr(metric, "unit", "") or "")
        if unit:
            kind, lo, hi = stated_range(unit)
            out.update(unit=unit, stated_range={"kind": kind, "lo": lo, "hi": hi})
    return out


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


@router.get("/cockpits/audiences")
def audiences(request: Request, connection_id: str) -> dict:
    """The groups the asker belongs to and the roles they hold: who they may publish a cockpit to
    (the canvas, B5). Declared before the cockpit-by-id read, which would take the word for an id."""
    _on()
    from aughor.cockpit import sharing
    from aughor.cockpit.home import person_of
    return sharing.audience_of(person_of(request))


@router.get("/cockpits/shared")
def shared_cockpits(request: Request, connection_id: str) -> dict:
    """The cockpits others published to a group the asker is in or a role they hold."""
    _on()
    from aughor.cockpit import sharing
    from aughor.cockpit.home import person_of
    return {"cockpits": sharing.shared_with(connection_id, person_of(request))}


@router.get("/cockpits/shared/{owner}/{cockpit_id}")
def read_shared_cockpit(request: Request, owner: str, cockpit_id: str, connection_id: str,
                        preset: Optional[str] = None, start: Optional[str] = None, end: Optional[str] = None,
                        workspace_id: Optional[str] = None) -> dict:
    """A published cockpit as it stands, for a reader it reaches: read-only, for the reader's own
    period; a card the reader may not read stands and says so."""
    _on()
    from aughor.cockpit import cards, host, images, sharing
    from aughor.cockpit.home import person_of
    from aughor.kernel.flags import flag_enabled
    from aughor.routers.investigations import resolve_currency_symbol
    try:
        got = sharing.read_shared(connection_id, owner, cockpit_id, reader=person_of(request))
    except sharing.Refused as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    home, kept = got["home"], got["cockpit"]
    ranges_on = flag_enabled("briefing.ranges")
    block, why = host.range_state(connection_id, preset if ranges_on else None,
                                  start=_day(start, "start") if ranges_on else None,
                                  end=_day(end, "end") if ranges_on else None, workspace_id=workspace_id)
    if block is None:
        raise HTTPException(status_code=422, detail=why)
    return {
        **home.as_params(),
        "cockpit": kept,
        "cards": [_as_read(c, connection_id) for c in cards.cards_of(home)],
        "range": block,
        "ranges_on": ranges_on,
        "currency_symbol": resolve_currency_symbol(connection_id, None),
        "images": images.stamps_for(connection_id, kept.get("spec")),
        "published_by": kept.get("published_by") or "",
        "published_to": kept.get("published_to") or [],
    }


@router.post("/cockpits/shared/{owner}/{cockpit_id}/copy")
def copy_shared_cockpit(request: Request, owner: str, cockpit_id: str, connection_id: str) -> dict:
    """Start a cockpit of the asker's own from a published one: the publisher's cards copied into
    theirs, the spec kept as the new cockpit's first version. The publisher's is untouched."""
    _on()
    from aughor.cockpit import sharing
    from aughor.cockpit.home import person_of
    try:
        out = sharing.copy_for(connection_id, owner, cockpit_id, reader=person_of(request),
                               approved_by=_approved_by(request))
    except sharing.Refused as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _answer(out["kept"], cockpit_id=out["cockpit_id"], title=out["title"])


@router.get("/cockpits/{cockpit_id}")
def read_cockpit(request: Request, cockpit_id: str, connection_id: str, preset: Optional[str] = None,
                 start: Optional[str] = None, end: Optional[str] = None,
                 workspace_id: Optional[str] = None) -> dict:
    """One of the asker's cockpits as it stands: its newest version with its spec, every card
    it may place (theirs and the connection's), the range it is read for, and its history."""
    _on()
    from aughor.cockpit import cards, host, images, versions
    from aughor.kernel.flags import flag_enabled
    from aughor.routers.investigations import resolve_currency_symbol
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
    held = cards.cards_of(home)
    withheld = cards.not_offered(home, held, kept.get("cards") or [])
    return {
        **home.as_params(),
        "cockpit": kept,
        "cards": [{**_as_read(c, connection_id), "not_offered": withheld.get(c.id, "")} for c in held],
        "range": block,
        "ranges_on": ranges_on,
        "history": versions.history(home),
        "currency_symbol": resolve_currency_symbol(connection_id, None),
        # What the spec's images are, from the volume's own rows; one the cockpit may not show says why.
        "images": images.stamps_for(connection_id, kept.get("spec")),
    }


@router.post("/cockpits/images")
async def upload_image(request: Request, connection_id: str, file: UploadFile) -> dict:
    """Take an image into this connection's cockpit volume — PNG, JPEG, GIF, WebP or SVG, up to
    5 MB, read from its bytes — to be placed on a cockpit by the object id this answers with.
    By hand only: no model uploads an image."""
    _on()
    from aughor.cockpit import images
    data = await file.read()
    try:
        return images.put_image(connection_id, file.filename or "image", data, file.content_type or "",
                                uploaded_by=_approved_by(request))
    except images.Refused as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/cockpits/images/{object_id}")
def read_image(request: Request, object_id: str, connection_id: str) -> Response:
    """An image a cockpit on this connection places, as bytes, with the reader's own access."""
    _on()
    from aughor.cockpit import images
    try:
        data, content_type = images.read_image(connection_id, object_id)
    except images.Refused as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    headers = {"Content-Disposition": "inline", "X-Content-Type-Options": "nosniff",
               "Cache-Control": "private, max-age=3600"}
    if content_type == "image/svg+xml":
        # Drawn in an <img>, nothing in it runs; opened on its own, this says the same.
        headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
    return Response(content=data, media_type=content_type, headers=headers)


@router.put("/cockpits/{cockpit_id}")
def keep_cockpit(request: Request, cockpit_id: str, connection_id: str, req: KeepRequest) -> dict:
    """Keep a spec the person wrote — a card moved, a section renamed — as the cockpit's next
    version, or a refusal with the reasons."""
    _on()
    from aughor.cockpit import versions
    home = _home(request, connection_id, cockpit_id)
    return _answer(versions.keep(home, req.spec, approved_by=_approved_by(request),
                                 source="a person's own hand", note=req.note, written_by_model=False),
                   cockpit_id=home.cockpit_id)


@router.post("/cockpits/start")
def start_first(request: Request, connection_id: str) -> dict:
    """Start "My cockpit" from the cards pinned in the Briefing before cockpits had names, in the
    order the person arranged them. Written by code, kept like any other spec."""
    _on()
    from aughor.cockpit import cards, compose, versions
    from aughor.cockpit.home import FIRST
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
    return _answer(versions.keep(home, spec, approved_by=_approved_by(request),
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


@router.post("/cockpits/{cockpit_id}/ask")
def ask_cockpit(request: Request, cockpit_id: str, connection_id: str, req: AskRequest) -> dict:
    """⚑ Spends model calls. A change to one of the asker's cockpits, asked for in words — add a
    finding, move or resize an element, take a note off, share it with a team. One short model
    run with the drafting tool alone; what comes back is a proposal to keep or not."""
    _on()
    from aughor.cockpit.ask import edit_in_words
    from aughor.cockpit.home import person_of
    home = _home(request, connection_id, cockpit_id)
    return edit_in_words(connection_id, person_of(request), home.cockpit_id, req.words, schema=req.schema_name)


@router.post("/cockpits/{cockpit_id}/publish")
def publish_cockpit(request: Request, cockpit_id: str, connection_id: str, req: PublishRequest) -> dict:
    """Publish the cockpit as it stands to groups the asker belongs to and roles they may publish
    to. A version, under their name; a reader sees it under "Shared with you"."""
    _on()
    from aughor.cockpit import sharing, versions
    from aughor.cockpit.home import person_of
    home = _home(request, connection_id, cockpit_id)
    targets: list[dict] = []
    for raw in req.to:
        hit, why = sharing.may_publish_to(person_of(request), raw)
        if hit is None:
            raise HTTPException(status_code=422, detail={"status": "refused", "kept": False, "version": None,
                                                         "artifact_id": "", "sentences": [why]})
        if hit not in targets:
            targets.append(hit)
    if not targets:
        raise HTTPException(status_code=422, detail={"status": "refused", "kept": False, "version": None,
                                                     "artifact_id": "", "sentences": ["Name a group or a role to publish to."]})
    return _answer(versions.publish(home, targets, approved_by=_approved_by(request)), cockpit_id=home.cockpit_id)


@router.post("/cockpits/{cockpit_id}/unpublish")
def unpublish_cockpit(request: Request, cockpit_id: str, connection_id: str) -> dict:
    """Stop sharing a cockpit. A version too: its history says when it reached whom."""
    _on()
    from aughor.cockpit import versions
    home = _home(request, connection_id, cockpit_id)
    return _answer(versions.publish(home, [], approved_by=_approved_by(request)), cockpit_id=home.cockpit_id)


@router.post("/cockpits/{cockpit_id}/restore")
def restore_cockpit(request: Request, cockpit_id: str, connection_id: str, req: RestoreRequest) -> dict:
    """Go back to an earlier version. It is kept again as the newest, checked against the
    cards as they are today."""
    _on()
    from aughor.cockpit import versions
    home = _home(request, connection_id, cockpit_id)
    return _answer(versions.restore(home, req.version, approved_by=_approved_by(request)),
                   cockpit_id=home.cockpit_id)


@router.post("/cockpits/{cockpit_id}/retire")
def retire_cockpit(request: Request, cockpit_id: str, connection_id: str, req: RetireRequest) -> dict:
    """Retire a cockpit. Its history stays."""
    _on()
    from aughor.cockpit import versions
    home = _home(request, connection_id, cockpit_id)
    return _answer(versions.retire(home, approved_by=_approved_by(request), note=req.note),
                   cockpit_id=home.cockpit_id)
