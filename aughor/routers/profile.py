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
    # RC3 — serve-time coherence: blank the value_sql of a category-named metric declared as
    # a scalar percent/ratio ("Top Return Reason 0.4%") so the KPI strip drops it, without
    # waiting for a re-inference. New profiles are already gated at build time (audit_profile).
    try:
        from aughor.profile.validate import name_sql_coherent
        for m in (raw.get("profile", {}).get("north_star_metrics") or []):
            if (m.get("value_sql") or "").strip():
                ok, _ = name_sql_coherent(m.get("name", ""), m.get("unit_or_range", ""))
                if not ok:
                    m["value_sql"] = ""
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "serve-time metric coherence filter is best-effort; the raw profile is "
                 "still returned (build-time audit_profile is the primary gate)",
                 counter="profile.coherence_filter")
    return {"available": True, **raw}


@router.post("/business-profile/rebuild")
def rebuild_business_profile(connection_id: str, schema_name: Optional[str] = Query(default=None)):
    """Force-reinfer the profile for a connection (uses the active LLM)."""
    try:
        profile = infer_business_profile(connection_id, schema_name)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Could not infer business profile: {e}")
    return {"ok": True, "connection_id": connection_id, "profile": profile.model_dump()}
