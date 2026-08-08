"""Wave N1 — the answer-consistency review surface.

Three routes over :mod:`aughor.semantic.answer_divergence`: what has been answered more than
one way, what that costs when the variants are actually executed, and a human's decision about
which one is right.

Every route is gated on ``consistency.divergence`` (default off ⇒ 404, byte-identical). The
gate is on the ROUTES rather than inside the module because detection is a pure read over
receipts the platform already stores — there is no live-path behaviour to make conditional.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field


router = APIRouter(tags=["consistency"])




class PinIn(BaseModel):
    connection_id: str
    question: str
    sql: str
    tables: list[str] = Field(default_factory=list)
    note: str = ""


@router.get("/consistency/summary")
def consistency_summary(connection_id: str, limit: int = 2000):
    """Headline counts — whether inconsistent answers are a problem on this connection."""
    from aughor.semantic.answer_divergence import summary
    return summary(connection_id, limit=limit)


@router.get("/consistency/divergences")
def list_divergences(connection_id: str, limit: int = 2000,
                     include_exploratory: bool = False,
                     include_settled: bool = False):
    """Recurring questions answered more than one way, most-contested first.

    ``include_exploratory`` adds questions where every run produced a unique query. They are
    excluded by default: those are being explored rather than decided, and asking a reviewer
    to pin one of fifteen one-off queries is asking the wrong question.
    """
    from aughor.semantic.answer_divergence import detect
    divs = detect(connection_id, limit=limit,
                  include_exploratory=include_exploratory,
                  include_settled=include_settled)
    return {"connection_id": connection_id, "count": len(divs),
            "divergences": [d.to_dict() for d in divs]}


@router.get("/consistency/impact")
def divergence_impact(connection_id: str, question_key: str, max_variants: int = 4):
    """Execute one divergence's variants read-only and report whether they actually disagree.

    Separate from the listing on purpose: the listing is free, this costs one bounded query
    per variant. Text over-reports disagreement — on the reference connection 34 textually
    contested questions became 12 genuinely divergent ones — so this is the step that turns
    "the SQL differs" into a number somebody can act on.
    """
    from aughor.semantic.answer_divergence import detect, measure_impact
    divs = detect(connection_id, include_exploratory=True, include_settled=True)
    match = next((d for d in divs if d.question_key == question_key), None)
    if match is None:
        raise HTTPException(status_code=404, detail="No such divergence on this connection")
    return {"divergence": match.to_dict(),
            "impact": measure_impact(match, connection_id,
                                     max_variants=max_variants).to_dict()}


@router.post("/consistency/pin")
def pin_answer(body: PinIn):
    """Record which variant is correct. The warrant becomes "a person decided"."""
    from aughor.semantic.answer_divergence import pin
    tq = pin(body.connection_id, body.question, body.sql,
             tables=body.tables, note=body.note)
    return {"pinned": tq.model_dump()}


@router.get("/consistency/confirmed")
def confirmed_divergences(connection_id: str, max_questions: int = 25,
                          limit: int = 2000):
    """Detection plus execution in one call, ranked by the gap between the answers.

    The expensive-but-honest view: only divergences whose variants genuinely return
    different data, ordered by how much separates them.
    """
    from aughor.semantic.answer_divergence import confirmed
    pairs = confirmed(connection_id, limit=limit, max_questions=max_questions)
    return {"connection_id": connection_id, "count": len(pairs),
            "confirmed": [{"divergence": d.to_dict(), "impact": i.to_dict()}
                          for d, i in pairs]}


__all__ = ["router"]
