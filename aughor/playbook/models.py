from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel, Field

#: The tag on a play seeded from a KB inflation or deflation cause: a check on the number itself, not a
#: move for the business. Retrieval leaves these plays out unless a caller asks for them.
DATA_QUALITY_TAG = "data quality"


class PlaybookEntry(BaseModel):
    id: str
    source_kb_id: Optional[str] = None        # KB entry that seeded this
    trigger_metric: str                         # snake_case metric name/keyword
    trigger_condition: str                      # human-readable, e.g. "refund_rate above target"
    trigger_operator: Literal["gt", "lt", "eq", "any"] = "any"
    trigger_value: float = 0.0
    recommendation: str
    expected_impact: str = ""
    typical_timeline: str = ""
    owner_role: str = ""
    tags: list[str] = Field(default_factory=list)
    evidence_sources: list[str] = Field(default_factory=list)  # inv_ids where this worked
    historical_success_rate: float = 0.0        # 0–1; updated by outcomes
    status: Literal["active", "deprecated", "draft"] = "draft"
    # ── A data-quality play's own words (IP-1) ─────────────────────────────────
    # The KB cause it checks and the KB's fix for it, verbatim — what a deep analysis lists as a
    # rule-out when this play's metric moves in its direction. "" on every other play.
    cause: str = ""
    fix: str = ""
    # ── Governed-Dive provenance (set by the store; do not hand-edit) ──────────
    version: int = 1                            # bumps each time the play's CONTENT changes
    receipt: str = ""                           # content fingerprint pinning THIS version
    updated_at: str = ""                        # ISO timestamp of the last content change
