"""Persistence + resolution for org/workspace settings.

The app-level ``OrgSettings`` is a singleton persisted as JSON in
``data/org_settings.json`` (mirroring the profile store). Per-workspace overrides
live on the Workspace row (``settings_override``). ``effective_settings(workspace_id)``
merges them with precedence: **workspace override > app default > model default**.

``resolve_industry`` implements override-wins over the inference; a figure's currency
deliberately does NOT — it is a property of the figure, not of the reader, nothing here
converts, and since 2026-10-23 only a person's confirmation per dataset labels one
(``data_currency`` / ``figure_currency``). Otherwise, override-wins over the
per-connection ``BusinessProfile``: an explicitly-set org/workspace value is
authoritative; otherwise the inferred value stands.
"""
from __future__ import annotations

import datetime as _dt
import re

import json
from pathlib import Path
from typing import Optional

from aughor.db.sqlite_util import resolve_db_path
from aughor.orgsettings.models import OrgSettings

#: ``AUGHOR_ORG_SETTINGS_FILE`` overrides it, and the test conftest points it at a throwaway file:
#: without one the suite read the live settings, and a Briefing test failed on what this install's
#: organisation had declared (2026-10-03).
_PATH = resolve_db_path("AUGHOR_ORG_SETTINGS_FILE",
                        Path(__file__).parent.parent.parent / "data" / "org_settings.json")


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


_SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥", "CNY": "¥", "INR": "₹"}


def currency_symbol(code: Optional[str]) -> str:
    """Display symbol for an ISO currency code; falls back to the bare code so an
    unmapped currency still reads as '<CODE> 1,234' rather than a wrong '$'.

    No code is no symbol (2026-10-23, the user's decision on the Olist study's Gap 14): a figure
    whose currency no person has confirmed prints as a plain amount, never under a default "$"."""
    if not code:
        return ""
    return _SYMBOLS.get(code.upper(), f"{code.upper()} ")


#: Where a person's confirmed currency is kept: the connection's settings (a person's own
#: declarations about a connection), one entry per dataset — "" is the connection as a whole.
CURRENCIES_KEY = "currencies"
_ISO = re.compile(r"^[A-Z]{3}$")


def data_currency(conn_id: str, schema: Optional[str] = None) -> dict:
    """The currency a figure from one DATASET (a connection and schema) is in, and whose word it is.

    ``code`` is set only when a PERSON confirmed it — then it labels every figure from the dataset.
    The business profile's ``currency_code`` is the model's inference: a PROPOSAL (``inferred``),
    shown beside a Confirm door and never printed in front of a number. Until a person confirms,
    figures print as plain amounts and the page says the currency is unconfirmed (the user's
    decisions of 2026-10-23: proposed by the Profile, confirmed by a person, per dataset — one
    connection held Olist in reais and a franchise in euros, so a workspace currency would mislabel one).

    The org setting describes the ORGANISATION ("reports in EUR", ``org_context``) and labels no
    warehouse figure: nothing in this tree converts currency, so it would relabel (2026-09-23)."""
    from aughor.db.registry import get_connection_settings
    key = schema or ""
    held = dict(((get_connection_settings(conn_id) or {}).get(CURRENCIES_KEY) or {}).get(key) or {})
    inferred, profile_confidence = "", None
    try:
        from aughor.business_profile import store as pstore
        prof = ((pstore.load_raw(conn_id, schema) or {}).get("profile") or {})
        inferred = str(prof.get("currency_code") or "").strip().upper()
        profile_confidence = prof.get("confidence")
    except Exception as exc:  # noqa: BLE001 — no proposal is said as none, never guessed
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the profile's currency could not be read", counter="orgsettings.currency.profile")
    code = str(held.get("code") or "").strip().upper()
    return {"connection_id": conn_id, "schema_name": schema, "code": code,
            "status": "confirmed" if code else ("inferred" if inferred else "unknown"),
            "inferred": inferred, "profile_confidence": profile_confidence,
            "confirmed_by": str(held.get("by") or ""), "confirmed_at": str(held.get("at") or "")}


def figure_currency(conn_id: str, schema: Optional[str] = None) -> str:
    """The code that labels a figure from this dataset — a person's confirmed one, or "" (a plain
    amount, said to be unconfirmed). Never the model's inference and never the org's preference."""
    if not conn_id:
        return ""
    try:
        return data_currency(conn_id, schema)["code"]
    except Exception as exc:  # noqa: BLE001 — unknown is unconfirmed, never a default
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the dataset's currency could not be read; figures print unlabelled",
                 counter="orgsettings.currency.read")
        return ""


def confirm_currency(conn_id: str, schema: Optional[str], code: str, *, actor: str) -> dict:
    """A person states the dataset's currency (or clears it with ""). Kept with who said it and
    when — provenance is required, and this is the only door that writes it."""
    from aughor.db.registry import get_connection_settings, update_connection_settings
    code = (code or "").strip().upper()
    if code and not _ISO.match(code):
        raise ValueError("a currency is a three-letter ISO 4217 code, e.g. BRL")
    held = dict((get_connection_settings(conn_id) or {}).get(CURRENCIES_KEY) or {})
    key = schema or ""
    if code:
        before = dict(held.get(key) or {})
        held[key] = {"code": code, "by": actor or "", "at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
                     "inferred": data_currency(conn_id, schema)["inferred"],
                     **({"was": before.get("code")} if before.get("code") and before.get("code") != code else {})}
    else:
        held.pop(key, None)
    update_connection_settings(conn_id, {CURRENCIES_KEY: held})
    return data_currency(conn_id, schema)


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
