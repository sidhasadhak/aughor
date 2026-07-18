"""Dashboard-card data model.

A DashboardCard is a user-authored card on the Briefing cockpit. It carries its own grounded
SQL (so it is self-contained and can be re-run + trust-guarded without a join), an opaque
render spec the frontend owns (a subset of the Chart component's props), a refresh record for
delta/trend, optional thresholds (for graduating to a Monitor), and provenance (the finding it
was pinned from + its receipt). `render` is treated as opaque JSON — the frontend owns its
shape, the store round-trips it — exactly as SavedQuery treats `spec`.

Scope decides where a card shows and who owns it: a canvas's own cockpit (`canvas`), a shared
workspace dashboard (`workspace`), or a personal one (`user`); `scope_ref` is the id within
that scope (canvas_id / workspace_id / user_id).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

# ── Enumerated string domains (kept as plain strings for storage simplicity) ──
SCOPES = ("canvas", "workspace", "user")
SOURCES = ("insight", "query_builder", "authored", "watch")
KINDS = ("note", "kpi", "chart", "watch")
CADENCES = ("brief_cycle", "hourly", "daily", "manual")


class CardRefresh(BaseModel):
    """The card's living state: how often it recomputes, and the last two values (for a delta)."""
    cadence: str = "brief_cycle"          # brief_cycle | hourly | daily | manual
    last_run: str = ""                    # ISO timestamp of the last recompute
    last_value: Optional[float] = None    # latest scalar (for a KPI/watch delta)
    prev_value: Optional[float] = None     # the value before that


class CardProvenance(BaseModel):
    """Where the card came from — so every measured card links back to its evidence."""
    insight_id: str = ""                  # the finding/insight it was pinned from (Door 1)
    origin_finding_id: str = ""           # the origin_finding anchor (drill/receipt reuse)
    receipt_ref: str = ""                 # the trust-receipt key proving the number


class DashboardCard(BaseModel):
    id: str = ""
    connection_id: str = ""
    scope: str = "canvas"                 # canvas | workspace | user
    scope_ref: str = ""                   # canvas_id / workspace_id / user_id
    source: str = "authored"              # insight | query_builder | authored | watch
    kind: str = "kpi"                     # note | kpi | chart | watch
    title: str = ""
    sql: str = ""                         # the grounded query (empty for kind=note)
    query_ref: Optional[str] = None       # optional link to a SavedQuery
    render: Dict[str, Any] = Field(default_factory=dict)   # opaque Chart render spec (frontend-owned)
    refresh: CardRefresh = Field(default_factory=CardRefresh)
    thresholds: Dict[str, Any] = Field(default_factory=dict)   # optional → Monitor graduation
    provenance: CardProvenance = Field(default_factory=CardProvenance)
    links: List[str] = Field(default_factory=list)   # related finding/insight ids (graph edges)
    body: str = ""                        # free text (kind=note)
    author: str = ""
    created_at: str = ""
    updated_at: str = ""
