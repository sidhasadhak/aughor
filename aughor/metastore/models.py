"""Metastore data models — Catalog + Grant (PLATFORM_ARCHITECTURE.md §2/§3).

The metastore is the org-level namespace + access registry (Unity Catalog model).
A **Catalog** is the unit of data isolation; today it *is* a connection within an
org (1:1, `id == conn_id`), so the existing connection abstraction is unchanged and
the mapping is trivial. A **Grant** gives a principal (a workspace) a privilege on a
securable (a catalog) — the thing that will replace the flat
`workspace.connection_ids` membership gate.

Grants are UC-shaped (`principal` / `securable` / `privilege`) so finer securables
(schema/table) and privileges extend the same model without a reshape.
"""
from __future__ import annotations

from pydantic import BaseModel

from aughor.org.context import DEFAULT_ORG_ID


class Catalog(BaseModel):
    """A data domain within an org — the unit of isolation. Backed 1:1 by a
    connection today (`id == conn_id`)."""

    id: str                        # == backing conn_id (stable, unique within org)
    org_id: str = DEFAULT_ORG_ID
    name: str = ""                 # connection display name
    conn_id: str = ""              # the backing connection
    created_at: str = ""
    updated_at: str = ""


def workspace_principal(workspace_id: str) -> str:
    """The grant principal string for a workspace."""
    return f"workspace:{workspace_id}"


def catalog_securable(catalog_id: str) -> str:
    """The grant securable string for a catalog."""
    return f"catalog:{catalog_id}"


def securable_catalog_id(securable: str) -> str | None:
    """The catalog id encoded in a securable string, or None if it isn't a catalog."""
    prefix = "catalog:"
    return securable[len(prefix):] if securable.startswith(prefix) else None


# The coarse, foundation-level privilege: "may access this catalog at all" — the
# UC USAGE privilege. Finer privileges (SELECT/MODIFY/...) extend this later.
USAGE = "USAGE"


class Grant(BaseModel):
    """A privilege a principal holds on a securable. Foundation grants are
    `workspace → catalog` USAGE, mirroring today's membership."""

    id: str
    org_id: str = DEFAULT_ORG_ID
    principal: str                 # e.g. "workspace:{ws_id}"
    securable: str                 # e.g. "catalog:{catalog_id}"
    privilege: str = USAGE
    created_at: str = ""
