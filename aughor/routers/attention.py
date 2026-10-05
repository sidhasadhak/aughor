"""The attention budget's doors (the 2027 study §I; phase 2, P2-2) — the four ranking terms
published, each addressee's slots and what was held this week, and the slots a person sets.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from aughor.govern import attention as A
from aughor.security.authz import get_principal

router = APIRouter(tags=["attention"])


@router.get("/attention/terms")
def get_terms() -> dict:
    """The four triage terms, their weights and how each is read today — published so the
    hand-set weights can be argued with and moved."""
    return {"terms": list(A.TERMS), "default_slots_per_week": A.DEFAULT_SLOTS_PER_WEEK,
            "held_state": A.HELD_BUDGET,
            "note": ("a departure arrives one at a time, so the score cannot reorder what already left; "
                     "it rides every row and every hold, and a held row scoring above a departed one is the "
                     "measurement that moves the weights or the slots")}


@router.get("/attention/budget")
def get_budget(addressee: str = Query(..., description="a target (a channel) or a person the gate addresses")) -> dict:
    return A.budget_view(addressee)


@router.get("/attention/held")
def get_held(addressee: Optional[str] = None, limit: int = 100) -> dict:
    """What the budget held this week and why, newest first — the list, never a silence."""
    return {"week_start": A.week_start()[:10],
            "held": A.held_this_week(addressee, limit=max(1, min(int(limit), 500)))}


class SlotsBody(BaseModel):
    addressee: str
    slots: int


@router.post("/attention/slots")
def post_slots(body: SlotsBody, principal=Depends(get_principal)) -> dict:
    """A person sets an addressee's slots a week (0 holds everything unattended to that place)."""
    try:
        n = A.set_slots(body.addressee, body.slots)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return A.budget_view(body.addressee) | {"set_to": n}
