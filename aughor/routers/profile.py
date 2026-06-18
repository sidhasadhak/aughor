"""Business/Industry Profile endpoints — the industry-aware intelligence keystone."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from aughor.profile import store
from aughor.profile.infer import infer_business_profile

router = APIRouter(tags=["profile"])


@router.get("/business-profile")
def get_business_profile(connection_id: str, schema_name: Optional[str] = Query(default=None)):
    """The cached Business Profile for a (connection, schema), with metadata, or
    available=False. A schema selection with no matching profile returns available=False
    (rather than another schema's metrics) so the Briefing's KPI strip and dashboard OBEY
    the schema selector instead of showing stale, wrong-schema figures."""
    raw = store.load_raw(connection_id, schema_name)
    if not raw:
        return {"available": False, "connection_id": connection_id, "schema_name": schema_name}
    return {"available": True, **raw}


@router.post("/business-profile/rebuild")
def rebuild_business_profile(connection_id: str, schema_name: Optional[str] = Query(default=None)):
    """Force-reinfer the profile for a connection (uses the active LLM)."""
    try:
        profile = infer_business_profile(connection_id, schema_name)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Could not infer business profile: {e}")
    return {"ok": True, "connection_id": connection_id, "profile": profile.model_dump()}
