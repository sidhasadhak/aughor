"""Governance surface (Wave G3) — usage attribution and the unified audit feed.

Read-only. Both endpoints report over stores that already exist; nothing here writes, and
neither costs a warehouse query or a model call.

Authorization rides the existing declarative table in ``aughor/rbac/policy.py`` rather
than a decorator here — that table is the auditable map of the whole surface, and a route
that gated itself would be invisible to anyone reading it.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(tags=["governance"])


@router.get("/usage")
def get_usage(
    by: str = Query(default="provider,model",
                    description="Comma-separated axes: provider, model, feature, "
                                "org_id, user_id, conn_id"),
    scan: int = Query(default=5000, ge=1, le=100_000),
    org_id: Optional[str] = None,
):
    """Model usage and cost, grouped by the requested axes.

    The response carries ``unattributed`` and ``coverage`` per axis alongside the rows.
    That is not padding: ``user_id`` is 0% populated in local mode, and a page that folded
    those into one blank-named group would present it as a real cohort. Cost likewise
    reports ``cost_is_complete`` — a model with no declared price contributes nothing to
    the total rather than being counted as free.
    """
    from aughor.obs.usage import AXES, usage_report

    axes = tuple(a.strip() for a in (by or "").split(",") if a.strip())
    if not axes:
        raise HTTPException(status_code=400, detail="`by` needs at least one axis")
    if unknown := [a for a in axes if a not in AXES]:
        raise HTTPException(
            status_code=400,
            detail=f"unknown axis/axes {unknown}; known: {sorted(AXES)}")
    return usage_report(axes=axes, org_id=org_id, scan=scan).to_dict()


@router.get("/usage/cost-sql")
def get_cost_sql():
    """The copy-pasteable cost query against our own session log.

    Served rather than only documented so it stays the same string the module computes
    from — `aughor_ops` reads that table directly, and an agent writing its own SQL needs
    column names that are real today, not as of whenever a doc was last edited.
    """
    from aughor.obs.usage import COST_SQL

    return {"sql": COST_SQL, "table": "session_events", "kind": "llm_call"}


@router.get("/audit/feed")
def get_audit_feed(
    category: Optional[str] = Query(default=None,
                                    description="data_access | governance_change | "
                                                "action_decision | model_call | "
                                                "human_verdict"),
    limit: int = Query(default=100, ge=1, le=1000),
):
    """Governance events across every audit sink, newest first.

    Five sinks record governance-relevant events and none knows about the others; this
    reads them under one category vocabulary. An unknown category is a 400 rather than an
    empty list — "no events" and "that category does not exist" are different answers.
    """
    from aughor.govern.audit_categories import CATEGORIES, feed

    try:
        events = feed(category=category, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"categories": list(CATEGORIES), "category": category,
            "count": len(events), "events": [e.to_dict() for e in events]}


@router.get("/governance/tags")
def get_governed_tags(key: str | None = None, securable_prefix: str | None = None,
                      limit: int = 200):
    """Browse the G2 governed-tag plane (read-only). S1/J13: the governance axis
    was write-only — tags existed in the store with no route and no UI, so a
    'Certified' securable could never LOOK certified. Writes stay with the
    clearance machinery; this is the render path."""
    from dataclasses import asdict

    from aughor.govern.tag_store import list_tags
    return [asdict(t) for t in
            list_tags(key=key, securable_prefix=securable_prefix, limit=limit)]
