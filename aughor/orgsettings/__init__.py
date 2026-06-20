"""Org / workspace settings (identity, localization, appearance).

Hybrid scope (app-wide singleton + per-workspace override) with override-wins
over the inferred BusinessProfile. See ``models.OrgSettings`` and ``store``.
"""
from aughor.orgsettings.models import OrgSettings
from aughor.orgsettings.store import (
    effective_settings,
    load_org_settings,
    org_context,
    resolve_currency,
    resolve_industry,
    save_org_settings,
)

__all__ = [
    "OrgSettings",
    "effective_settings",
    "load_org_settings",
    "save_org_settings",
    "resolve_currency",
    "resolve_industry",
    "org_context",
]
