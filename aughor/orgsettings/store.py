"""Persistence + resolution for org/workspace settings.

The app-level ``OrgSettings`` is a singleton persisted as JSON in
``data/org_settings.json`` (mirroring the profile store). Per-workspace overrides
live on the Workspace row (``settings_override``). ``effective_settings(workspace_id)``
merges them with precedence: **workspace override > app default > model default**.

``resolve_currency`` / ``resolve_industry`` implement override-wins over the
per-connection ``BusinessProfile``: an explicitly-set org/workspace value is
authoritative; otherwise the inferred value stands.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from aughor.orgsettings.models import OrgSettings

_PATH = Path(__file__).parent.parent.parent / "data" / "org_settings.json"


def load_org_settings() -> OrgSettings:
    """The app-wide settings singleton (model defaults when never configured)."""
    try:
        if _PATH.exists():
            return OrgSettings(**json.loads(_PATH.read_text()))
    except Exception as exc:
        # A malformed/legacy file must not break the app — fall back to defaults.
        from aughor.kernel.errors import tolerate
        tolerate(exc, "org_settings.json unreadable/invalid — using defaults",
                 counter="orgsettings.load_failed")
    return OrgSettings()


def save_org_settings(settings: OrgSettings) -> OrgSettings:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    _PATH.write_text(json.dumps(settings.model_dump(), indent=2))
    return settings


def effective_settings(workspace_id: Optional[str] = None) -> OrgSettings:
    """Resolve effective settings: workspace override > app default > model default.

    Only non-empty override values win, so a workspace that overrides just the
    currency does not blank out the app-level company name, etc.
    """
    base = load_org_settings().model_dump()
    if workspace_id:
        try:
            from aughor.workspace.store import get_workspace

            ws = get_workspace(workspace_id)
            override = (ws.settings_override if ws else {}) or {}
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "workspace settings_override unreadable — using app-level settings",
                     counter="orgsettings.override_read_failed")
            override = {}
        for k, v in override.items():
            if k in base and v not in (None, ""):
                base[k] = v
    return OrgSettings(**base)


def resolve_currency(profile_currency: str = "", workspace_id: Optional[str] = None) -> str:
    """Effective reporting currency: an explicitly-set org/workspace currency is
    authoritative; else the per-connection inferred value; else USD."""
    eff = effective_settings(workspace_id).currency_code
    return eff or (profile_currency or "").strip().upper() or "USD"


def resolve_industry(profile_industry: str = "", workspace_id: Optional[str] = None) -> str:
    """Effective industry: an explicitly-set org/workspace industry is
    authoritative; else the per-connection inferred value."""
    eff = effective_settings(workspace_id).industry
    return eff or (profile_industry or "").strip()


def org_context(workspace_id: Optional[str] = None) -> str:
    """A short 'ORGANIZATION:' block for prompt injection, built only from identity
    the user has EXPLICITLY declared. Returns '' when nothing is set, so callers can
    prepend it unconditionally without polluting prompts for unconfigured orgs."""
    s = effective_settings(workspace_id)
    head = ", ".join(b for b in (s.company_name, f"HQ {s.hq_location}" if s.hq_location else "", s.website) if b)
    tail = []
    if s.industry:
        tail.append(f"industry: {s.industry}")
    if s.currency_code:
        tail.append(f"reports in {s.currency_code}")
    if s.fiscal_year_start_month and s.fiscal_year_start_month != 1:
        tail.append(f"fiscal year starts month {s.fiscal_year_start_month}")
    line = head + ((" — " if head else "") + "; ".join(tail) if tail else "")
    return f"ORGANIZATION: {line}.\n" if line else ""
