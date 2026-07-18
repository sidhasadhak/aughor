"""Dashboard-card CRUD — the standing (cockpit) layer of the Briefing.

Slice 0 of the briefing-cockpit initiative (docs/BRIEFING_COCKPIT_2026-07-18.md): a thin,
scope-filtered CRUD over the dashboard-card store, exposing the primitive. Deliberately
DEFERRED to later slices (kept out of scope here): RBAC scope enforcement, running a
user-authored card's SQL through the guard battery (execute_guarded) on write, and the
pin-from-insight / Query-Builder convenience doors that compose this primitive.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException

from aughor.dashboard.models import DashboardCard
from aughor.dashboard.store import delete_card, get_card, list_cards, upsert_card

router = APIRouter(tags=["dashboard"])


@router.get("/cards")
def list_cards_route(
    connection_id: Optional[str] = None,
    scope: Optional[str] = None,
    scope_ref: Optional[str] = None,
) -> list[dict]:
    """Cards matching the filters (any left unset is ignored), newest-updated first.
    Fetch a canvas cockpit with `?scope=canvas&scope_ref=<canvas_id>`."""
    return [
        c.model_dump()
        for c in list_cards(connection_id=connection_id, scope=scope, scope_ref=scope_ref)
    ]


@router.get("/cards/{card_id}")
def get_card_route(card_id: str) -> dict:
    c = get_card(card_id)
    if not c:
        raise HTTPException(status_code=404, detail="Card not found")
    return c.model_dump()


@router.post("/cards", status_code=201)
def create_card_route(card: DashboardCard) -> dict:
    # The store owns id + timestamps; ignore any client-supplied values.
    card = card.model_copy(update={"id": "", "created_at": "", "updated_at": ""})
    return upsert_card(card).model_dump()


@router.put("/cards/{card_id}")
def update_card_route(card_id: str, card: DashboardCard) -> dict:
    if not get_card(card_id):
        raise HTTPException(status_code=404, detail="Card not found")
    return upsert_card(card.model_copy(update={"id": card_id})).model_dump()


@router.delete("/cards/{card_id}", status_code=204)
def delete_card_route(card_id: str) -> None:
    if not delete_card(card_id):
        raise HTTPException(status_code=404, detail="Card not found")
