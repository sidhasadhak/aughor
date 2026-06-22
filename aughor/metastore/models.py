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


class Schema(BaseModel):
    """A schema within a catalog — the middle level of the UC three-part namespace
    `catalog.schema.table`. Synced from live introspection; identified by
    (catalog_id, name) within an org."""

    catalog_id: str
    name: str
    org_id: str = DEFAULT_ORG_ID
    created_at: str = ""
    updated_at: str = ""

    @property
    def full_name(self) -> str:
        return f"{self.catalog_id}.{self.name}"


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


def schema_securable(catalog_id: str, schema_name: str) -> str:
    """The grant securable string for a schema (the finer-grained securable that
    schema-level grants will use; modeled now, enforced later)."""
    return f"schema:{catalog_id}.{schema_name}"


def securable_schema(securable: str) -> tuple[str, str] | None:
    """The (catalog_id, schema_name) encoded in a schema securable, or None."""
    prefix = "schema:"
    if not securable.startswith(prefix):
        return None
    rest = securable[len(prefix):]
    cat, _, name = rest.partition(".")
    return (cat, name) if name else None


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
