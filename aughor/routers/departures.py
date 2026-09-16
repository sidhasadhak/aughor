"""HB-2 — the departures ledger's doors: what left, what was held and why, the
declarer's verdict, and graduation.

The probation loop lives here: a held-probation departure is reviewed on the screen
(never re-sent by this router — the ledger is the declarer's queue, not a second
transport), the declarer marks it accept / correct / reject, and at measured precision
(``govern/departure.py``'s thresholds) the automation graduates — its next departures
reach the channel. Marks are also the wave's contribution to MI-1's graded ledger: a
departure that carries an ``investigation_id`` forwards its verdict into the feedback
plane, so the same mark teaches the model's ledger and the probation ratchet at once.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from aughor.govern.departure import GRADUATION_MIN_MARKED, GRADUATION_PRECISION
from aughor.govern.departure_store import (
    get_departure,
    list_departures,
    mark_departure,
    precision_for,
)

router = APIRouter(tags=["departures"])


@router.get("/departures")
def get_departures(state: Optional[str] = Query(default=None),
                   automation_id: Optional[str] = Query(default=None),
                   limit: int = Query(default=50, ge=1, le=500)):
    """The ledger, newest first — departed and held rows alike, reasons and checks
    verbatim (the receipt that travels, readable where it was recorded)."""
    return {"departures": list_departures(state=state, automation_id=automation_id,
                                          limit=limit)}


@router.get("/departures/{departure_id}")
def get_one(departure_id: str):
    row = get_departure(departure_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Departure not found")
    return row


class VerdictBody(BaseModel):
    verdict: str
    note: str = ""


@router.post("/departures/{departure_id}/verdict")
def mark(departure_id: str, body: VerdictBody):
    """The declarer's mark on one departure — accept / correct / reject.

    Forwards into the feedback plane when the departure carries an investigation id
    (one mark, both ledgers), then re-measures the automation's precision and
    graduates it the moment the threshold holds — "graduates at a measured
    precision", literally at the moment of the measurement that satisfies it."""
    verdict = body.verdict.strip().lower()
    if verdict not in ("accept", "correct", "reject"):
        raise HTTPException(status_code=422,
                            detail="verdict must be accept, correct or reject")
    row = mark_departure(departure_id, verdict, note=body.note.strip())
    if row is None:
        raise HTTPException(status_code=404, detail="Departure not found")

    if row.get("investigation_id"):
        try:
            from aughor.feedback.verdicts import record_verdict
            record_verdict(connection_id=row.get("conn_id", ""),
                           investigation_id=row["investigation_id"],
                           verdict=verdict, note=body.note.strip(),
                           headline=(row.get("text_preview") or "")[:200])
        except Exception:
            # The departure mark stands on its own; the feedback forward is a bonus,
            # not a dependency — a broken second ledger must not lose the first mark.
            import logging
            logging.getLogger(__name__).warning(
                "departure verdict recorded, feedback-plane forward failed", exc_info=True)

    graduated = False
    stats = {}
    if row.get("automation_id"):
        stats = precision_for(row["automation_id"])
        if (stats["marked"] >= GRADUATION_MIN_MARKED
                and (stats["precision"] or 0.0) >= GRADUATION_PRECISION):
            from aughor.automations.store import get_automation, set_probation
            auto = get_automation(row["automation_id"])
            if auto is not None and auto.probation:
                set_probation(row["automation_id"], False)
                graduated = True
    return {"departure": row, "precision": stats, "graduated": graduated}


@router.get("/departures/precision/{automation_id}")
def get_precision(automation_id: str):
    """The measured departure precision one automation has earned — the number
    graduation reads, published so probation is never a mystery state."""
    stats = precision_for(automation_id)
    stats["graduates_at"] = {"min_marked": GRADUATION_MIN_MARKED,
                             "precision": GRADUATION_PRECISION}
    return stats


@router.post("/automations/{automation_id}/graduate")
def graduate(automation_id: str):
    """Take an automation off probation by hand — the declarer's override. The measured
    path (verdicts crossing the threshold) is the intended door; this one exists
    because a person outranks a threshold about their own automation."""
    from aughor.automations.store import get_automation, set_probation
    auto = get_automation(automation_id)
    if auto is None:
        raise HTTPException(status_code=404, detail="Automation not found")
    if not auto.probation:
        return {"automation_id": automation_id, "probation": False,
                "message": "already graduated"}
    set_probation(automation_id, False)
    return {"automation_id": automation_id, "probation": False,
            "message": "graduated by hand", "precision": precision_for(automation_id)}
