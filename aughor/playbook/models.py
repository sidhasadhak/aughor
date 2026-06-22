from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel, Field


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
    # ── Governed-Dive provenance (set by the store; do not hand-edit) ──────────
    version: int = 1                            # bumps each time the play's CONTENT changes
    receipt: str = ""                           # content fingerprint pinning THIS version
    updated_at: str = ""                        # ISO timestamp of the last content change
