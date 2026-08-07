"""Human-verdict endpoints (Bet 0, 0-V) — capture accept/correct/reject on a finding.

These verdicts are the non-circular ground truth the trust economy calibrates against
(self-graded confidence is overconfident exactly when wrong). See
docs/DOMAIN_EXPERTISE_PACKS_10X.md §0.7.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from aughor.feedback import record_verdict, verdict_stats, list_verdicts

router = APIRouter(tags=["verify"])


class VerdictIn(BaseModel):
    connection_id: str = ""
    investigation_id: str = ""
    verdict: str                      # accept | correct | reject
    note: str = ""
    headline: str = ""
    # S3 fix-it flow: the SQL that produced the judged answer, and an optional
    # human fix. The store has carried both since P1 — the route just dropped
    # them, so the UI could never deliver the structural payload the planner
    # reads back (dead code at BOTH ends, gap in the middle — the S2 lesson).
    sql_source: str = ""
    corrected_sql: str = ""


@router.post("/verify/verdict")
def post_verdict(v: VerdictIn):
    """Record a human verdict on an investigation finding."""
    try:
        return record_verdict(
            connection_id=v.connection_id, investigation_id=v.investigation_id,
            verdict=v.verdict, note=v.note, headline=v.headline,
            sql_source=v.sql_source, corrected_sql=v.corrected_sql,
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
