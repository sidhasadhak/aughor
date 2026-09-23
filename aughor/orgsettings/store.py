"""Persistence + resolution for org/workspace settings.

The app-level ``OrgSettings`` is a singleton persisted as JSON in
``data/org_settings.json`` (mirroring the profile store). Per-workspace overrides
live on the Workspace row (``settings_override``). ``effective_settings(workspace_id)``
merges them with precedence: **workspace override > app default > model default**.

``resolve_industry`` implements override-wins over the inference; ``resolve_currency``
deliberately does NOT — a currency is a property of the figure, not of the reader, and
nothing here converts. See its docstring. Otherwise, override-wins over the
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
            if k in base and v not in (None, "", []):    # an empty list inherits too (CB-6 priorities)
                base[k] = v
    return OrgSettings(**base)


def resolve_currency(profile_currency: str = "", workspace_id: Optional[str] = None) -> str:
    """The currency a FIGURE from this data is denominated in — the data's own, else the
    org's declared reporting currency, else USD.

    This order is the reverse of `resolve_industry` below, and deliberately so.

    A currency symbol in front of a number is not a preference. It is a claim about what
    that number IS, and it is only true if the number is in that currency. **Nothing in
    this tree converts anything** — `grep` for an exchange rate finds two comments in the
    profiler about column NAMING and no converter at all. So applying a declared reporting
    currency to a warehouse value does not report it in that currency; it relabels it, and
    the figure is then wrong by whatever the rate happens to be.

    Measured 2026-09-23: theLook, a USD dataset, rendered revenue axes and prose in EUR
    because the workspace declares EUR — a real chart went to a real Slack channel reading
    "€20.0K" over dollars. The answer beside it even said it had applied no conversion.

    The org setting keeps every meaning it was given that does not require converting
    anything: `org_context` still says "reports in EUR", because that is a true statement
    about the ORGANISATION, and it is read straight from the settings rather than through
    here. What changes is only this — the unit printed against a number the platform read
    out of a warehouse and did not touch. When a converter exists, the org preference can
    win again, because then it will be true.

    ``profile_currency`` is itself inferred and can be wrong (see `BusinessProfile`), which
    is a separate defect with a separate fix; this function's job is to prefer the claim
    that is ABOUT the data over the one that is about the reader.
    """
    data_currency = (profile_currency or "").strip().upper()
    if data_currency:
        return data_currency
    return effective_settings(workspace_id).currency_code or "USD"


def resolve_industry(profile_industry: str = "", workspace_id: Optional[str] = None) -> str:
    """Effective industry: an explicitly-set org/workspace industry is
    authoritative; else the per-connection inferred value."""
    eff = effective_settings(workspace_id).industry
    return eff or (profile_industry or "").strip()


def org_context(workspace_id: Optional[str] = None, *, reading: str = "this brief") -> str:
    """A short 'ORGANIZATION:' block for prompt injection, built only from identity
    the user has EXPLICITLY declared. Returns '' when nothing is set, so callers can
    prepend it unconditionally without polluting prompts for unconfigured orgs.

    These settings are WORKSPACE-GLOBAL, so this describes the organization *using* Aughor —
    never the data being analysed. One workspace can hold several unrelated datasets as
    schemas, and stating this as the subject made a schema-scoped brief open "LuxExperience
    has aggressively scaled content production…" over a Netflix title catalog. Callers that
    brief a specific dataset must also say what that dataset IS.

    ``reading`` names the artifact this block is being prepended to. It defaults to
    "this brief" — the wording every existing caller already emits, so their prompts
    are byte-identical — and exists because the block had only three callers, none of
    them the quick answer path: the declared industry and currency were invisible to
    the surface people actually use, and telling an answer's reader they are "reading
    this brief" would be a small lie in service of reuse."""
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
    # "reading …", not a claim of ownership over the data.
    return f"ORGANIZATION reading {reading}: {line}.\n" if line else ""
