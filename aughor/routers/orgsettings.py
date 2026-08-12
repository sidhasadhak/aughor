"""Org/workspace settings endpoints — app-wide identity, localization, appearance.

The app-level OrgSettings is a singleton; per-workspace overrides are edited via the
workspace router (PUT /workspaces/{id} with settings_override). ``/org-settings/effective``
resolves the two for a workspace (workspace override > app default > model default).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from aughor.licensing import Capability, gate
from aughor.orgsettings import effective_settings, load_org_settings, save_org_settings
from aughor.orgsettings.models import OrgSettings

router = APIRouter(tags=["settings"])


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
