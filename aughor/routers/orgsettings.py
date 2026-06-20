"""Org/workspace settings endpoints — app-wide identity, localization, appearance.

The app-level OrgSettings is a singleton; per-workspace overrides are edited via the
workspace router (PUT /workspaces/{id} with settings_override). ``/org-settings/effective``
resolves the two for a workspace (workspace override > app default > model default).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query

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
    payload (currency normalized to a 3-letter ISO 4217 code, fiscal month 1-12)."""
    return save_org_settings(settings).model_dump()


@router.get("/org-settings/effective")
def get_effective_settings(workspace_id: Optional[str] = Query(default=None)):
    """Resolved settings for a workspace: workspace override > app default > model
    default. With no workspace_id, returns the app-level settings as-is."""
    return effective_settings(workspace_id).model_dump()
