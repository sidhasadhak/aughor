"""Org data model — the tenant boundary above Workspace.

An Org is the top of the namespace (``org.catalog.schema.table`` internally; the
user sees the UC-standard three levels). Single-org in practice today, but every
persisted object is keyed by ``org_id`` so multi-tenant is additive. ``region`` is
present from day one even with one region (PLATFORM_ARCHITECTURE.md §8) so regional
federation is later a value, not a schema change.
"""
from __future__ import annotations

from pydantic import BaseModel

from aughor.org.context import DEFAULT_ORG_ID


class Org(BaseModel):
    """A tenant. Owns the metastore/catalogs in the target model; today it is the
    scope key stamped onto every workspace, connection, job, receipt and audit row."""

    id: str = DEFAULT_ORG_ID
    name: str = "Default"
    region: str = ""  # home region; one region today, per-region metastores later
    created_at: str = ""
    updated_at: str = ""
