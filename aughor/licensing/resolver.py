"""Resolve the active tier and answer capability checks.

Precedence (first match wins):
  1. per-connection `tier` in connection_settings.json (runtime-flippable, no redeploy)
  2. (future) per-workspace tier — the slot is here for SaaS tenancy
  3. the `AUGHOR_TIER` env — the self-host floor; **defaults to `enterprise`** so a fresh
     install behaves exactly as before this layer existed.
"""
from __future__ import annotations

import os
from typing import Optional

from aughor.licensing.capabilities import Capability, Tier, capabilities_for


def _default_tier() -> Tier:
    raw = (os.getenv("AUGHOR_TIER", "enterprise") or "enterprise").strip().lower()
    try:
        return Tier(raw)
    except ValueError:
        return Tier.ENTERPRISE


def resolve_tier(conn_id: Optional[str] = None, workspace_id: Optional[str] = None) -> Tier:
    """The active tier for a connection (or the env default). Never raises — an unknown or
    missing value falls back to the env default, then to enterprise (everything on)."""
    if conn_id:
        try:
            from aughor.db.registry import get_connection_settings
            t = (get_connection_settings(conn_id) or {}).get("tier")
            if t:
                return Tier(str(t).strip().lower())
        except Exception:
            pass
    # workspace_id precedence slot (SaaS tenancy) goes here when workspaces carry a tier.
    return _default_tier()


def has_capability(cap: Capability, *, conn_id: Optional[str] = None,
                   workspace_id: Optional[str] = None) -> bool:
    """True when the resolved tier grants `cap`."""
    return cap in capabilities_for(resolve_tier(conn_id, workspace_id))
