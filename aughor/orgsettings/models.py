"""Org / workspace settings — identity, localization, and appearance.

Aughor is single-tenant with a multi-Workspace model. These settings follow a
HYBRID scope: an app-wide ``OrgSettings`` singleton holds the defaults, and any
Workspace may override a subset (workspace override > app default > model default).
The same model shape is used for the singleton AND for the resolved *effective*
settings of a workspace.

Override-wins over inference: ``currency_code`` and ``industry`` here, WHEN SET,
are authoritative over the per-connection values ``BusinessProfile`` infers from
the data (the user's "org setting is authoritative" choice). They default to ``""``
( = "not set — use the inferred value") so merely having a settings object never
silently clobbers good inference; only an explicit choice does.
"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class OrgSettings(BaseModel):
    """App-wide organization settings (the singleton) and the shape of a
    workspace's resolved effective settings."""

    # ── Identity ──
    company_name: str = Field(default="", description="Display name of the company/organization")
    website: str = Field(default="", description="Primary website URL, e.g. 'https://acme.com'")
    hq_location: str = Field(default="", description="HQ location, e.g. 'London, UK' or 'United States'")
    industry: str = Field(
        default="",
        description=(
            "Industry/vertical. When set, AUTHORITATIVE over the industry that "
            "BusinessProfile infers per connection. Empty = use the inferred value."
        ),
    )

    # ── Localization ──
    currency_code: str = Field(
        default="",
        description=(
            "ISO 4217 reporting currency, e.g. 'GBP'. When set, AUTHORITATIVE over the "
            "currency BusinessProfile infers from the data. Empty = use the inferred value."
        ),
    )
    timezone: str = Field(default="", description="IANA timezone, e.g. 'Europe/London'. Empty = UTC.")
    date_format: str = Field(
        default="",
        description="Display date format token, e.g. 'DD/MM/YYYY', 'MM/DD/YYYY', 'YYYY-MM-DD'. Empty = auto.",
    )
    fiscal_year_start_month: int = Field(
        default=1, ge=1, le=12, description="Month the fiscal year starts (1=January)"
    )

    # ── Appearance ──
    chart_palette: str = Field(
        default="", description="Named chart palette (e.g. 'tableau', 'colorblind'); empty = theme default"
    )

    @field_validator("currency_code")
    @classmethod
    def _norm_currency(cls, v: str) -> str:
        v = (v or "").strip().upper()
        if v and (len(v) != 3 or not v.isalpha()):
            raise ValueError("currency_code must be a 3-letter ISO 4217 code (or empty)")
        return v

    @field_validator(
        "company_name", "website", "hq_location", "industry", "timezone", "date_format", "chart_palette"
    )
    @classmethod
    def _strip(cls, v: str) -> str:
        return (v or "").strip()
