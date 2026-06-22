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
    Schema,
    catalog_securable,
    schema_securable,
    securable_catalog_id,
    securable_schema,
    workspace_principal,
)
from aughor.metastore.store import (
    add_grant,
    delete_catalog,
    get_catalog,
    grants_for_workspace,
    list_catalogs,
    list_grants,
    list_schemas,
    revoke_grant,
    set_catalog_schemas,
    upsert_catalog,
    upsert_schema,
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
    "Catalog", "Grant", "Schema", "USAGE",
    "workspace_principal", "catalog_securable", "securable_catalog_id",
    "schema_securable", "securable_schema",
    # store
    "upsert_catalog", "get_catalog", "list_catalogs", "delete_catalog",
    "add_grant", "revoke_grant", "list_grants", "grants_for_workspace",
    "upsert_schema", "list_schemas", "set_catalog_schemas",
    # sync + resolver
    "sync_metastore_from_registry", "ensure_catalogs_for_connections",
    "ensure_grants_for_memberships", "reconcile_workspace_grants",
    "granted_catalog_ids", "accessible_catalog_ids",
]
