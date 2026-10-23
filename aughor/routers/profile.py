"""Business/Industry Profile endpoints — the industry-aware intelligence keystone."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from aughor.business_profile import store
from aughor.business_profile.infer import infer_business_profile
from aughor.security.authz import connection_owner_guard

#: DATA-06 — every connection a door of this router names belongs to the caller's org (identity on).
router = APIRouter(tags=["profile"], dependencies=[Depends(connection_owner_guard)])


def _profile_currency(connection_id: str, schema_name: Optional[str]) -> dict:
    """The profile's currency PROPOSAL for one dataset, handed to the platform's currency store (which
    may not read the agent's profile itself)."""
    prof = ((store.load_raw(connection_id, schema_name) or {}).get("profile") or {})
    return {"inferred": str(prof.get("currency_code") or "").strip().upper(),
            "profile_confidence": prof.get("confidence")}


class _CurrencyBody(BaseModel):
    #: A three-letter ISO 4217 code a person states for the dataset, or "" to clear it.
    code: str = ""


@router.get("/business-profile/currency")
def get_dataset_currency(connection_id: str, schema_name: Optional[str] = Query(default=None)):
    """The currency one dataset's figures carry, and whose word it is: ``code`` only when a person
    confirmed it (then it labels every figure), ``inferred`` as the profile proposes it, and
    ``status`` confirmed · inferred · unknown. Unconfirmed figures print as plain amounts (2026-10-23)."""
    from aughor.orgsettings import data_currency
    return data_currency(connection_id, schema_name, **_profile_currency(connection_id, schema_name))


@router.put("/business-profile/currency")
def put_dataset_currency(body: _CurrencyBody, connection_id: str,
                         schema_name: Optional[str] = Query(default=None)):
    """A person confirms the dataset's currency — the profile's proposal or another code — or clears it
    with "". Kept with who and when; it then labels every figure read from this dataset."""
    from aughor.orgsettings import confirm_currency
    from aughor.security.authz import caller
    proposal = _profile_currency(connection_id, schema_name)
    try:
        return {**confirm_currency(connection_id, schema_name, body.code, actor=caller(),
                                   inferred=proposal["inferred"]),
                "profile_confidence": proposal["profile_confidence"]}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


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
    # And ship each metric's unit/range text as the RANGE IT STATES (`stated_range`), read by the
    # same `stated_range` the value audit holds the metric to — so the KPI strip formats a figure at
    # the scale its text states and hides it only by a bound that text states, instead of reading
    # the prose with regexes of its own (which held every "ratio" to 0..1 and read '0-1000' as a
    # percent). Serve-time, so a reworded reader reaches the tiles without a re-inference.
    try:
        from aughor.business_profile.validate import stated_range, name_sql_coherent
        for m in (raw.get("profile", {}).get("north_star_metrics") or []):
            kind, lo, hi = stated_range(m.get("unit_or_range", "") or "")
            m["stated_range"] = {"kind": kind, "lo": lo, "hi": hi}
            if (m.get("value_sql") or "").strip():
                ok, _ = name_sql_coherent(m.get("name", ""), m.get("unit_or_range", ""))
                if not ok:
                    m["value_sql"] = ""
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "serve-time metric coherence filter and range reading are best-effort; the raw "
                 "profile is still returned (build-time audit_profile is the primary gate, and a metric "
                 "with no stated_range formats as open — unbounded, never a guessed bound)",
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
