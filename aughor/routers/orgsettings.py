"""Org/workspace settings endpoints — app-wide identity, localization, appearance.

The app-level OrgSettings is a singleton; per-workspace overrides are edited via the
workspace router (PUT /workspaces/{id} with settings_override). ``/org-settings/effective``
resolves the two for a workspace (workspace override > app default > model default).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from aughor.licensing import Capability, gate
from aughor.orgsettings import effective_settings, load_org_settings, save_org_settings
from aughor.orgsettings.models import OrgSettings
from aughor.security.authz import connection_owner_guard

#: DATA-06 — every connection a door of this router names belongs to the caller's org (identity on).
router = APIRouter(tags=["settings"], dependencies=[Depends(connection_owner_guard)])


@router.get("/org-settings")
def get_org_settings():
    """The app-wide organization settings singleton (model defaults when unconfigured)."""
    return load_org_settings().model_dump()


@router.put("/org-settings")
def put_org_settings(settings: OrgSettings):
    """Replace the app-wide organization settings. The OrgSettings model validates the
    payload (currency normalized to a 3-letter ISO 4217 code, fiscal month 1-12).

    When the declared INDUSTRY changes to a new non-empty value, every stored business
    profile is invalidated so each dataset re-infers against the selected industry's
    curated KB on next access — "pick an industry → its intelligence is captured" without
    a manual rebuild. (Clearing the industry back to "" keeps the inferred profiles.)"""
    prev = load_org_settings()
    saved = save_org_settings(settings)
    new_ind = (saved.industry or "").strip().lower()
    if new_ind and new_ind != (prev.industry or "").strip().lower():
        from aughor.business_profile import store as _pstore
        from aughor.kernel.errors import tolerate
        try:
            n = _pstore.invalidate_all()
            import logging
            logging.getLogger(__name__).info(
                "[org-settings] industry → %r; invalidated %d profile(s) for re-capture",
                saved.industry, n)
        except Exception as e:
            tolerate(e, "industry-change profile invalidation is best-effort",
                     counter="orgsettings.industry_invalidate")
    return saved.model_dump()


# ── IP-2 — the industries chosen at install ─────────────────────────────────────────
# Deployment-wide, like the install that first asked: one file (aughor/packs/industry_choice.py) the
# installer, `aughor industries` and this screen all write.

class ShippedIndustryOut(BaseModel):
    id: str
    name: str
    title: str = ""
    description: str = ""


class IndustryChoiceOut(BaseModel):
    """The industry packages this deployment ships, and the ones it reads."""
    #: None keeps every industry, detected per connection; a list keeps those (none is a choice too).
    industries: Optional[list[str]] = None
    source: str = ""
    updated_at: str = ""
    #: Chosen ids no shipped package carries any more — ignored.
    ignored: list[str] = []
    #: Why the stored choice could not be read, when it could not.
    problem: str = ""
    shipped: list[ShippedIndustryOut] = []
    #: Business profiles dropped by this change because their industry now resolves differently —
    #: each is rebuilt, with a model call, the next time its data is used.
    profiles_refreshed: int = 0


class IndustryChoiceIn(BaseModel):
    industries: Optional[list[str]] = None


def _industry_choice_out(choice, refreshed: int = 0) -> IndustryChoiceOut:
    from aughor.packs.industry_choice import shipped_industries
    return IndustryChoiceOut(
        industries=list(choice.industries) if choice.industries is not None else None,
        source=choice.source, updated_at=choice.updated_at, ignored=list(choice.ignored),
        problem=choice.problem, profiles_refreshed=refreshed,
        shipped=[ShippedIndustryOut(id=i.id, name=i.name, title=i.title, description=i.description)
                 for i in shipped_industries()])


@router.get("/org-settings/industries", response_model=IndustryChoiceOut)
def get_industry_choice():
    """IP-2 — the shipped industry packages and which of them this deployment reads."""
    from aughor.packs.industry_choice import read_choice
    return _industry_choice_out(read_choice())


@router.put("/org-settings/industries", response_model=IndustryChoiceOut)
def put_industry_choice(body: IndustryChoiceIn):
    """IP-2 — choose the industry packages this deployment reads: null for every industry (each
    connection's detected on its own), else the ids to keep. A stored business profile whose industry
    now resolves to a different package is dropped so it re-infers on next use; the rest are kept."""
    from aughor.business_profile.metric_kb import refresh_profiles_for_choice
    from aughor.packs.industry_choice import UnknownIndustry, read_choice, write_choice

    before = read_choice()
    try:
        after = write_choice(body.industries, source="settings")
    except UnknownIndustry as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    refreshed = 0
    if before.industries != after.industries:
        try:
            refreshed = refresh_profiles_for_choice(before.industries, after.industries)
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "profile refresh after an industry choice is best-effort; stale profiles "
                          "re-resolve when they are next rebuilt", counter="orgsettings.industry_choice_refresh")
    return _industry_choice_out(after, refreshed)


@router.get("/org-settings/effective")
def get_effective_settings(workspace_id: Optional[str] = Query(default=None)):
    """Resolved settings for a workspace: workspace override > app default > model
    default. With no workspace_id, returns the app-level settings as-is."""
    return effective_settings(workspace_id).model_dump()


# ── CI-5b — org-scoped BYOK (the org's own provider keys + per-role models) ────────
#
# Deliberately NOT the deployment's POST /llm/config: that path reloads every cached
# provider in the process — the reload that cancels a running exploration. These
# endpoints write one org's store row and move only that org's cache fingerprint;
# every other tenant's in-flight work never notices.

class _OrgLLMPatch(BaseModel):
    backend: Optional[str] = None       # "" clears back to the deployment default
    models: Optional[dict] = None       # {coder?, narrator?, fast?}   ("" clears)
    keys: Optional[dict] = None         # {openrouter?, anthropic?, …} ("" clears, masked = unchanged)
    allow_paid: Optional[bool] = None   # paid OpenRouter models must be deliberate


@router.get("/org-settings/llm")
def get_org_llm():
    """The current org's BYOK binding — backend, per-role models, which keys are SET.
    Key values never leave the server, masked or otherwise."""
    from aughor.llm.org_config import describe_org_config
    from aughor.org.context import current_org_id
    return describe_org_config(current_org_id())


@router.put("/org-settings/llm", dependencies=[gate(Capability.SECURITY_SUITE)])
def put_org_llm(patch: _OrgLLMPatch):
    """Merge a partial BYOK config for the current org. Gated like the deployment
    config (SEC-10): keys and model bindings are admin-grade — an ungated caller
    could pivot a tenant's inference to an attacker endpoint."""
    from aughor.llm.org_config import save_org_config
    from aughor.org.context import current_org_id
    try:
        return save_org_config(current_org_id(), patch.model_dump(exclude_none=True))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/org-settings/llm", dependencies=[gate(Capability.SECURITY_SUITE)])
def delete_org_llm():
    """Drop the org's BYOK row entirely — it falls back to the deployment binding."""
    from aughor.llm.org_config import clear_org_config, describe_org_config
    from aughor.org.context import current_org_id
    clear_org_config(current_org_id())
    return describe_org_config(current_org_id())
