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
from pydantic import BaseModel, ConfigDict, Field

from aughor.dashboard.models import CardProvenance, DashboardCard
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


# ── Door 1: pin a briefing finding as a card ─────────────────────────────────

class PinInsightRequest(BaseModel):
    """Pin the finding `insight_id` (from `connection_id`'s briefing) as a card scoped to
    `scope`/`scope_ref` (e.g. a canvas cockpit)."""
    model_config = ConfigDict(populate_by_name=True)
    connection_id: str
    insight_id: str
    schema_name: Optional[str] = Field(default=None, alias="schema")
    scope: str = "canvas"
    scope_ref: str = ""
    kind: str = "kpi"                 # kpi | chart
    title: Optional[str] = None       # optional override of the finding text


@router.post("/cards/pin-insight", status_code=201)
def pin_insight_route(req: PinInsightRequest) -> dict:
    """Pin a briefing finding as a dashboard card (the "from an insight" door).

    Resolves the finding's grounded SQL from the SAME domain insights the brief is built
    from, RE-RUNS it through the deterministic guard battery (`execute_guarded`) so the
    pinned number carries the same trust guarantee as an AI answer — a query that errors or
    is BLOCKED is refused (422), never stored — then persists a card linked back to the
    source finding + its receipt, plus a live preview and any unrepaired guard caveats.
    """
    from aughor.routers.exploration import _domain_insights_for, _store_key
    from aughor.db.connection import open_connection_for, open_connection_for_with_schema
    from aughor.sql.executor import execute_guarded

    # 1) Resolve the finding (same source as the brief) and require a runnable query.
    by_domain = _domain_insights_for(req.connection_id, req.schema_name)
    insight = next(
        (i for items in by_domain.values() for i in (items or []) if i.get("id") == req.insight_id),
        None,
    )
    if not insight:
        raise HTTPException(status_code=404, detail="Insight not found in this connection's briefing")
    sql = (insight.get("sql") or "").strip()
    if not sql:
        raise HTTPException(status_code=422, detail="This finding has no query to pin (profile-only fact)")

    # 2) Open the (canvas-scoped) connection.
    use_schema = (
        req.schema_name
        if (req.schema_name and _store_key(req.connection_id, req.schema_name) != req.connection_id)
        else None
    )
    try:
        db = (
            open_connection_for_with_schema(req.connection_id, schema_name=use_schema)
            if use_schema else open_connection_for(req.connection_id)
        )
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Connection not found: {e}")

    # 3) Guard-on-write: a leadership dashboard never stores a card it couldn't run cleanly.
    try:
        result = execute_guarded(db, sql, query_id=f"pin:{req.insight_id}", schema=use_schema)
    finally:
        try:
            db.close()
        except Exception:
            pass
    if result.error:
        raise HTTPException(status_code=422, detail=f"Query failed the trust guards, not pinned: {result.error}")

    # 4) Build + store the card, linked to the source finding (graph edge) + its receipt.
    finding = (insight.get("finding") or "").strip()
    title = req.title or finding or "Pinned finding"
    if len(title) > 120:
        title = title[:117].rstrip() + "…"
    saved = upsert_card(DashboardCard(
        connection_id=req.connection_id,
        scope=req.scope,
        scope_ref=req.scope_ref,
        source="insight",
        kind=req.kind,
        title=title,
        sql=sql,
        provenance=CardProvenance(
            insight_id=req.insight_id,
            receipt_ref=f"insight:{req.connection_id}:{req.insight_id}",
        ),
        links=[req.insight_id],
    ))
    return {
        "card": saved.model_dump(),
        "preview": {
            "columns": result.columns or [],
            "rows": [[str(c) for c in r] for r in (result.rows or [])[:20]],
            "row_count": result.row_count,
        },
        "caveats": result.caveats or [],
    }


# ── Run / refresh a card's value ─────────────────────────────────────────────

def _scalar(result) -> Optional[float]:
    """A single numeric cell → the card's tracked value; else None (chart/table card)."""
    if result.error or result.row_count != 1 or len(result.columns or []) != 1:
        return None
    try:
        return float((result.rows or [[None]])[0][0])
    except (TypeError, ValueError, IndexError):
        return None


@router.post("/cards/{card_id}/run")
def run_card_route(card_id: str) -> dict:
    """Recompute a card's value NOW: re-run its SQL through the guard battery and return the
    current result. A single numeric cell is recorded as the card's latest value (rolling the
    previous one into prev_value) so a KPI can show a delta. Guard-on-read keeps a card honest
    even if the underlying data drifted after it was pinned."""
    from aughor.db.connection import open_connection_for
    from aughor.sql.executor import execute_guarded
    from aughor.util.time import now_iso

    card = get_card(card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    if not (card.sql or "").strip():
        return {"columns": [], "rows": [], "row_count": 0, "caveats": [], "error": None,
                "refresh": card.refresh.model_dump()}
    try:
        db = open_connection_for(card.connection_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Connection not found: {e}")
    try:
        result = execute_guarded(db, card.sql, query_id=f"card:{card_id}", schema=None)
    finally:
        try:
            db.close()
        except Exception:
            pass

    scalar = _scalar(result)
    if scalar is not None:
        hist = list(card.refresh.history or [])
        if not hist or hist[-1] != scalar:      # dedupe consecutive equals → a meaningful step series
            hist = (hist + [scalar])[-24:]        # bounded to the last 24 observations
        card = upsert_card(card.model_copy(update={"refresh": card.refresh.model_copy(update={
            "prev_value": card.refresh.last_value,
            "last_value": scalar,
            "last_run": now_iso(),
            "history": hist,
        })}))
    return {
        "columns": result.columns or [],
        "rows": (result.rows or [])[:200],       # raw values so the client can detect a time series
        "row_count": result.row_count,
        "caveats": result.caveats or [],
        "error": result.error,
        "refresh": card.refresh.model_dump(),
    }
