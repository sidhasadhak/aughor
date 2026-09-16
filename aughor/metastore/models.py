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


def user_principal(user_id: str) -> str:
    """The grant principal string for a person."""
    return f"user:{user_id}"


def group_principal(group_id: str) -> str:
    """The grant principal string for a group (HB-1) — a grant held by every member."""
    return f"group:{group_id}"


def agent_principal(agent_id: str) -> str:
    """The grant principal string for an agent (HB-1) — the service-principal shape:
    an agent in a function group inherits the group's grants like any member."""
    return f"agent:{agent_id}"


def principal_kind(principal: str) -> str:
    """The leading kind of a principal string (``user`` / ``group`` / ``agent`` /
    ``workspace``), or ``""`` when it is not one — the principal-side sibling of
    :func:`securable_kind`, so routing can branch without a chain of prefix tests."""
    head, sep, _ = str(principal or "").partition(":")
    return head if sep and head in ("user", "group", "agent", "workspace") else ""


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


def table_securable(catalog_id: str, schema_name: str, table: str) -> str:
    """The securable string for one table — the finest data grain.

    Added by Wave G2 so the governed tag plane names objects in the vocabulary that
    already exists here, instead of minting a second id scheme in ``aughor/govern``. The
    repo has paid for parallel dialects before (Wave V found *thirteen* incompatible
    spellings of "this is out of date", five of them for one fingerprint), and an access
    decision that disagrees with a grant about which object it is talking about is the
    worst possible place to discover the next one.
    """
    return f"table:{catalog_id}.{schema_name}.{table}"


def securable_table(securable: str) -> tuple[str, str, str] | None:
    """The ``(catalog_id, schema_name, table)`` in a table securable, or ``None``."""
    prefix = "table:"
    if not securable.startswith(prefix):
        return None
    parts = securable[len(prefix):].split(".")
    return (parts[0], parts[1], ".".join(parts[2:])) if len(parts) >= 3 else None


def artifact_securable(kind: str, artifact_id: str) -> str:
    """The securable string for a governed artifact (a brief, canvas, saved query…).

    Artifacts are not data objects, but they *carry* data — a published brief can quote
    the rows a clearance exists to withhold — so they are securables too.
    """
    return f"artifact:{kind}:{artifact_id}"


# HB-1 — the ontology's things become securables the way catalogs and artifacts already
# are: one string vocabulary, so a grant and an access decision can never disagree about
# which object they are talking about (the Wave G2 lesson, thirteen spellings, above).
# ``domain:`` is the grant-bearing tag's securable (§6 item 24 (b)): a grant on
# ``domain:supply-chain`` covers every object tagged ``domain=supply-chain`` — which is
# what makes a function group self-maintaining when a promise is declared next month.

_ONTOLOGY_SECURABLE_KINDS = (
    "metric", "promise", "process", "rule", "domain", "automation", "agent", "canvas",
)

_ALL_SECURABLE_KINDS = ("catalog", "schema", "table", "artifact") + _ONTOLOGY_SECURABLE_KINDS


def thing_securable(kind: str, thing_id: str) -> str:
    """The securable string for one of the ontology's things or a runtime object —
    ``metric: promise: process: rule: domain: automation: agent: canvas:``. Raises on a
    kind outside the vocabulary so a typo cannot mint a securable no grant will match."""
    k = (kind or "").strip().lower()
    if k not in _ONTOLOGY_SECURABLE_KINDS:
        raise ValueError(f"not a securable kind: {kind!r} (one of {_ONTOLOGY_SECURABLE_KINDS})")
    return f"{k}:{thing_id}"


def domain_securable(domain: str) -> str:
    """The securable a ``domain=<value>`` tag binds its objects to (§6 item 24 (b))."""
    return f"domain:{domain}"


def securable_kind(securable: str) -> str:
    """The leading kind of any securable string (``catalog`` / ``schema`` / ``table`` /
    ``artifact``, and since HB-1 the ontology's things — ``metric`` / ``promise`` /
    ``process`` / ``rule`` / ``domain`` / ``automation`` / ``agent`` / ``canvas``), or
    ``""`` when it is not one. Lets a caller branch without a chain of
    prefix tests, and keeps the set of kinds readable in one place."""
    head, sep, _ = str(securable or "").partition(":")
    return head if sep and head in _ALL_SECURABLE_KINDS else ""


# The coarse, foundation-level privilege: "may access this catalog at all" — the
# UC USAGE privilege. Finer privileges (SELECT/MODIFY/...) extend this later.
USAGE = "USAGE"


class Grant(BaseModel):
    """A privilege a principal holds on a securable — `workspace → catalog` USAGE
    today. An independent access-control record: the data-path gate is
    `membership ∪ explicit grants`, so an explicit grant adds access to a catalog
    beyond a workspace's connection membership."""

    id: str
    org_id: str = DEFAULT_ORG_ID
    principal: str                 # e.g. "workspace:{ws_id}"
    securable: str                 # e.g. "catalog:{catalog_id}"
    privilege: str = USAGE
    source: str = "explicit"       # "explicit" (gate reads these) | "membership" (legacy)
    created_at: str = ""
