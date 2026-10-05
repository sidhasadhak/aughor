"""EvidenceClaim — a single verifiable claim produced by an investigation."""
from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel, Field
import uuid


from aughor.util.time import now_iso as _now_iso


def _new_id() -> str:
    return str(uuid.uuid4())


class EvidenceClaim(BaseModel):
    """A single verifiable finding produced during an investigation.

    Every claim carries the SQL that produced it, the metric it references and how fresh the
    underlying data was. Claims can be validated or disputed by humans after the fact.

    ``confidence`` is None since phase 1 of the 2027 study (ROADMAP §3.53): the ledger stored 0.8
    or 0.5 by whether a phase called itself significant — a self-reported number wearing a badge.
    Confidence is counted or absent (`aughor/record/claims.py`, law 3); the field stays on the model
    so rows written before the change still read, and nothing writes it now.
    """

    id: str = Field(default_factory=_new_id)
    investigation_id: str
    hypothesis_id: Optional[str] = None       # which hypothesis this finding came from
    claim_text: str                             # "Revenue declined 12% in Q3"
    sql_source: Optional[str] = None           # exact SQL that produced this number
    metric_used: Optional[str] = None          # metric catalog name if applicable
    data_freshness: Optional[str] = None       # ISO timestamp of latest data point used
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)  # None: not counted (see above)
    created_at: str = Field(default_factory=_now_iso)

    # Human-in-the-loop feedback
    owner_feedback: Optional[Literal["validated", "disputed", "needs_context"]] = None
    feedback_note: Optional[str] = None

    # Downstream linkage
    downstream_recommendations: list[str] = Field(default_factory=list)
    outcome_status: Optional[Literal["acted_on", "superseded", "archived"]] = None
