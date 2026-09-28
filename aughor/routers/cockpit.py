"""A Data Canvas's cockpit — read it, start it, keep it, go back, retire it (Arc CT, CT-4).

Behind ``cockpit.composed``. Off, every route here answers 404 and nothing else in the
product changes. On, **no route here calls a model**: reading draws what was approved, and
starting a cockpit arranges the canvas's cards by their kind, in code.

Every write goes through ``aughor.cockpit.versions``, so it goes through the validator and
is kept with the name of the person who asked. A refusal is an HTTP error that carries the
validator's own sentences; it is never a 200 with nothing kept.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from aughor.routers.canvas import canvas_owner_guard

router = APIRouter(tags=["cockpit"], dependencies=[Depends(canvas_owner_guard)])

#: What a kept-or-not outcome is to a caller over HTTP.
_STATUS_CODE = {"refused": 422, "not_checked": 503, "failed": 500}


class KeepRequest(BaseModel):
    spec: Any
    note: str = ""


class RestoreRequest(BaseModel):
    version: int


class RetireRequest(BaseModel):
    note: str = ""


def _on() -> None:
    from aughor.kernel.flags import flag_enabled
    if not flag_enabled("cockpit.composed"):
        raise HTTPException(status_code=404, detail="a canvas's cockpit needs the 'cockpit.composed' flag")


def _canvas(canvas_id: str):
    from aughor.canvas.store import get_canvas
    canvas = get_canvas(canvas_id)
    if canvas is None:
        raise HTTPException(status_code=404, detail="Canvas not found")
    return canvas


def _person() -> str:
    """Who is asking, as every approval route names them: the identified user, or "person"
    where identity is off and there is one operator."""
    from aughor.org.context import current_user_id
    uid = current_user_id()
    return f"user:{uid}" if uid else "person"


def _answer(kept) -> dict:
    code = _STATUS_CODE.get(kept.status)
    if code:
        raise HTTPException(status_code=code, detail=kept.as_dict())
    return kept.as_dict()


def _day(value: Optional[str], what: str) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"{what} is an ISO day, e.g. 2026-08-17")


@router.get("/canvases/{canvas_id}/cockpit")
def read_cockpit(canvas_id: str, preset: Optional[str] = None, start: Optional[str] = None,
                 end: Optional[str] = None, workspace_id: Optional[str] = None) -> dict:
    """The canvas's cockpit as it stands: its newest version with its spec (or null when it
    has none), the cards the canvas holds, the range it is read for, and its history.
    No model call, and nothing is written."""
    _on()
    from aughor.cockpit import cards, host, versions
    from aughor.kernel.flags import flag_enabled

    canvas = _canvas(canvas_id)
    conn_id = canvas.primary_connection_id or ""
    ranges_on = flag_enabled("briefing.ranges")
    if (preset or start or end) and not ranges_on:
        raise HTTPException(status_code=404, detail="a cockpit for a date range needs the 'briefing.ranges' flag")
    block, why = host.range_state(conn_id, preset, start=_day(start, "start"), end=_day(end, "end"),
                                  workspace_id=workspace_id)
    if block is None:
        raise HTTPException(status_code=422, detail=why)
    return {
        "canvas_id": canvas_id,
        "connection_id": conn_id,
        "cockpit": versions.latest(canvas_id),
        "cards": [c.model_dump() for c in cards.cards_of(canvas_id)],
        "range": block,
        "ranges_on": ranges_on,
        "history": versions.history(canvas_id),
    }


@router.put("/canvases/{canvas_id}/cockpit")
def keep_cockpit(canvas_id: str, req: KeepRequest) -> dict:
    """Keep a spec a person wrote as this canvas's cockpit: the next version, or a refusal
    with the reasons."""
    _on()
    from aughor.cockpit import versions
    _canvas(canvas_id)
    return _answer(versions.keep(canvas_id, req.spec, approved_by=_person(),
                                 source="a person's own hand", note=req.note,
                                 written_by_model=False))


@router.post("/canvases/{canvas_id}/cockpit/start")
def start_cockpit(canvas_id: str) -> dict:
    """Start a cockpit from the cards this canvas holds, grouped by their kind. Written by
    code, kept like any other spec."""
    _on()
    from aughor.cockpit import cards, compose, versions
    canvas = _canvas(canvas_id)
    held = cards.cards_of(canvas_id)
    if not held:
        raise HTTPException(status_code=422, detail={
            "status": "refused", "kept": False, "version": None, "artifact_id": "",
            "sentences": ["This canvas holds no cards yet. A cockpit is made of cards; add one first."]})
    # The title is the canvas's own name, which a person gave it; the sections' are this code's.
    return _answer(versions.keep(canvas_id, compose.default_spec(canvas.name, held),
                                 approved_by=_person(), source="started from this canvas's cards",
                                 written_by_model=False))


@router.post("/canvases/{canvas_id}/cockpit/restore")
def restore_cockpit(canvas_id: str, req: RestoreRequest) -> dict:
    """Go back to an earlier version. It is kept again as the newest, checked against the
    canvas as it is today."""
    _on()
    from aughor.cockpit import versions
    _canvas(canvas_id)
    return _answer(versions.restore(canvas_id, req.version, approved_by=_person()))


@router.post("/canvases/{canvas_id}/cockpit/retire")
def retire_cockpit(canvas_id: str, req: RetireRequest) -> dict:
    """Retire this canvas's cockpit. Its history stays."""
    _on()
    from aughor.cockpit import versions
    _canvas(canvas_id)
    return _answer(versions.retire(canvas_id, approved_by=_person(), note=req.note))
