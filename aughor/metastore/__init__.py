"""The metastore — org-level namespace + access registry (PLATFORM_ARCHITECTURE.md
Phase 2). Catalog (the unit of isolation, = a connection within an org) + Grant
(workspace → catalog) as first-class objects.

Catalogs and grants are *derived* from the connection registry and workspace
membership. The live data-path gate is now `accessible_catalog_ids()` (reconcile-on-
read, wired into the router visibility gates) — it routes the gate through the
metastore while staying provably equal to the legacy `workspace_connection_ids()`
gate. Making grants fully authoritative (independent of membership) is a later step.
"""
from aughor.metastore.models import (
    USAGE,
    Catalog,
    Grant,
    catalog_securable,
    securable_catalog_id,
    workspace_principal,
)
from aughor.metastore.store import (
    add_grant,
    delete_catalog,
    get_catalog,
    grants_for_workspace,
    list_catalogs,
    list_grants,
    revoke_grant,
    upsert_catalog,
)
from aughor.metastore.sync import (
    accessible_catalog_ids,
    ensure_catalogs_for_connections,
    ensure_grants_for_memberships,
    granted_catalog_ids,
    reconcile_workspace_grants,
    sync_metastore_from_registry,
)

__all__ = [
    # models
    "Catalog", "Grant", "USAGE",
    "workspace_principal", "catalog_securable", "securable_catalog_id",
    # store
    "upsert_catalog", "get_catalog", "list_catalogs", "delete_catalog",
    "add_grant", "revoke_grant", "list_grants", "grants_for_workspace",
    # sync + resolver
    "sync_metastore_from_registry", "ensure_catalogs_for_connections",
    "ensure_grants_for_memberships", "reconcile_workspace_grants",
    "granted_catalog_ids", "accessible_catalog_ids",
]
