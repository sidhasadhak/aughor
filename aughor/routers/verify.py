"""Human-verdict endpoints (Bet 0, 0-V) — capture accept/correct/reject on a finding.

These verdicts are the non-circular ground truth the trust economy calibrates against
(self-graded confidence is overconfident exactly when wrong). See
docs/DOMAIN_EXPERTISE_PACKS_10X.md §0.7.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from aughor.verify import record_verdict, verdict_stats, list_verdicts

router = APIRouter(tags=["verify"])


class VerdictIn(BaseModel):
    connection_id: str = ""
    investigation_id: str = ""
    verdict: str                      # accept | correct | reject
    note: str = ""
    headline: str = ""


@router.post("/verify/verdict")
def post_verdict(v: VerdictIn):
    """Record a human verdict on an investigation finding."""
    try:
        return record_verdict(
            connection_id=v.connection_id, investigation_id=v.investigation_id,
            verdict=v.verdict, note=v.note, headline=v.headline,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/verify/verdicts/stats")
def get_verdict_stats(connection_id: Optional[str] = None):
    """Verdict counts + acceptance rate for the current org (optionally one connection)."""
    return verdict_stats(connection_id)


@router.get("/verify/verdicts")
def get_verdicts(connection_id: Optional[str] = None, limit: int = 50):
    """Most-recent verdicts for the current org (optionally one connection)."""
    return list_verdicts(connection_id, limit)
